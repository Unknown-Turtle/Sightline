"""Command line: python -m matchgen {generate,stream,summary,world}"""
from __future__ import annotations

import argparse
import json
import sys

from .engine import simulate
from .io import read_match, write_match
from .script import DEMO_SCRIPT, Script
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
           start_minute=a.start_minute)


def cmd_summary(a: argparse.Namespace) -> None:
    meta, events, frames = read_match(a.dir)
    s = summarise(events, frames, [meta["home_team_id"], meta["away_team_id"]])
    print(json.dumps({"final_score": meta["final_score"],
                      "teams": {t: {k: round(v, 3) for k, v in sorted(d.items())} for t, d in s.items()}},
                     indent=2))


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
    s.set_defaults(fn=cmd_stream)

    m = sub.add_parser("summary", help="print team stats for a generated match")
    m.add_argument("--dir", default="out/match")
    m.set_defaults(fn=cmd_summary)

    w = sub.add_parser("world", help="export the default world to JSON for editing")
    w.add_argument("--seed", type=int, default=2026)
    w.add_argument("--out", default="world.json")
    w.set_defaults(fn=cmd_world)

    a = p.parse_args(argv)
    a.fn(a)


if __name__ == "__main__":
    main()
