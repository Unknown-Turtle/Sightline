"""Routine detection: rehearsed pass sequences found from events.jsonl and match.json only.

Detection path (never reads routines_truth.jsonl):
  1. Every possession that starts from a routine trigger (goal kick, keeper distribution, or a regain
     or second ball inside the team's own third) is a candidate.
  2. Its opening passes are turned into a role chain (formation slot of passer to slot of receiver,
     substitutes inherit the slot of the player they replaced) with team-relative end points.
  3. Playbook matching: the public routine definitions in match.json (`lineups[].routines`) are used as
     templates. Steps are matched in order (`from` may be `*`), each pass must end within ZONE_M of the
     step's target zone. One or more matched steps is an attempt.
  4. Discovery: role chains of the first 3 passes that repeat 3 or more times from the same trigger are
     reported too, so a team's unnamed habits show up alongside the playbook.
Evaluation (report only) compares detected event ids and attempts against routines_truth.jsonl.
"""
from __future__ import annotations

from collections import defaultdict
from pathlib import Path

from .common import Match, VIEWER_DATA, read_jsonl, rel_point, write_json

ZONE_M = 15.0
OWN_THIRD_RX = 35.0
MAX_CHAIN = 4
MIN_DISCOVERED = 3


def trigger_of(first: dict) -> str | None:
    pat = first["play_pattern"]
    if pat in ("goal_kick", "keeper"):
        return pat
    if pat in ("regain", "second_ball") and first.get("start"):
        if rel_point(first["start"], first["attack_dir"])[0] < OWN_THIRD_RX:
            return "regain_own_third"
    return None


def possessions(match: Match) -> list[list[dict]]:
    out: dict[int, list[dict]] = defaultdict(list)
    for e in match.events:
        out[e["possession_id"]].append(e)
    return [out[k] for k in sorted(out)]


def opening_chain(match: Match, poss: list[dict]) -> list[dict]:
    """The opening completed passes of a possession as role steps, stopping at the first loss or shot."""
    team = poss[0]["possession_team_id"]
    chain = []
    for e in poss:
        if e["team_id"] != team:
            if e["type"] in ("pressure",):
                continue
            break
        if e["type"] == "pass":
            if e["outcome"] != "complete":
                break
            ex, ey = rel_point(e["end"], e["attack_dir"])
            chain.append({"event": e, "from": match.slot_of.get(e["player_id"], "?"),
                          "to": match.slot_of.get(e["extra"].get("receiver_id"), "?"), "end": (ex, ey)})
            if len(chain) >= MAX_CHAIN:
                break
        elif e["type"] in ("carry", "take_on", "pressure", "ball_recovery", "interception", "tackle"):
            if e["type"] in ("carry", "take_on") and e["outcome"] in ("dispossessed", "fail"):
                break
            continue
        else:
            break
    return chain


def match_template(routine: dict, chain: list[dict]) -> list[dict]:
    matched = []
    for step, link in zip(routine["steps"], chain):
        if step["from"] != "*" and step["from"] != link["from"]:
            break
        if step["to"] != link["to"]:
            break
        zx, zy = step["zone"]
        if ((link["end"][0] - zx) ** 2 + (link["end"][1] - zy) ** 2) ** 0.5 > ZONE_M:
            break
        matched.append(link)
    return matched


def possession_outcome(poss: list[dict], matched_all: bool) -> str:
    team = poss[0]["possession_team_id"]
    if any(e["type"] == "shot" and e["team_id"] == team for e in poss):
        return "shot"
    return "completed" if matched_all else "lost"


def detect(match: Match) -> dict:
    patterns: dict[str, dict] = {}
    for team, routines in match.routines.items():
        for r in routines:
            patterns[r["id"]] = {"id": r["id"], "team": team, "label": r["name"], "trigger": r["trigger"], "source": "playbook",
                                 "steps": [f"{s['from']} to {s['to']}" for s in r["steps"]], "attempts": [], "shots_from": 0}
    discovered: dict[tuple, dict] = {}
    for poss in possessions(match):
        first = poss[0]
        trig = trigger_of(first)
        if trig is None:
            continue
        team = first["possession_team_id"]
        chain = opening_chain(match, poss)
        if not chain:
            continue
        best, best_r = [], None
        for r in match.routines.get(team, []):
            if r["trigger"] != trig:
                continue
            m = match_template(r, chain)
            if len(m) > len(best):
                best, best_r = m, r
        if best_r is not None:
            full = len(best) == len(best_r["steps"])
            patterns[best_r["id"]]["attempts"].append({
                "t": best[0]["event"]["elapsed"], "clock": best[0]["event"]["clock"].split(".")[0], "possession_id": first["possession_id"],
                "event_ids": [l["event"]["event_id"] for l in best], "steps_matched": len(best), "steps_total": len(best_r["steps"]),
                "outcome": possession_outcome(poss, full)})
            continue
        key = (team, trig, tuple(f"{l['from']} to {l['to']}" for l in chain[:3]))
        if len(key[2]) < 2:
            continue
        d = discovered.setdefault(key, {"team": team, "trigger": trig, "steps": list(key[2]), "attempts": []})
        d["attempts"].append({"t": chain[0]["event"]["elapsed"], "clock": chain[0]["event"]["clock"].split(".")[0], "possession_id": first["possession_id"],
                              "event_ids": [l["event"]["event_id"] for l in chain[:3]], "steps_matched": len(chain[:3]), "steps_total": 3,
                              "outcome": possession_outcome(poss, True)})
    n = 0
    for key in sorted(discovered, key=lambda k: (-len(discovered[k]["attempts"]), k)):
        d = discovered[key]
        if len(d["attempts"]) < MIN_DISCOVERED:
            continue
        n += 1
        patterns[f"{d['team']}_D{n}"] = {"id": f"{d['team']}_D{n}", "team": d["team"], "label": f"{d['trigger'].replace('_', ' ')}: " + ", ".join(d["steps"]),
                                        "trigger": d["trigger"], "source": "discovered", "steps": d["steps"], "attempts": d["attempts"], "shots_from": 0}
    out = []
    for p in patterns.values():
        p["shots_from"] = sum(1 for a in p["attempts"] if a["outcome"] == "shot")
        p["completed"] = sum(1 for a in p["attempts"] if a["outcome"] in ("completed", "shot"))
        out.append(p)
    out.sort(key=lambda p: (p["source"] != "playbook", p["team"], p["id"]))
    return {"match_id": match.match_id, "method": "playbook template matching plus repeated opening role chains, events and match.json only",
            "zone_tolerance_m": ZONE_M, "patterns": out}


def evaluate(match: Match, detected: dict, truth_path: Path | None = None) -> dict | None:
    """Precision and recall against routines_truth.jsonl, for the report only."""
    truth_path = truth_path or (match.dir / "routines_truth.jsonl")
    if not truth_path.exists():
        return None
    truth = read_jsonl(truth_path)
    truth_ids = {i for a in truth for i in a["event_ids"]}
    truth_poss = {(a["routine_id"], a["possession_id"]) for a in truth}
    pred_ids, pred_poss = set(), set()
    per: dict[str, dict] = {}
    for p in detected["patterns"]:
        if p["source"] != "playbook":
            continue
        ids = {i for a in p["attempts"] for i in a["event_ids"]}
        pp = {(p["id"], a["possession_id"]) for a in p["attempts"]}
        pred_ids |= ids
        pred_poss |= pp
        t_ids = {i for a in truth if a["routine_id"] == p["id"] for i in a["event_ids"]}
        t_pp = {(a["routine_id"], a["possession_id"]) for a in truth if a["routine_id"] == p["id"]}
        per[p["id"]] = {"precision": round(len(ids & t_ids) / len(ids), 3) if ids else None, "recall": round(len(ids & t_ids) / len(t_ids), 3) if t_ids else None,
                        "attempts_detected": len(pp), "attempts_true": len(t_pp), "attempts_matched": len(pp & t_pp), "against": truth_path.name}
    ev = {"against": truth_path.name, "level": "event ids of playbook attempts",
          "precision": round(len(pred_ids & truth_ids) / len(pred_ids), 3) if pred_ids else 0.0,
          "recall": round(len(pred_ids & truth_ids) / len(truth_ids), 3) if truth_ids else 0.0,
          "attempt_precision": round(len(pred_poss & truth_poss) / len(pred_poss), 3) if pred_poss else 0.0,
          "attempt_recall": round(len(pred_poss & truth_poss) / len(truth_poss), 3) if truth_poss else 0.0,
          "detected_events": len(pred_ids), "true_events": len(truth_ids), "per_pattern": per}
    return ev


def write_routines(match: Match, out: Path = VIEWER_DATA / "routines.json") -> dict:
    data = detect(match)
    ev = evaluate(match, data)
    if ev:
        data["evaluation"] = {k: v for k, v in ev.items() if k != "per_pattern"}
        for p in data["patterns"]:
            if p["id"] in ev["per_pattern"]:
                p["evaluation"] = ev["per_pattern"][p["id"]]
    write_json(out, data)
    return data
