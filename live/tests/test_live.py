"""Live pipeline tests: python -m pytest live/tests (needs aiohttp; the Functions test needs azure-functions)."""
from __future__ import annotations

import asyncio
import importlib
import json
import os
import sys
import time

import pytest

from live import claims
from live.pipeline import ROOT, Pipeline, load_match

aiohttp = pytest.importorskip("aiohttp")
from live.local import LiveServer  # noqa: E402

MATCH = os.path.join(ROOT, "matchgen", "sample", "demo_seed587")
KINDS = {"snapshot", "insight", "rating", "event"}

INSIGHT = {
    "id": "i_0001", "t": 95.0, "clock": "01:35", "kind": "anchor", "point_id": "anchor-ARD_05",
    "team": "ARD", "subject": "ARD_05",
    "text": {"casual": "a", "tactical": "b", "commentator": "c"},
    "evidence_for": ["e_000010"], "evidence_against": [], "trivia": [],
    "check": {"passed": True, "numbers_checked": 1, "retries": 0, "issues": []},
    "receipt": {"model": None, "latency_ms": 0, "tokens_in": 0, "tokens_out": 0, "agents": []},
}
RATING = {"t": 60.0, "rating": 6.1, "delta": 0.1,
          "reasons": [{"event_id": "e_000005", "label": "Pass", "effect": 0.1}]}
CLAIM = {"t": 120.0, "claim": "Arden are on top", "response": {
    "claim": "Arden are on top", "verdict": "partly", "summary": {"casual": "x", "tactical": "y"},
    "tests": [], "evidence_for": [], "evidence_against": [],
    "check": {"passed": True, "numbers_checked": 0, "retries": 0},
    "receipt": {"model": None, "latency_ms": 0, "mode": "fallback"}}}


@pytest.fixture()
def data_dir(tmp_path):
    (tmp_path / "insights.json").write_text(json.dumps(
        {"match_id": "m_seed587", "generated_at": "x", "mode": "fallback", "model": None, "items": [INSIGHT]}))
    (tmp_path / "ratings.json").write_text(json.dumps(
        {"every_s": 60, "formula": "test", "players": {"ARD_05": [RATING]}}))
    (tmp_path / "claims.sample.json").write_text(json.dumps({"claims": [CLAIM]}))
    return str(tmp_path)


def check_shape(m: dict) -> None:
    assert set(m) == {"kind", "match_id", "data"}
    assert m["kind"] in KINDS and m["match_id"] == "m_seed587" and isinstance(m["data"], dict)
    d = m["data"]
    if m["kind"] == "snapshot":
        assert {"elapsed", "clock", "score", "teams", "players"} <= set(d)
        assert "last_5_min" in d["teams"]["ARD"]
    elif m["kind"] == "event":
        assert "type" in d and "elapsed" in d


async def _serve(server: LiveServer):
    runner = aiohttp.web.AppRunner(server.app())
    await runner.setup()
    site = aiohttp.web.TCPSite(runner, "localhost", 0)
    await site.start()
    port = runner.addresses[0][1]
    return runner, port


def test_snapshot_within_a_second(data_dir):
    async def go():
        server = LiveServer(MATCH, speed=600, data_dir=data_dir)
        runner, port = await _serve(server)
        t0 = time.monotonic()
        try:
            async with aiohttp.ClientSession() as s:
                async with s.ws_connect(f"ws://localhost:{port}/ws") as ws:
                    while True:
                        m = json.loads((await ws.receive(timeout=1.0)).data)
                        check_shape(m)
                        if m["kind"] == "snapshot":
                            return time.monotonic() - t0
        finally:
            await runner.cleanup()
    assert asyncio.run(go()) < 1.0


def test_stream_shapes_over_websocket(data_dir):
    async def go():
        server = LiveServer(MATCH, speed=2000, data_dir=data_dir)
        runner, port = await _serve(server)
        got = []
        try:
            async with aiohttp.ClientSession() as s:
                async with s.ws_connect(f"ws://localhost:{port}/ws") as ws:
                    while not any(m["kind"] == "event" and m["data"]["type"] == "match_end" for m in got):
                        got.append(json.loads((await ws.receive(timeout=10.0)).data))
                neg = await (await s.get(f"http://localhost:{port}/api/negotiate")).json()
                claim = await (await s.post(f"http://localhost:{port}/api/claims",
                                            json={"match_id": "m_seed587", "t": 125, "claim": "Arden are on top",
                                                  "lens": "casual", "lang": "en"})).json()
        finally:
            await runner.cleanup()
        return got, neg, claim
    got, neg, claim = asyncio.run(go())
    for m in got:
        check_shape(m)
    by_kind = {k: [m for m in got if m["kind"] == k] for k in KINDS}
    assert [m["data"] for m in by_kind["insight"]] == [INSIGHT]
    assert [m["data"] for m in by_kind["rating"]] == [{"player": "ARD_05", **RATING}]
    goals = [m for m in by_kind["event"] if m["data"]["type"] == "goal"]
    assert len(goals) == 5
    assert by_kind["snapshot"][-1]["data"]["score"] == {"ARD": 3, "HVL": 2}
    assert neg["url"].startswith("ws://localhost:")
    assert claim == CLAIM["response"]


def test_pipeline_order_and_timing(data_dir):
    """Snapshots every 30 s of match time, insights released only once their t has passed."""
    from matchgen.stream import merged
    meta, events, frames = load_match(MATCH)
    p = Pipeline(meta, data_dir=data_dir)
    out = []
    for t, kind, data in merged(events, frames):
        for m in p.feed(kind, data):
            out.append((t, m))
        if t > 400:
            break
    snaps = [m["data"]["elapsed"] for _, m in out if m["kind"] == "snapshot"]
    assert snaps[:4] == [0.0, 30.0, 60.0, 90.0]
    (t_insight,) = [t for t, m in out if m["kind"] == "insight"]
    assert t_insight >= INSIGHT["t"]
    cards = [m for _, m in out if m["kind"] == "event" and m["data"]["type"] == "card"]
    assert cards and cards[0]["data"]["event_id"] == "e_000125"


def test_claims_out_of_scope_without_backend(tmp_path):
    r = asyncio.run(claims.check({"claim": "anything", "t": 1}, str(tmp_path)))
    assert r["verdict"] == "out_of_scope" and r["receipt"]["mode"] == "fallback"
    assert {"claim", "verdict", "summary", "tests", "evidence_for", "evidence_against", "check", "receipt"} <= set(r)


def test_functions_app_publishes_to_match_group(data_dir, monkeypatch, tmp_path):
    pytest.importorskip("azure.functions")
    pytest.importorskip("azure.messaging.webpubsubservice")
    meta, events, _ = load_match(MATCH)
    matches = tmp_path / "matches" / "m_seed587"
    matches.mkdir(parents=True)
    (matches / "match.json").write_text(json.dumps(meta))
    monkeypatch.setenv("SIGHTLINE_DATA_DIR", str(tmp_path))
    for mod in ("live.pipeline", "live.claims"):
        importlib.reload(sys.modules[mod])
    sys.path.insert(0, os.path.join(ROOT, "live", "functions"))
    try:
        fa = importlib.import_module("function_app")
        importlib.reload(fa)
    finally:
        sys.path.pop(0)

    sent = []

    class FakeWps:
        def send_to_group(self, group, message, content_type=None):
            sent.append((group, json.loads(message), content_type))

        def get_client_access_token(self, **kw):
            return {"url": "wss://example/client/hubs/match?access_token=x", "kw": kw}

    class Ev:
        def __init__(self, m):
            self.body = json.dumps(m).encode()

        def get_body(self):
            return self.body

    monkeypatch.setattr(fa, "_client", FakeWps())
    batch = [{"kind": "match_start", "data": {"match_id": "m_seed587"}}]
    batch += [{"kind": "event", "data": e} for e in events if e["elapsed"] < 200]
    fa.match_events([Ev(m) for m in batch])
    assert sent and all(g == "m_seed587" and ct == "application/json" for g, _, ct in sent)
    for _, m, _ in sent:
        check_shape(m)
    assert {m["kind"] for _, m, _ in sent} >= {"snapshot", "event"}
    monkeypatch.delenv("SIGHTLINE_DATA_DIR")
    for mod in ("live.pipeline", "live.claims"):
        importlib.reload(sys.modules[mod])
