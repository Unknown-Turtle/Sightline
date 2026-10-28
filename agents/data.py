"""Loading a generated match folder and the history archive, plus small helpers."""
from __future__ import annotations

import csv
import json
import os
import sys
from dataclasses import dataclass, field


def _ensure_matchgen_importable(match_dir: str) -> None:
    """Make `matchgen.stats` importable when the repo is run from its root."""
    # From the repo root, `import matchgen` finds the project folder (a namespace package),
    # not the library inside it, so look for the folder that holds matchgen/stats.py.
    try:
        import matchgen.stats  # noqa: F401
        return
    except ImportError:
        pass
    here = os.path.dirname(os.path.abspath(__file__))
    candidates = [os.path.join(here, "..", "matchgen"), os.path.join(match_dir, "..", ".."), os.path.join(match_dir, "..")]
    for cand in candidates:
        cand = os.path.abspath(cand)
        if os.path.isfile(os.path.join(cand, "matchgen", "stats.py")):
            if cand not in sys.path:
                sys.path.insert(0, cand)
            sys.modules.pop("matchgen", None)
            return


@dataclass
class Match:
    meta: dict
    events: list[dict]
    dir: str

    @property
    def match_id(self) -> str:
        return self.meta["match_id"]

    @property
    def home(self) -> str:
        return self.meta["home_team_id"]

    @property
    def away(self) -> str:
        return self.meta["away_team_id"]

    @property
    def teams(self) -> list[str]:
        return [self.home, self.away]

    def team_name(self, tid: str) -> str:
        for lu in self.meta["lineups"]:
            if lu["team_id"] == tid:
                return lu["name"]
        return tid

    def player_name(self, pid: str | None) -> str:
        if not pid:
            return "Unknown"
        for p in self.meta.get("players", []):
            if p["id"] == pid:
                return p["name"]
        return pid

    def surname(self, pid: str | None) -> str:
        return self.player_name(pid).split(" ")[-1]

    def team_of(self, pid: str) -> str:
        return pid.rsplit("_", 1)[0]

    @property
    def duration(self) -> float:
        return float(self.meta.get("duration_elapsed_s") or self.events[-1]["elapsed"])


def load_match(match_dir: str) -> Match:
    _ensure_matchgen_importable(match_dir)
    with open(os.path.join(match_dir, "match.json"), encoding="utf-8") as f:
        meta = json.load(f)
    events: list[dict] = []
    with open(os.path.join(match_dir, "events.jsonl"), encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                events.append(json.loads(line))
    events.sort(key=lambda e: e["elapsed"])
    return Match(meta=meta, events=events, dir=match_dir)


@dataclass
class History:
    dir: str
    tables: dict[str, list[dict]] = field(default_factory=dict)

    def rows(self, table: str) -> list[dict]:
        if table not in self.tables:
            path = os.path.join(self.dir, table + ".csv")
            if not os.path.exists(path):
                self.tables[table] = []
            else:
                with open(path, encoding="utf-8", newline="") as f:
                    self.tables[table] = list(csv.DictReader(f))
        return self.tables[table]


def load_history(history_dir: str | None) -> History | None:
    if not history_dir or not os.path.isdir(history_dir):
        return None
    return History(dir=history_dir)


def short_clock(clock: str) -> str:
    """'72:36.4' to '72:36', '45+2:10.0' to '45+2:10'."""
    return clock.split(".")[0] if "." in clock else clock
