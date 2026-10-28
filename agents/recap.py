"""Recap agent: at half time and full time, a three to five sentence recap per lens built from
the score state, the xG timeline and the strongest points. Numbers come from the fact pack only."""
from __future__ import annotations

from .data import Match


def recap_pack(m: Match, when: str, t: float, clock: str, snap: dict, score_pack: dict,
               strongest: list[dict], goals: list[dict]) -> dict:
    home, away = m.home, m.away
    hx = round(float(snap["teams"][home]["xg"]), 2)
    ax = round(float(snap["teams"][away]["xg"]), 2)
    hs, as_ = int(snap["teams"][home]["shots"]), int(snap["teams"][away]["shots"])
    hb, ab = int(snap["teams"][home]["big_chances"]), int(snap["teams"][away]["big_chances"])
    score = snap["score"]
    xg_timeline = [{"clock": g["clock"], "minute": g["minute"], "team": m.team_name(g["player"] and m.team_of(_pid(m, g["player"])) or home),
                    "scorer": g["player"]} for g in goals]
    numbers = {"home_goals": score[home], "away_goals": score[away], "home_xg": hx, "away_xg": ax,
               "home_shots": hs, "away_shots": as_, "home_big_chances": hb, "away_big_chances": ab,
               "minute": score_pack["numbers"]["minute"], "goals_so_far": len(goals)}
    if score_pack.get("comeback"):
        numbers["comeback_from_goals_down"] = score_pack["numbers"]["comeback_from_goals_down"]
    names = list(score_pack["names"])
    for p in strongest:
        if p.get("subject_name"):
            names += [p["subject_name"], p["subject_name"].split(" ")[-1]]
        for key in ("numbers",):
            pass
    pack = {
        "point_id": f"recap-{when}", "kind": "recap", "team": score_pack["team"], "subject": None,
        "t": t, "clock": clock, "team_name": score_pack["team_name"], "subject_name": None,
        "when": "half time" if when == "ht" else "full time",
        "home_name": m.team_name(home), "away_name": m.team_name(away),
        "score_line": f"{score[home]}-{score[away]}", "leader": score_pack.get("leader"),
        "leader_name": score_pack.get("leader_name"), "comeback": score_pack.get("comeback"),
        "comeback_name": score_pack.get("comeback_name"),
        "numbers": numbers, "names": names,
        "evidence_for": list(score_pack["evidence_for"]), "evidence_against": list(score_pack["evidence_against"]),
        "xg_timeline": xg_timeline,
        "strongest_points": [{"point_id": p["point_id"], "summary": p["summary"], "numbers": p["numbers"]} for p in strongest],
        "strength": 100.0, "summary": f"{when} recap: {score_pack['summary']}",
    }
    pack["extra_numbers"] = [p["numbers"] for p in strongest]
    pack["template"] = _template(m, pack, strongest)
    return pack


def _pid(m: Match, name: str) -> str:
    for p in m.meta.get("players", []):
        if p["name"] == name:
            return p["id"]
    return m.home + "_00"


def _template(m: Match, pack: dict, strongest: list[dict]) -> dict:
    n = pack["numbers"]
    hn, an, sl, when = pack["home_name"], pack["away_name"], pack["score_line"], pack["when"]
    s1 = f"{when.capitalize()}: {hn} {sl} {an}."
    if pack["leader"]:
        s1 += f" {pack['leader_name']} {'win' if when == 'full time' else 'lead'}."
    else:
        s1 += " It ends level." if when == "full time" else " It is level."
    if pack.get("comeback"):
        s1 += f" {pack['comeback_name']} came back from {n['comeback_from_goals_down']} down."
    goals = pack["evidence_for"] + pack["evidence_against"]
    goals = sorted(goals, key=lambda g: g["minute"])
    if goals:
        s2 = "The goals: " + ", ".join(f"{g['player']} on {g['minute']} minutes" for g in goals) + "."
        # one goal reads better without the plural
        s2 = s2.replace(" on 1 minutes", " on 1 minute")
    else:
        s2 = "There have been no goals yet."
    casual_points = []
    tactical_points = []
    for p in strongest[:2]:
        pn = p["numbers"]
        if p["kind"] == "anchor":
            casual_points.append(f"{p['subject_name'].split(' ')[-1]} has been the rock at the back for {p['team_name']}.")
            tactical_points.append(f"{p['subject_name']} leads the defensive actions with {pn['defensive_actions']}, {pn['margin_over_teammates']} clear of any teammate.")
        elif p["kind"] == "duel":
            casual_points.append(f"{p['subject_name'].split(' ')[-1]} keeps beating his man.")
            tactical_points.append(f"{p['subject_name']} has won {pn['take_ons_won']} of {pn['take_ons']} take-ons.")
        elif p["kind"] == "finishing":
            hot = pn["goals_minus_xg"] > 0
            casual_points.append(f"{p['team_name']} {'have been clinical' if hot else 'have wasted good chances'}.")
            tactical_points.append(f"{p['team_name']} have {pn['goals']} goals from {pn['xg']:.2f} expected goals across {pn['shots']} shots.")
        elif p["kind"] == "momentum":
            casual_points.append(f"{p['team_name']} have had the upper hand recently.")
            tactical_points.append(f"{p['team_name']} momentum sits at {pn['momentum_now']} with {pn['final_third_entries_5min']} final-third entries in the last five minutes.")
    casual = " ".join([s1, s2] + casual_points[:2])
    tactical = " ".join([s1, f"Expected goals: {hn} {n['home_xg']:.2f} from {n['home_shots']} shots, {an} {n['away_xg']:.2f} from {n['away_shots']} shots.",
                         f"Big chances: {hn} {n['home_big_chances']}, {an} {n['away_big_chances']}."] + tactical_points[:2])
    comm = s1 + (" " + casual_points[0] if casual_points else "")
    return {"casual": casual, "tactical": tactical, "commentator": comm}
