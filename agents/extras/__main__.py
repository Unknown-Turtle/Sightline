"""CLI: python -m agents.extras <ratings|claims|claims-sample|routines|translate|all> [--dir MATCH_DIR] [--out DIR]"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .common import DEFAULT_MATCH_DIR, VIEWER_DATA, Match


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m agents.extras")
    ap.add_argument("command", choices=["ratings", "claims", "claims-sample", "routines", "translate", "all"])
    ap.add_argument("--dir", default=str(DEFAULT_MATCH_DIR), help="match folder (match.json, events.jsonl ...)")
    ap.add_argument("--out", default=str(VIEWER_DATA), help="output folder for the viewer data files")
    ap.add_argument("--every", type=float, default=60.0, help="ratings interval in match seconds")
    ap.add_argument("--t", type=float, default=None, help="claims: match time in elapsed seconds")
    ap.add_argument("--claim", default=None, help="claims: the pundit claim to test")
    ap.add_argument("--lens", default="tactical")
    ap.add_argument("--lang", default="en")
    ap.add_argument("--insights", default=None, help="translate: path to insights.json (default <out>/insights.json)")
    ap.add_argument("--langs", default="es,fr,pt,ar")
    args = ap.parse_args(argv)
    out = Path(args.out)
    match = Match(args.dir, frames=args.command in ("claims", "claims-sample", "all"))

    if args.command in ("ratings", "all"):
        from .ratings import write_ratings
        data = write_ratings(match, out / "ratings.json", args.every)
        print(f"ratings.json: {len(data['players'])} players, {sum(len(v) for v in data['players'].values())} entries")
    if args.command == "claims":
        from .claims import check_claim
        if not args.claim or args.t is None:
            ap.error("claims needs --claim and --t")
        print(json.dumps(check_claim(match, args.claim, args.t, args.lens, args.lang), indent=1, ensure_ascii=False))
    if args.command in ("claims-sample", "all"):
        from .claims import write_sample
        data = write_sample(match, out / "claims.sample.json")
        print(f"claims.sample.json: {len(data['claims'])} claims, mode {data['mode']}")
    if args.command in ("routines", "all"):
        from .routines import write_routines
        data = write_routines(match, out / "routines.json")
        ev = data.get("evaluation") or {}
        print(f"routines.json: {len(data['patterns'])} patterns, precision {ev.get('precision')} recall {ev.get('recall')}")
    if args.command in ("translate", "all"):
        from .translate import write_translations
        src = Path(args.insights) if args.insights else out / "insights.json"
        res = write_translations(match, src, out, args.langs.split(","))
        for lang, info in res.items():
            print(f"insights.{lang}.json: {info}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
