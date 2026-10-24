"""Search seeds with the demo script for a match that tells the demo story.

Usage: python scripts/find_demo_seed.py [first_seed] [last_seed]

Criteria:
- a Hollow Vale goal between minutes 55 and 75
- an Arden comeback: Arden behind at some point, then winning with the winner after minute 80
- 5 or fewer goals in total
- at least one big chance (xG 0.35 or more) missed
- the boosted standout ARD_05 among the top two Arden players for defensive actions
"""
from __future__ import annotations

import os
import sys
from collections import Counter
from concurrent.futures import ProcessPoolExecutor

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from matchgen.engine import simulate  # noqa: E402
from matchgen.script import DEMO_SCRIPT, Script  # noqa: E402
from matchgen.world import default_world  # noqa: E402

DEFENSIVE = ("tackle", "interception", "clearance", "block", "ball_recovery")


def check(seed: int) -> dict | None:
    eng = simulate(default_world(), seed=seed, script=Script.from_dict(DEMO_SCRIPT), match_id=f"m_seed{seed}")
    goals = [(e["minute"], e["clock"], e["team_id"], e["player_id"]) for e in eng.events if e["type"] == "goal"]
    if not goals or len(goals) > 5:
        return None
    if eng.home.score <= eng.away.score:
        return None
    if not any(t == "HVL" and 55 <= m <= 75 for m, _c, t, _p in goals):
        return None
    behind = False
    score = {"ARD": 0, "HVL": 0}
    winner_minute = None
    for m, _c, t, _p in goals:
        score[t] += 1
        if score["HVL"] > score["ARD"]:
            behind = True
        if t == "ARD" and score["ARD"] == score["HVL"] + 1:
            winner_minute = m
    if not behind or winner_minute is None or winner_minute <= 80:
        return None
    if score["ARD"] <= score["HVL"]:
        return None
    big_missed = sum(1 for e in eng.events if e["type"] == "shot" and e["extra"]["xg"] >= 0.35 and e["outcome"] != "goal")
    if big_missed < 1:
        return None
    acts = Counter(e["player_id"] for e in eng.events if e["type"] in DEFENSIVE and e["team_id"] == "ARD")
    top2 = [p for p, _ in acts.most_common(2)]
    if "ARD_05" not in top2:
        return None
    return {"seed": seed, "score": dict(score), "goals": goals, "big_chances_missed": big_missed,
            "ard_defensive_top": acts.most_common(3)}


def main() -> None:
    lo = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    hi = int(sys.argv[2]) if len(sys.argv) > 2 else 400
    with ProcessPoolExecutor() as ex:
        for res in ex.map(check, range(lo, hi + 1)):
            if res:
                print(res)


if __name__ == "__main__":
    main()
