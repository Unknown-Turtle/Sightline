"""Write a simulated match to disk and read it back."""
from __future__ import annotations

import json
import os
from dataclasses import asdict

from .engine import MatchEngine
from .world import FORMATIONS

SCHEMA_VERSION = "0.2.0"


def match_metadata(eng: MatchEngine) -> dict:
    w = eng.world

    def lineup(ts):
        team = ts.team
        return {
            "team_id": team.id,
            "name": team.name,
            "formation": team.formation,
            "style": team.style,
            "starting_xi": [
                {"player_id": pid, "slot": role}
                for pid, (role, *_rest) in zip(team.starting_xi, FORMATIONS[team.formation])
            ],
            "bench": list(team.bench),
            "routines": [dict(r) for r in team.routines],
        }

    return {
        "schema_version": SCHEMA_VERSION,
        "match_id": eng.match_id,
        "competition": w.competition,
        "venue": w.venue,
        "home_team_id": w.home.id,
        "away_team_id": w.away.id,
        "final_score": {eng.home.id: eng.home.score, eng.away.id: eng.away.score},
        "referee": eng.context["referee"],
        "weather": eng.context["weather"],
        "attendance": eng.context["attendance"],
        "venue_capacity": eng.context["venue_capacity"],
        "kickoff_local": eng.context["kickoff_local"],
        "matchday": eng.context["matchday"],
        "stakes": eng.context["stakes"],
        "stoppage_seconds": {"1": eng.stoppage[1], "2": eng.stoppage[2]},
        "duration_elapsed_s": round(eng.elapsed, 1),
        "pitch": {"length_m": 105, "width_m": 68},
        "attack_direction": {
            "1": {w.home.id: 1, w.away.id: -1},
            "2": {w.home.id: -1, w.away.id: 1},
        },
        "tracking_hz": round(1.0 / eng.tracking_interval, 3),
        "lineups": [lineup(eng.home), lineup(eng.away)],
        "players": [asdict(p) for p in w.home.players + w.away.players],
    }


def write_match(eng: MatchEngine, out_dir: str) -> dict:
    os.makedirs(out_dir, exist_ok=True)
    meta = match_metadata(eng)
    with open(os.path.join(out_dir, "match.json"), "w") as f:
        json.dump(meta, f, indent=2)
    with open(os.path.join(out_dir, "events.jsonl"), "w") as f:
        for e in eng.events:
            f.write(json.dumps(e, separators=(",", ":")) + "\n")
    with open(os.path.join(out_dir, "tracking.jsonl"), "w") as f:
        for fr in eng.frames:
            f.write(json.dumps(fr, separators=(",", ":")) + "\n")
    # ground truth for routine detection, deliberately kept out of events.jsonl
    with open(os.path.join(out_dir, "routines_truth.jsonl"), "w") as f:
        for r in eng.routine_attempts:
            f.write(json.dumps(r, separators=(",", ":")) + "\n")
    return meta


def read_jsonl(path: str) -> list[dict]:
    with open(path) as f:
        return [json.loads(line) for line in f if line.strip()]


def read_match(in_dir: str) -> tuple[dict, list[dict], list[dict]]:
    with open(os.path.join(in_dir, "match.json")) as f:
        meta = json.load(f)
    events = read_jsonl(os.path.join(in_dir, "events.jsonl"))
    frames = read_jsonl(os.path.join(in_dir, "tracking.jsonl"))
    return meta, events, frames
