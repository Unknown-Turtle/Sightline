"""Shared loading helpers: match folders, event streams, name indexes and StatsEngine replays."""
from __future__ import annotations

import json
import os
import sys
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MATCHGEN_DIR = ROOT / "matchgen"
DEFAULT_MATCH_DIR = MATCHGEN_DIR / "sample" / "demo_seed587"
DEFAULT_HISTORY_DIR = MATCHGEN_DIR / "sample" / "history"
VIEWER_DATA = ROOT / "viewer" / "public" / "data"

if str(MATCHGEN_DIR) not in sys.path:
    sys.path.insert(0, str(MATCHGEN_DIR))

from matchgen.stats import StatsEngine, rel_x, rel_point, in_box  # noqa: E402


def read_jsonl(path: Path) -> list[dict]:
    out = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=1)
        fh.write("\n")


class Match:
    """A loaded match folder: meta, events, optional frames, plus name and role indexes."""

    def __init__(self, match_dir: Path | str = DEFAULT_MATCH_DIR, frames: bool = False):
        self.dir = Path(match_dir)
        self.meta = json.load(open(self.dir / "match.json", encoding="utf-8"))
        self.events = read_jsonl(self.dir / "events.jsonl")
        self.frames = read_jsonl(self.dir / "tracking.jsonl") if frames and (self.dir / "tracking.jsonl").exists() else []
        self.match_id = self.meta["match_id"]
        self.home = self.meta["home_team_id"]
        self.away = self.meta["away_team_id"]
        self.teams = [self.home, self.away]
        self.team_names = {lu["team_id"]: lu["name"] for lu in self.meta["lineups"]}
        self.players = {p["id"]: p for p in self.meta["players"]}
        self.team_of: dict[str, str] = {}
        self.slot_of: dict[str, str] = {}
        self.routines: dict[str, list[dict]] = {}
        for lu in self.meta["lineups"]:
            self.routines[lu["team_id"]] = lu.get("routines", [])
            for entry in lu["starting_xi"]:
                self.team_of[entry["player_id"]] = lu["team_id"]
                self.slot_of[entry["player_id"]] = entry["slot"]
            for pid in lu["bench"]:
                self.team_of[pid] = lu["team_id"]
        for pid in self.players:
            self.team_of.setdefault(pid, pid.rsplit("_", 1)[0])
        # substitutes inherit the formation slot of the player they replace
        for e in self.events:
            if e["type"] == "substitution":
                x = e["extra"]
                self.slot_of[x["player_in"]] = self.slot_of.get(x["player_out"], self.players.get(x["player_in"], {}).get("position", "?"))
        self.by_id = {e["event_id"]: e for e in self.events}
        self.duration = float(self.meta.get("duration_elapsed_s") or self.events[-1]["elapsed"])

    # ---- names
    def name(self, pid: str | None) -> str:
        if pid is None:
            return "Unknown"
        return self.players.get(pid, {}).get("name", pid)

    def surname(self, pid: str | None) -> str:
        return self.name(pid).split(" ")[-1]

    def team_name(self, tid: str) -> str:
        return self.team_names.get(tid, tid)

    def other(self, tid: str) -> str:
        return self.away if tid == self.home else self.home

    def all_names(self) -> set[str]:
        """Every player name, surname and team name: the vocabulary the checker guards."""
        names: set[str] = set()
        for p in self.players.values():
            names.add(p["name"])
            names.add(p["name"].split(" ")[-1])
        for n in self.team_names.values():
            names.add(n)
            names.update(w for w in n.split(" ") if len(w) > 3)
        return names

    # ---- events
    def upto(self, t: float) -> list[dict]:
        return [e for e in self.events if e["elapsed"] <= t]

    def between(self, t0: float, t1: float) -> list[dict]:
        return [e for e in self.events if t0 < e["elapsed"] <= t1]

    def clock_at(self, t: float) -> str:
        last = None
        for e in self.events:
            if e["elapsed"] <= t:
                last = e
            else:
                break
        return last["clock"].split(".")[0] if last else "00:00"

    def score_at(self, t: float) -> dict[str, int]:
        score = {tid: 0 for tid in self.teams}
        for e in self.events:
            if e["elapsed"] > t:
                break
            if e["type"] == "goal":
                score = dict(e["score"])
        return score

    def engine_at(self, t: float, with_frames: bool = True) -> StatsEngine:
        """Replay events (and frames when loaded) up to t into a fresh StatsEngine."""
        eng = StatsEngine(self.meta)
        fi = 0
        frames = self.frames if with_frames else []
        for e in self.events:
            if e["elapsed"] > t:
                break
            while fi < len(frames) and frames[fi]["elapsed"] <= e["elapsed"]:
                eng.ingest_frame(frames[fi])
                fi += 1
            eng.ingest_event(e)
        while fi < len(frames) and frames[fi]["elapsed"] <= t:
            eng.ingest_frame(frames[fi])
            fi += 1
        return eng

    def snapshot_at(self, t: float, with_frames: bool = True) -> dict:
        return self.engine_at(t, with_frames).snapshot(at=t)


@lru_cache(maxsize=4)
def load_match(match_dir: str = str(DEFAULT_MATCH_DIR), frames: bool = False) -> Match:
    return Match(match_dir, frames=frames)


def foundry_config() -> dict | None:
    """Foundry settings from the environment, or None for fallback mode."""
    endpoint = os.environ.get("FOUNDRY_ENDPOINT")
    deployment = os.environ.get("FOUNDRY_DEPLOYMENT")
    if not endpoint or not deployment:
        return None
    return {"endpoint": endpoint.rstrip("/"), "deployment": deployment, "api_key": os.environ.get("FOUNDRY_API_KEY")}


def zone_text(e: dict) -> str:
    """Where an event happened, in the acting team's frame."""
    if not e.get("start"):
        return ""
    rx, ry = rel_point(e["start"], e["attack_dir"])
    if rx < 16.5 and 13.84 < ry < 54.16:
        return "in own box"
    if in_box(rx, ry):
        return "in the box"
    if rx < 35:
        return "in own third"
    if rx < 70:
        return "in midfield"
    return "in the final third"
