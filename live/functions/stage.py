"""Stage the Functions app into live/functions/build with everything it imports.

    python live/functions/stage.py [--match matchgen/sample/demo_seed587 ...]

Copies function_app.py, host.json, requirements.txt, the `live` package, the `matchgen` package,
`agents/` when present, each match's match.json (data/matches/<match_id>/match.json) and the
viewer data files the stubs read (insights.json, ratings.json, claims.sample.json, insights.<lang>.json).
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import shutil

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
IGNORE = shutil.ignore_patterns("__pycache__", "*.pyc", "tests", "functions", "infra")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--match", action="append", default=None, help="match folder (repeatable)")
    ap.add_argument("--out", default=os.path.join(HERE, "build"))
    a = ap.parse_args()
    out = a.out
    shutil.rmtree(out, ignore_errors=True)
    os.makedirs(out)
    for f in ("function_app.py", "host.json", "requirements.txt", ".funcignore"):
        shutil.copy(os.path.join(HERE, f), out)
    shutil.copytree(os.path.join(ROOT, "live"), os.path.join(out, "live"), ignore=IGNORE)
    shutil.copytree(os.path.join(ROOT, "matchgen", "matchgen"), os.path.join(out, "matchgen"), ignore=IGNORE)
    if os.path.isdir(os.path.join(ROOT, "agents")):
        shutil.copytree(os.path.join(ROOT, "agents"), os.path.join(out, "agents"), ignore=IGNORE)
    data = os.path.join(out, "data")
    os.makedirs(data)
    viewer_data = os.path.join(ROOT, "viewer", "public", "data")
    for pattern in ("insights*.json", "ratings.json", "routines.json", "claims.sample.json"):
        for f in glob.glob(os.path.join(viewer_data, pattern)):
            shutil.copy(f, data)
    for m in a.match or [os.path.join(ROOT, "matchgen", "sample", "demo_seed587")]:
        with open(os.path.join(m, "match.json")) as f:
            mid = json.load(f)["match_id"]
        os.makedirs(os.path.join(data, "matches", mid))
        shutil.copy(os.path.join(m, "match.json"), os.path.join(data, "matches", mid))
    print(out)


if __name__ == "__main__":
    main()
