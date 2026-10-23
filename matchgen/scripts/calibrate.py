"""Calibration check: simulate N unscripted matches and compare averages to target ranges.

Usage: python scripts/calibrate.py [N] [--demo]

Prints mean, min and max per metric (per team per match unless noted) and
flags anything outside the target range. With --demo, also simulates the demo
script over 20 seeds and compares the standout centre back ARD_05 with the
other Arden centre back on defensive actions.
"""
from __future__ import annotations

import os
import sys
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from matchgen.engine import simulate  # noqa: E402
from matchgen.script import DEMO_SCRIPT, Script  # noqa: E402
from matchgen.io import match_metadata  # noqa: E402
from matchgen.world import default_world  # noqa: E402

TARGETS: dict[str, tuple[float, float]] = {
    "goals_per_match": (2.5, 3.2),
    "shots": (11.5, 14.5),
    "xg": (1.2, 1.7),
    "xg_per_shot": (0.09, 0.13),
    "passes": (450, 620),
    "pass_accuracy": (0.80, 0.87),
    "tackles": (15, 24),
    "fouls": (9, 13),
    "yellow_cards": (1.4, 2.4),
    "sprints": (200, 320),
    "top_speed_kmh": (30.5, 34),
    "penalties_per_match": (0.15, 0.45),
}
# informational only (no range check)
INFO = ["gk_passes", "corners_per_match", "goal_kicks_per_match", "throw_ins_per_match",
        "possessions", "shots_inside_9m", "big_chances", "sim_seconds"]


DEFENSIVE_TYPES = ("tackle", "interception", "clearance", "block", "ball_recovery")


def defensive_actions(events: list[dict]) -> dict[str, int]:
    """Tackles + interceptions + clearances + blocks + recoveries per player."""
    out: dict[str, int] = defaultdict(int)
    for e in events:
        if e["type"] in DEFENSIVE_TYPES and e["player_id"]:
            out[e["player_id"]] += 1
    return dict(out)


def team_metrics(meta: dict, events: list[dict], frames: list[dict]) -> dict[str, dict[str, float]]:
    """Plain counts from the event and tracking files (independent of summary.py and stats.py)."""
    teams = [meta["home_team_id"], meta["away_team_id"]]
    m = {t: defaultdict(float) for t in teams}
    gk_ids = {p["id"] for p in meta["players"] if p["group"] == "GK"}
    poss_seen: dict[str, set[int]] = {t: set() for t in teams}
    for e in events:
        t = e["team_id"]
        ty = e["type"]
        poss_seen[e["possession_team_id"]].add(e["possession_id"])
        if ty == "pass":
            m[t]["passes"] += 1
            if e["outcome"] == "complete":
                m[t]["passes_complete"] += 1
            if e["player_id"] in gk_ids:
                m[t]["gk_passes"] += 1
        elif ty == "shot":
            m[t]["shots"] += 1
            m[t]["xg"] += e["extra"]["xg"]
            if e["extra"]["xg"] >= 0.35:
                m[t]["big_chances"] += 1
            if e["extra"]["distance_m"] < 9:
                m[t]["shots_inside_9m"] += 1
            if "penalty" in e["qualifiers"]:
                m[t]["penalties"] += 1
        elif ty == "goal":
            m[t]["goals"] += 1
        elif ty == "tackle":
            m[t]["tackles"] += 1
        elif ty == "foul":
            m[t]["fouls"] += 1
        elif ty == "card" and e["outcome"] in ("yellow", "second_yellow"):
            m[t]["yellows"] += 1
        elif ty == "ball_out":
            m[t][e["extra"].get("restart", "none")] += 1
    top: dict[str, float] = defaultdict(float)
    sprints: dict[str, int] = defaultdict(int)
    in_sprint: dict[str, bool] = defaultdict(bool)
    for f in frames:
        for pid, _x, _y, kmh in f["players"]:
            top[pid] = max(top[pid], kmh)
            if kmh >= 25.2 and not in_sprint[pid]:
                sprints[pid] += 1
            in_sprint[pid] = kmh >= 25.2
    for t in teams:
        m[t]["pass_accuracy"] = m[t]["passes_complete"] / m[t]["passes"] if m[t]["passes"] else 0.0
        m[t]["possessions"] = len(poss_seen[t])
        m[t]["top_speed_kmh"] = max((v for p, v in top.items() if p.startswith(t)), default=0.0)
        m[t]["sprints"] = sum(v for p, v in sprints.items() if p.startswith(t))
    return {t: dict(v) for t, v in m.items()}


def one_match(seed: int) -> dict[str, float]:
    import time
    t0 = time.perf_counter()
    eng = simulate(default_world(), seed=seed, match_id=f"cal{seed}")
    took = time.perf_counter() - t0
    meta = match_metadata(eng)
    tm = team_metrics(meta, eng.events, eng.frames)
    out: dict[str, float] = defaultdict(float)
    n = len(tm)
    per_team = ["shots", "xg", "passes", "pass_accuracy", "tackles", "fouls", "sprints", "top_speed_kmh",
                "possessions", "big_chances", "gk_passes", "shots_inside_9m"]
    for t, d in tm.items():
        for k in per_team:
            out[k] += d.get(k, 0.0) / n
        out["yellow_cards"] += d.get("yellows", 0.0) / n
        out["goals_per_match"] += d.get("goals", 0.0)
        out["penalties_per_match"] += d.get("penalties", 0.0)
        out["corners_per_match"] += d.get("corner", 0.0)
        out["goal_kicks_per_match"] += d.get("goal_kick", 0.0)
        out["throw_ins_per_match"] += d.get("throw_in", 0.0)
    out["xg_per_shot"] = out["xg"] / out["shots"] if out["shots"] else 0.0
    out["sim_seconds"] = took
    return dict(out)


def demo_standout(seed: int) -> tuple[float, float]:
    eng = simulate(default_world(), seed=seed, script=Script.from_dict(DEMO_SCRIPT), match_id=f"demo{seed}")
    acts = defensive_actions(eng.events)
    return acts.get("ARD_05", 0), acts.get("ARD_06", 0)


def fmt_row(name: str, vals: list[float], rng: tuple[float, float] | None) -> str:
    mean = sum(vals) / len(vals)
    lo, hi = min(vals), max(vals)
    flag = ""
    if rng is not None:
        flag = "  OK" if rng[0] <= mean <= rng[1] else f"  OUT OF RANGE (target {rng[0]} to {rng[1]})"
    return f"{name:22s} mean {mean:8.3f}  min {lo:8.3f}  max {hi:8.3f}{flag}"


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    n = int(args[0]) if args else 40
    seeds = list(range(1, n + 1))
    with ProcessPoolExecutor() as ex:
        rows = list(ex.map(one_match, seeds))
    bad = 0
    print(f"Calibration over {n} seeds (no script), per team per match unless noted")
    for k, rng in TARGETS.items():
        vals = [r[k] for r in rows]
        line = fmt_row(k, vals, rng)
        print(line)
        if "OUT OF RANGE" in line:
            bad += 1
    print("-- informational --")
    for k in INFO:
        print(fmt_row(k, [r[k] for r in rows], None))
    if "--demo" in sys.argv:
        with ProcessPoolExecutor() as ex:
            pairs = list(ex.map(demo_standout, range(1, 21)))
        a = sum(p[0] for p in pairs) / len(pairs)
        b = sum(p[1] for p in pairs) / len(pairs)
        print("-- demo script standout (20 seeds) --")
        print(f"ARD_05 (boost 12) defensive actions per match: {a:.1f}")
        print(f"ARD_06 (other CB)  defensive actions per match: {b:.1f}")
    print(f"{bad} metric(s) out of range" if bad else "all metrics in range")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
