"""Quick match summary, used for calibration and sanity checks."""
from __future__ import annotations

import math
from collections import defaultdict


def summarise(events: list[dict], frames: list[dict], team_ids: list[str]) -> dict:
    keys = ["passes", "passes_complete", "crosses", "shots", "xg", "on_target", "goals", "tackles",
            "interceptions", "pressures", "fouls", "clearances", "take_ons", "carrys", "yellow",
            "second_yellow", "red", "subs"]
    out = {t: defaultdict(float, {k: 0.0 for k in keys}) for t in team_ids}
    poss_time = defaultdict(float)
    prev = None
    for e in events:
        t = e["team_id"]
        o = out[t]
        ty = e["type"]
        if ty == "pass":
            o["passes"] += 1
            if e["outcome"] == "complete":
                o["passes_complete"] += 1
            if "cross" in e["qualifiers"]:
                o["crosses"] += 1
        elif ty == "shot":
            o["shots"] += 1
            o["xg"] += e["extra"]["xg"]
            if e["outcome"] in ("goal", "saved"):
                o["on_target"] += 1
        elif ty == "goal":
            o["goals"] += 1
        elif ty in ("tackle", "interception", "pressure", "foul", "clearance", "take_on", "carry"):
            o[ty + "s"] += 1
        elif ty == "card":
            o[e["outcome"]] += 1
        elif ty == "substitution":
            o["subs"] += 1
        # possession share by time between consecutive on-ball events
        if prev is not None and e["elapsed"] - prev["elapsed"] < 15:
            poss_time[prev["possession_team_id"]] += e["elapsed"] - prev["elapsed"]
        prev = e
    total_poss = sum(poss_time.values()) or 1
    for t in team_ids:
        o = out[t]
        o["pass_accuracy"] = o["passes_complete"] / o["passes"] if o["passes"] else 0
        o["possession"] = poss_time[t] / total_poss
    # physical
    dist_by = defaultdict(float)
    top = defaultdict(float)
    sprint_count = defaultdict(int)
    in_sprint = defaultdict(bool)
    last = {}
    for f in frames:
        for pid, x, y, kmh in f["players"]:
            if pid in last:
                lx, ly, lt = last[pid]
                dt = f["elapsed"] - lt
                if dt <= 1.5:
                    dist_by[pid] += math.hypot(x - lx, y - ly)
            last[pid] = (x, y, f["elapsed"])
            top[pid] = max(top[pid], kmh)
            if kmh >= 25.2 and not in_sprint[pid]:
                sprint_count[pid] += 1
            in_sprint[pid] = kmh >= 25.2
    for t in team_ids:
        pids = [p for p in dist_by if p.startswith(t)]
        full = [dist_by[p] for p in pids if dist_by[p] > 7000]
        out[t]["avg_distance_km_90"] = (sum(full) / len(full) / 1000) if full else 0
        out[t]["team_distance_km"] = sum(dist_by[p] for p in pids) / 1000
        out[t]["top_speed_kmh"] = max((top[p] for p in pids), default=0)
        out[t]["sprints"] = sum(sprint_count[p] for p in pids)
    return {t: dict(v) for t, v in out.items()}
