"""Command line: python -m matchgen {generate,stream,summary,snapshot,snapshots,history,world}"""
from __future__ import annotations

import argparse
import json
import sys

from .engine import simulate
from .history import build_history
from .io import read_match, write_match
from .script import DEMO_SCRIPT, Script
from .stats import StatsEngine, clock_to_elapsed, snapshots_every
from .summary import summarise
from .world import World, default_world


def _world(path: str | None) -> World:
    return World.load(path) if path else default_world()


def cmd_generate(a: argparse.Namespace) -> None:
    script = None
    if a.script == "demo":
        script = Script.from_dict(DEMO_SCRIPT)
    elif a.script:
        script = Script.load(a.script)
    eng = simulate(_world(a.world), seed=a.seed, script=script, tracking_hz=a.hz,
                   match_id=a.match_id or f"m_seed{a.seed}")
    meta = write_match(eng, a.out)
    print(json.dumps({"out": a.out, "final_score": meta["final_score"], "events": len(eng.events),
                      "frames": len(eng.frames)}), file=sys.stderr)


def cmd_stream(a: argparse.Namespace) -> None:
    from .stream import EventHubSink, StdoutSink, replay
    meta, events, frames = read_match(a.dir)
    sink = EventHubSink(meta["match_id"]) if a.sink == "eventhub" else StdoutSink()
    replay(meta, events, frames, speed=a.speed, sink=sink, include_frames=not a.no_frames,
           start_minute=a.start_minute, snapshot_every=a.snapshots)


def cmd_summary(a: argparse.Namespace) -> None:
    meta, events, frames = read_match(a.dir)
    s = summarise(meta, events, frames)
    for d in s.values():
        d.pop("pass_network", None)
        d.pop("last_5_min", None)
    print(json.dumps({"final_score": meta["final_score"], "teams": s}, indent=2))


def cmd_snapshot(a: argparse.Namespace) -> None:
    meta, events, frames = read_match(a.dir)
    at = clock_to_elapsed(a.at, meta)
    engine = StatsEngine(meta)
    for e in events:
        if e["elapsed"] <= at:
            engine.ingest_event(e)
    for f in frames:
        if f["elapsed"] <= at:
            engine.ingest_frame(f)
    print(json.dumps(engine.snapshot(at=at), indent=2))


def cmd_snapshots(a: argparse.Namespace) -> None:
    meta, events, frames = read_match(a.dir)
    n = 0
    with open(a.out, "w") as f:
        for snap in snapshots_every(meta, events, frames, a.every):
            f.write(json.dumps(snap, separators=(",", ":")) + "\n")
            n += 1
    print(json.dumps({"out": a.out, "snapshots": n, "every_s": a.every}), file=sys.stderr)


def cmd_history(a: argparse.Namespace) -> None:
    hist = build_history(a.seed, _world(a.world))
    counts = hist.write(a.out)
    print(json.dumps({"out": a.out, "seed": a.seed, "tables": counts}), file=sys.stderr)


def cmd_world(a: argparse.Namespace) -> None:
    w = default_world(a.seed)
    with open(a.out, "w") as f:
        json.dump(w.to_dict(), f, indent=2)
    print(f"wrote {a.out}", file=sys.stderr)


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(prog="matchgen", description="Synthetic football match generator")
    sub = p.add_subparsers(dest="cmd", required=True)

    g = sub.add_parser("generate", help="simulate a match and write it to a folder")
    g.add_argument("--seed", type=int, default=1)
    g.add_argument("--out", default="out/match")
    g.add_argument("--script", help="storyline JSON file, or 'demo'")
    g.add_argument("--world", help="world JSON (clubs and players); defaults to the built-in world")
    g.add_argument("--hz", type=float, default=1.0, help="tracking frames per second (1 or 5)")
    g.add_argument("--match-id")
    g.set_defaults(fn=cmd_generate)

    s = sub.add_parser("stream", help="replay a generated match as a live feed")
    s.add_argument("--dir", default="out/match")
    s.add_argument("--speed", type=float, default=30.0, help="30 = 90 minutes in about 3")
    s.add_argument("--sink", choices=["stdout", "eventhub"], default="stdout")
    s.add_argument("--no-frames", action="store_true", help="events only")
    s.add_argument("--start-minute", type=float, default=0.0)
    s.add_argument("--snapshots", type=float, default=None, metavar="SECONDS",
                   help="interleave stats snapshots every N seconds of match time")
    s.set_defaults(fn=cmd_stream)

    m = sub.add_parser("summary", help="print full-time team stats for a generated match")
    m.add_argument("--dir", default="out/match")
    m.set_defaults(fn=cmd_summary)

    sn = sub.add_parser("snapshot", help="print the stats snapshot at a moment, e.g. --at 14:00 or 90+3:00")
    sn.add_argument("--dir", default="out/match")
    sn.add_argument("--at", required=True, help="broadcast clock: 14, 14:00, 45+2:00, 90+3:00")
    sn.set_defaults(fn=cmd_snapshot)

    ss = sub.add_parser("snapshots", help="write a snapshot every N seconds of match time (plus half and full time)")
    ss.add_argument("--dir", default="out/match")
    ss.add_argument("--every", type=float, default=30.0)
    ss.add_argument("--out", default="out/match/snapshots.jsonl")
    ss.set_defaults(fn=cmd_snapshots)

    h = sub.add_parser("history", help="generate the fictional league history (CSV and JSONL tables)")
    h.add_argument("--seed", type=int, default=1)
    h.add_argument("--out", default="out/history")
    h.add_argument("--world", help="world JSON whose Arden and Hollow Vale squads get career logs")
    h.set_defaults(fn=cmd_history)

    w = sub.add_parser("world", help="export the default world to JSON for editing")
    w.add_argument("--seed", type=int, default=2026)
    w.add_argument("--out", default="world.json")
    w.set_defaults(fn=cmd_world)

    a = p.parse_args(argv)
    a.fn(a)


if __name__ == "__main__":
    main()
