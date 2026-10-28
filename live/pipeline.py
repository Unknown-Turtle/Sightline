"""The live pipeline shared by the local server and the Azure Functions app.

Feed it matchgen stream messages in match-time order ({"kind": "event" | "frame" | "snapshot" |
"match_start" | "match_end", "data": {...}}) and it returns the contract live messages
({"kind": "snapshot" | "insight" | "rating" | "event", "match_id": ..., "data": {...}}).

It runs `matchgen.stats.StatsEngine` incrementally and asks a list of sources for insights and
ratings. A source is any object with `on_event(event) -> list[msg]` and `until(t) -> list[msg]`.
Real detectors from `agents/` are used when they import; otherwise timed stubs replay the
precomputed `insights.json` and `ratings.json` items as match time passes them.
"""
from __future__ import annotations

import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in (ROOT, os.path.join(ROOT, "matchgen")):
    if os.path.isdir(_p) and _p not in sys.path:
        sys.path.insert(0, _p)

from matchgen.stats import BIG_CHANCE_XG, StatsEngine  # noqa: E402

DEFAULT_DATA_DIR = os.path.join(ROOT, "viewer", "public", "data")
INSTANT_TYPES = {"goal", "card", "period_end"}


def msg(kind: str, match_id: str, data: dict) -> dict:
    return {"kind": kind, "match_id": match_id, "data": data}


def is_instant(e: dict) -> bool:
    if e.get("type") in INSTANT_TYPES:
        return True
    return e.get("type") == "shot" and (e.get("extra") or {}).get("xg", 0.0) >= BIG_CHANCE_XG


def _load_json(path: str):
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


class TimedSource:
    """Releases precomputed (t, kind, data) items once match time passes t."""

    def __init__(self, match_id: str, items: list[tuple[float, str, dict]]):
        self.match_id = match_id
        self.items = sorted(items, key=lambda x: x[0])
        self.i = 0

    def on_event(self, event: dict) -> list[dict]:
        return []

    def until(self, t: float) -> list[dict]:
        out = []
        while self.i < len(self.items) and self.items[self.i][0] <= t:
            _, kind, data = self.items[self.i]
            out.append(msg(kind, self.match_id, data))
            self.i += 1
        return out


def insights_stub(match_id: str, data_dir: str) -> TimedSource | None:
    doc = _load_json(os.path.join(data_dir, "insights.json"))
    if not doc or doc.get("match_id", match_id) != match_id:
        return None
    return TimedSource(match_id, [(float(it["t"]), "insight", it) for it in doc.get("items", [])])


def ratings_stub(match_id: str, data_dir: str) -> TimedSource | None:
    doc = _load_json(os.path.join(data_dir, "ratings.json"))
    if not doc:
        return None
    items = []
    for pid, series in (doc.get("players") or {}).items():
        for r in series:
            items.append((float(r["t"]), "rating", {"player": pid, **r}))
    return TimedSource(match_id, items)


class AgentSource:
    """Wraps a live detector from agents/ that exposes ingest_event(event) -> list[item]."""

    def __init__(self, match_id: str, detector, kind: str):
        self.match_id, self.detector, self.kind = match_id, detector, kind

    def on_event(self, event: dict) -> list[dict]:
        try:
            return [msg(self.kind, self.match_id, it) for it in (self.detector.ingest_event(event) or [])]
        except Exception as exc:  # a detector bug must not stop the feed
            print(f"live: {self.kind} detector failed: {exc}", file=sys.stderr)
            return []

    def until(self, t: float) -> list[dict]:
        return []


def default_sources(meta: dict, data_dir: str = DEFAULT_DATA_DIR) -> list:
    """Agent detectors if importable (agents.live.LiveDetector, agents.extras.ratings.LiveRatings),
    otherwise the timed stubs over the precomputed files."""
    mid = meta["match_id"]
    sources = []
    try:
        from agents.live import LiveDetector  # type: ignore
        sources.append(AgentSource(mid, LiveDetector(meta), "insight"))
    except Exception:
        s = insights_stub(mid, data_dir)
        if s:
            sources.append(s)
    try:
        from agents.extras.ratings import LiveRatings  # type: ignore
        sources.append(AgentSource(mid, LiveRatings(meta), "rating"))
    except Exception:
        s = ratings_stub(mid, data_dir)
        if s:
            sources.append(s)
    return sources


class Pipeline:
    """Per-match state. Not thread safe: feed one match from one ordered stream."""

    def __init__(self, meta: dict, sources: list | None = None, snapshot_every: float = 30.0,
                 data_dir: str = DEFAULT_DATA_DIR):
        self.meta = meta
        self.match_id = meta["match_id"]
        self.engine = StatsEngine(meta)
        self.every = snapshot_every
        self.next_at = snapshot_every
        self.sources = default_sources(meta, data_dir) if sources is None else sources
        self.t = 0.0
        self.last_snapshot: dict | None = None
        self.started = False

    def _snapshot(self, at: float | None = None, label: str | None = None) -> dict:
        snap = self.engine.snapshot(at=at)
        if label:
            snap["label"] = label
        m = msg("snapshot", self.match_id, snap)
        self.last_snapshot = m
        return m

    def start(self) -> list[dict]:
        """Kick-off: a match_start control event and a snapshot at 0:00."""
        if self.started:
            return []
        self.started = True
        info = {k: self.meta.get(k) for k in ("match_id", "home_team_id", "away_team_id", "competition", "venue")}
        return [msg("event", self.match_id, {"type": "match_start", "elapsed": 0.0, **info}),
                self._snapshot(at=0.0, label="kick_off")]

    def _advance(self, t: float) -> list[dict]:
        out = []
        while t > self.next_at:
            out.append(self._snapshot(at=self.next_at))
            out.extend(self._timed(self.next_at))
            self.next_at += self.every
        return out

    def _timed(self, t: float) -> list[dict]:
        out = []
        for s in self.sources:
            out.extend(s.until(t))
        return out

    def feed(self, kind: str, data: dict) -> list[dict]:
        out = self.start()
        if kind in ("snapshot", "match_start"):
            return out  # we build our own snapshots from the same messages
        if kind == "match_end":
            out.append(self._snapshot(label="full_time"))
            out.append(msg("event", self.match_id, {"type": "match_end", "elapsed": self.t,
                                                     "final_score": data.get("final_score")}))
            return out
        t = float(data.get("elapsed", self.t))
        out.extend(self._advance(t))
        self.t = max(self.t, t)
        if kind == "frame":
            self.engine.ingest_frame(data)
        elif kind == "event":
            self.engine.ingest_event(data)
            if is_instant(data):
                out.append(msg("event", self.match_id, data))
            for s in self.sources:
                out.extend(s.on_event(data))
            if data.get("type") == "period_end":
                period = (data.get("extra") or {}).get("period", data.get("period"))
                out.append(self._snapshot(label="half_time" if period == 1 else "full_time"))
        out.extend(self._timed(self.t))
        return out


def load_match(match_dir: str) -> tuple[dict, list[dict], list[dict]]:
    from matchgen.io import read_match
    return read_match(match_dir)
