"""Quick match summary: the full-time team blocks of the stats engine (matchgen/stats.py)."""
from __future__ import annotations

from .stats import StatsEngine


def summarise(meta: dict, events: list[dict], frames: list[dict]) -> dict:
    """Team metrics at full time, keyed by team id. One source of truth: StatsEngine."""
    engine = StatsEngine(meta)
    for e in events:
        engine.ingest_event(e)
    for f in frames:
        engine.ingest_frame(f)
    return engine.snapshot()["teams"]
