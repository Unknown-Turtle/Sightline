"""Command line: python -m agents build --match <dir> --history <dir> --out <file>"""
from __future__ import annotations

import argparse
import json
import os
import sys


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m agents", description="Sightline agent layer")
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build", help="read a match folder and the history archive, write insights.json")
    b.add_argument("--match", required=True, help="match folder with match.json and events.jsonl")
    b.add_argument("--history", default=None, help="history archive folder (CSV tables)")
    b.add_argument("--out", required=True, help="output insights.json path")
    b.add_argument("--fallback", action="store_true", help="ignore credentials and use template phrasing")
    b.add_argument("--max-items", type=int, default=None, help="stop after this many items (smoke tests)")
    b.add_argument("--quiet", action="store_true")
    args = ap.parse_args(argv)

    from .data import load_history, load_match
    from .llm import Foundry
    from .pipeline import build

    m = load_match(args.match)
    hist = load_history(args.history)
    foundry = None if args.fallback else Foundry()
    if foundry is not None and not foundry.configured:
        print("No FOUNDRY_ENDPOINT / FOUNDRY_DEPLOYMENT set: running in fallback mode (template phrasing).", file=sys.stderr)
        foundry = None
    result = build(m, hist, foundry, verbose=not args.quiet, max_items=args.max_items)
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=1, ensure_ascii=False)
        f.write("\n")
    failed = sum(1 for i in result["items"] if not i["check"]["passed"])
    llm = sum(1 for i in result["items"] if i["receipt"]["source"] == "llm")
    print(f"wrote {args.out}: {len(result['items'])} items, mode={result['mode']}, "
          f"llm-phrased={llm}, checker failures={failed}", file=sys.stderr)
    if foundry is not None and foundry.error:
        print(f"last model error: {foundry.error}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
