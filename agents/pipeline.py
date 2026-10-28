"""Orchestration: checkpoints, agent handoffs and the insights.json writer.

Checkpoints: every 5 minutes of match time, plus immediately after each goal, red card and
half time (and full time). At each one: analyst -> trivia -> narrator -> checker, and at
half time and full time the recap agent. Plain Python orchestration with OpenTelemetry spans
around each agent step (no-op unless an OTel SDK and exporter are configured).
"""
from __future__ import annotations

import datetime as dt
import json
import time

from .analyst import analyse, describe
from .data import History, Match, short_clock
from .llm import Foundry
from .narrator import narrate
from .recap import recap_pack
from .trivia import trivia_for

try:
    from opentelemetry import trace
    _tracer = trace.get_tracer("sightline.agents")
except Exception:  # pragma: no cover - OTel is optional
    _tracer = None


def _span(name: str):
    if _tracer is None:
        import contextlib
        return contextlib.nullcontext()
    return _tracer.start_as_current_span(name)


CHECKPOINT_EVERY_S = 300.0
MOMENTUM_SAMPLE_S = 60.0


def checkpoints(m: Match) -> list[tuple[float, str]]:
    """(t, reason) pairs in time order."""
    out: list[tuple[float, str]] = []
    end = m.duration
    t = CHECKPOINT_EVERY_S
    while t < end:
        out.append((t, "interval"))
        t += CHECKPOINT_EVERY_S
    for e in m.events:
        if e["type"] == "goal":
            out.append((e["elapsed"], "goal"))
        elif e["type"] == "card" and e.get("outcome") in ("red", "second_yellow"):
            out.append((e["elapsed"], "red_card"))
        elif e["type"] == "period_end":
            out.append((e["elapsed"], "half_time" if e["period"] == 1 else "full_time"))
    out.sort(key=lambda x: (x[0], x[1] != "interval"))
    merged: list[tuple[float, str]] = []
    for t, reason in out:
        if merged and abs(merged[-1][0] - t) < 1e-6:
            if reason != "interval":
                merged[-1] = (t, reason)
            continue
        merged.append((t, reason))
    return merged


def _signature(pack: dict) -> str:
    """A point is re-emitted only when its numbers change (the clock minute does not count)."""
    return json.dumps({k: v for k, v in pack["numbers"].items() if k != "minute"}, sort_keys=True)


def build(m: Match, hist: History | None, foundry: Foundry | None, *, verbose: bool = False,
          max_items: int | None = None) -> dict:
    from matchgen.stats import StatsEngine

    engine = StatsEngine(m.meta)
    mode = "live" if (foundry is not None and foundry.configured) else "fallback"
    items: list[dict] = []
    last_sig: dict[str, str] = {}
    last_t: dict[str, float] = {}
    momentum_series: dict[str, list[tuple[float, float]]] = {t: [] for t in m.teams}
    next_sample = MOMENTUM_SAMPLE_S
    ev_index = 0
    events = m.events

    def ingest_until(t: float) -> None:
        nonlocal ev_index, next_sample
        while ev_index < len(events) and events[ev_index]["elapsed"] <= t:
            e = events[ev_index]
            while next_sample < e["elapsed"] and next_sample <= t:
                _sample(engine, next_sample, momentum_series)
                next_sample += MOMENTUM_SAMPLE_S
            engine.ingest_event(e)
            ev_index += 1
        while next_sample <= t:
            _sample(engine, next_sample, momentum_series)
            next_sample += MOMENTUM_SAMPLE_S

    seq = 0
    for t, reason in checkpoints(m):
        if max_items is not None and len(items) >= max_items:
            break
        with _span("checkpoint"):
            ingest_until(t)
            snap = engine.snapshot(at=t)
            clock = short_clock(snap["clock"])
            upto = events[:ev_index]
            with _span("analyst"):
                packs = analyse(m, upto, t, clock, snap, momentum_series)
            emitted = []
            for pack in packs:
                sig = _signature(pack)
                pid = pack["point_id"]
                key_moment = reason in ("half_time", "full_time")
                if last_sig.get(pid) == sig and not key_moment:
                    continue
                # momentum drifts a little every window; only re-emit it after 10 minutes
                # or when the shots in the window change
                if pack["kind"] == "momentum" and pid in last_t and not key_moment:
                    prev = json.loads(last_sig[pid])
                    if t - last_t[pid] < 600 and prev.get("shots_5min") == pack["numbers"]["shots_5min"]:
                        continue
                last_sig[pid] = sig
                last_t[pid] = t
                emitted.append(pack)
            if reason in ("half_time", "full_time"):
                score_pack = next(p for p in packs if p["kind"] == "score_state")
                strongest = [p for p in packs if p["kind"] not in ("score_state",)][:3]
                goals = [describe(m, e) for e in upto if e["type"] == "goal"]
                emitted.append(recap_pack(m, "ht" if reason == "half_time" else "ft", t, clock, snap, score_pack, strongest, goals))
            for pack in emitted:
                seq += 1
                item = _run_point(m, hist, foundry, pack, seq, mode)
                items.append(item)
                if verbose:
                    print(f"[{item['clock']}] {item['kind']:<11} {item['point_id']:<18} check={'ok' if item['check']['passed'] else 'FAIL'} "
                          f"src={item['receipt']['source']}  {item['text']['tactical'][:90]}")
    model = foundry.deployment if mode == "live" else None
    return {
        "match_id": m.match_id,
        "generated_at": dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "mode": mode,
        "model": model,
        "items": items,
    }


def _sample(engine, at: float, series: dict[str, list[tuple[float, float]]]) -> None:
    snap = engine.snapshot(at=at)
    for team, block in snap["teams"].items():
        series[team].append((at, float(block["last_5_min"]["momentum"])))


def _run_point(m: Match, hist: History | None, foundry: Foundry | None, pack: dict, seq: int, mode: str) -> dict:
    started = time.perf_counter()
    with _span("trivia"):
        trivia = trivia_for(hist, m, pack)
    with _span("narrator"):
        narration = narrate(pack, trivia, foundry)
    latency = int((time.perf_counter() - started) * 1000)
    model = None
    if narration.calls:
        model = narration.calls[-1].model
    return {
        "id": f"i_{seq:04d}",
        "t": float(pack["t"]),
        "clock": pack["clock"],
        "kind": pack["kind"],
        "point_id": pack["point_id"],
        "team": pack["team"],
        "subject": pack.get("subject"),
        "text": narration.text,
        "evidence_for": [e["event_id"] for e in pack["evidence_for"]],
        "evidence_against": [e["event_id"] for e in pack["evidence_against"]],
        "trivia": trivia,
        "check": narration.check.as_dict(narration.retries),
        "receipt": {
            "model": model,
            "latency_ms": latency,
            "tokens_in": sum(c.tokens_in for c in narration.calls),
            "tokens_out": sum(c.tokens_out for c in narration.calls),
            "agents": ["analyst", "trivia", "narrator", "checker"] + (["recap"] if pack["kind"] == "recap" else []),
            "mode": mode,
            "source": narration.source,
            "llm_calls": len(narration.calls),
        },
    }
