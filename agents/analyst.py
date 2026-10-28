"""Analyst agent: deterministic detectors over the events up to a time, producing fact packs.

A fact pack carries every number the narrator may use, every evidence event id with a short
description, and the names it may mention. Nothing here calls a model.

Detectors (the first three are ports of viewer/src/points.ts):
- anchor: the defensive anchor, a player with at least 6 defensive actions and 3 more than any teammate
- duel: take-on record, at least 4 attempts with 60% or more won
- finishing: goals against xG differ by 0.8 or more over at least 3 shots
- momentum: a team's last_5_min.momentum stays above 60 for two consecutive snapshots
- score_state: who leads, any comeback, with the goals as evidence
"""
from __future__ import annotations

from .data import Match, short_clock

DEF_FOR_TYPES = ("interception", "clearance", "block", "ball_recovery")
MOMENTUM_THRESHOLD = 60.0


def is_def_for(e: dict) -> bool:
    return (e["type"] == "tackle" and e.get("outcome") == "won") or e["type"] in DEF_FOR_TYPES


def is_def_against(e: dict) -> bool:
    return (e["type"] == "tackle" and e.get("outcome") == "lost") or e["type"] in ("dribbled_past", "foul")


LABELS = {
    "tackle": lambda e: "Tackle won" if e.get("outcome") == "won" else "Tackle lost",
    "interception": lambda e: "Interception",
    "clearance": lambda e: "Clearance",
    "block": lambda e: "Shot blocked",
    "ball_recovery": lambda e: "Loose ball won",
    "dribbled_past": lambda e: "Beaten by a dribble",
    "foul": lambda e: "Foul conceded",
    "take_on": lambda e: "Beat the defender" if e.get("outcome") == "success" else "Take-on lost",
    "shot": lambda e: {"goal": "Goal", "saved": "Saved", "off_target": "Off target", "blocked": "Blocked"}.get(e.get("outcome") or "", "Shot"),
    "goal": lambda e: "Goal",
    "pass": lambda e: "Pass into the final third" if (e.get("extra") or {}).get("into_final_third") else "Pass",
    "card": lambda e: {"yellow": "Yellow card", "second_yellow": "Second yellow card", "red": "Red card"}.get(e.get("outcome") or "", "Card"),
}


def card_label(e: dict) -> str:
    return LABELS.get(e["type"], lambda x: x["type"])(e)


def zone_text(e: dict) -> str:
    s = e.get("start")
    if not s:
        return ""
    rx = s["x"] if e["attack_dir"] == 1 else 105 - s["x"]
    ry = s["y"] if e["attack_dir"] == 1 else 68 - s["y"]
    in_own_box = rx < 16.5 and 13.84 < ry < 54.16
    in_opp_box = rx > 88.5 and 13.84 < ry < 54.16
    if in_own_box:
        return "in their own box"
    if in_opp_box:
        return "in the box"
    if rx < 35:
        return "in their own third"
    if rx < 70:
        return "in midfield"
    return "in the final third"


def describe(m: Match, e: dict) -> dict:
    d = {
        "event_id": e["event_id"],
        "clock": short_clock(e["clock"]),
        "minute": e["minute"],
        "player": m.player_name(e.get("player_id")),
        "label": card_label(e),
        "zone": zone_text(e),
    }
    x = e.get("extra") or {}
    if e["type"] == "shot":
        d["xg"] = round(float(x.get("xg", 0.0)), 2)
    return d


def _pack(m: Match, *, point_id: str, kind: str, team: str, subject: str | None, t: float, clock: str,
          numbers: dict, names: list[str], for_ev: list[dict], against_ev: list[dict],
          strength: float, summary: str) -> dict:
    name_set: list[str] = []
    for n in names + [m.team_name(tid) for tid in m.teams]:
        if n and n not in name_set:
            name_set.append(n)
    ef = [describe(m, e) for e in for_ev]
    ea = [describe(m, e) for e in against_ev]
    for d in ef + ea:
        if d["player"] not in name_set:
            name_set.append(d["player"])
    return {
        "point_id": point_id, "kind": kind, "team": team, "subject": subject,
        "t": t, "clock": clock, "team_name": m.team_name(team),
        "subject_name": m.player_name(subject) if subject else None,
        "numbers": numbers, "names": name_set,
        "evidence_for": ef, "evidence_against": ea,
        "strength": round(strength, 3), "summary": summary,
    }


def detect_anchor(m: Match, upto: list[dict], t: float, clock: str) -> list[dict]:
    packs = []
    for team in m.teams:
        counts: dict[str, int] = {}
        for e in upto:
            if e["team_id"] == team and e.get("player_id") and is_def_for(e):
                counts[e["player_id"]] = counts.get(e["player_id"], 0) + 1
        ranked = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
        if not ranked:
            continue
        pid, n = ranked[0]
        nxt = ranked[1][1] if len(ranked) > 1 else 0
        if n < 6 or n - nxt < 3:
            continue
        for_ev = [e for e in upto if e.get("player_id") == pid and is_def_for(e)]
        against_ev = [e for e in upto if e.get("player_id") == pid and is_def_against(e)]
        packs.append(_pack(
            m, point_id=f"anchor-{pid}", kind="anchor", team=team, subject=pid, t=t, clock=clock,
            numbers={"defensive_actions": n, "next_best_teammate": nxt, "margin_over_teammates": n - nxt,
                     "actions_lost": len(against_ev), "minute": _minute(clock)},
            names=[m.player_name(pid), m.surname(pid)], for_ev=for_ev, against_ev=against_ev,
            strength=n - nxt + n * 0.2,
            summary=f"{m.player_name(pid)} has {n} defensive actions, {n - nxt} more than any teammate",
        ))
    return packs


def detect_duel(m: Match, upto: list[dict], t: float, clock: str) -> list[dict]:
    tk: dict[str, list[dict]] = {}
    for e in upto:
        if e["type"] == "take_on" and e.get("player_id"):
            tk.setdefault(e["player_id"], []).append(e)
    duelists = []
    for pid, evs in tk.items():
        won = sum(1 for e in evs if e.get("outcome") == "success")
        if len(evs) >= 4 and won / len(evs) >= 0.6:
            duelists.append((pid, evs, won))
    duelists.sort(key=lambda d: (-d[2], d[0]))
    packs = []
    for pid, evs, won in duelists[:2]:
        victims: dict[str, int] = {}
        for e in evs:
            opp = (e.get("extra") or {}).get("opponent_id")
            if e.get("outcome") == "success" and opp:
                victims[opp] = victims.get(opp, 0) + 1
        top = sorted(victims.items(), key=lambda kv: (-kv[1], kv[0]))[:1]
        numbers = {"take_ons": len(evs), "take_ons_won": won, "take_ons_lost": len(evs) - won,
                   "win_rate_pct": round(100 * won / len(evs)), "minute": _minute(clock)}
        names = [m.player_name(pid), m.surname(pid)]
        summary = f"{m.player_name(pid)} has won {won} of {len(evs)} take-ons"
        if top and top[0][1] >= 2:
            numbers["won_against_top_victim"] = top[0][1]
            names += [m.player_name(top[0][0]), m.surname(top[0][0])]
            summary += f", {top[0][1]} of them against {m.player_name(top[0][0])}"
        packs.append(_pack(
            m, point_id=f"duel-{pid}", kind="duel", team=m.team_of(pid), subject=pid, t=t, clock=clock,
            numbers=numbers, names=names,
            for_ev=[e for e in evs if e.get("outcome") == "success"],
            against_ev=[e for e in evs if e.get("outcome") != "success"],
            strength=won * 0.8, summary=summary,
        ))
    return packs


def detect_finishing(m: Match, upto: list[dict], t: float, clock: str) -> list[dict]:
    packs = []
    for team in m.teams:
        shots = [e for e in upto if e["type"] == "shot" and e["team_id"] == team]
        if len(shots) < 3:
            continue
        xg = sum(float((e.get("extra") or {}).get("xg", 0.0)) for e in shots)
        goals = [e for e in shots if e.get("outcome") == "goal"]
        diff = len(goals) - xg
        if abs(diff) < 0.8:
            continue
        hot = diff > 0
        misses = [e for e in shots if e.get("outcome") != "goal" and float((e.get("extra") or {}).get("xg", 0.0)) >= 0.15]
        packs.append(_pack(
            m, point_id=f"finishing-{team}", kind="finishing", team=team, subject=None, t=t, clock=clock,
            numbers={"goals": len(goals), "xg": round(xg, 2), "xg_1dp": round(xg, 1), "shots": len(shots),
                     "goals_minus_xg": round(diff, 2), "good_chances_missed": len(misses), "minute": _minute(clock)},
            names=[], for_ev=goals if hot else misses, against_ev=misses if hot else goals,
            strength=abs(diff) * 3,
            summary=(f"{m.team_name(team)} have {len(goals)} goals from {xg:.2f} xG across {len(shots)} shots"
                     + (" (finishing above expectation)" if hot else " (finishing below expectation)")),
        ))
    return packs


def detect_momentum(m: Match, upto: list[dict], t: float, clock: str, snap: dict,
                    momentum_series: dict[str, list[tuple[float, float]]]) -> list[dict]:
    packs = []
    for team in m.teams:
        series = [(at, v) for at, v in momentum_series.get(team, []) if at <= t]
        if len(series) < 2:
            continue
        (t_prev, prev), (t_now, now) = series[-2], series[-1]
        if prev <= MOMENTUM_THRESHOLD or now <= MOMENTUM_THRESHOLD:
            continue
        lo = t - 300.0
        window = [e for e in upto if lo < e["elapsed"] <= t and e["team_id"] == team]
        entries = [e for e in window if e["type"] == "pass" and (e.get("extra") or {}).get("into_final_third")
                   and e.get("outcome") == "complete"]
        shots = [e for e in window if e["type"] == "shot"]
        last5 = snap["teams"][team]["last_5_min"]
        opp = m.away if team == m.home else m.home
        packs.append(_pack(
            m, point_id=f"momentum-{team}", kind="momentum", team=team, subject=None, t=t, clock=clock,
            numbers={"momentum_now": round(now), "momentum_previous": round(prev), "threshold": 60, "window_minutes": 5,
                     "final_third_entries_5min": int(last5.get("final_third_entries", len(entries))),
                     "shots_5min": len(shots), "xg_5min": round(float(last5.get("xg", 0.0)), 2),
                     "opponent_momentum": round(float(snap["teams"][opp]["last_5_min"].get("momentum", 0.0))),
                     "minute": _minute(clock)},
            names=[], for_ev=entries + shots, against_ev=[],
            strength=(now - MOMENTUM_THRESHOLD) * 0.5 + len(shots),
            summary=f"{m.team_name(team)} momentum {now:.0f} after {prev:.0f}, {len(entries)} final-third entries and {len(shots)} shots in the last 5 minutes",
        ))
    return packs


def detect_score_state(m: Match, upto: list[dict], t: float, clock: str, snap: dict) -> list[dict]:
    goals = [e for e in upto if e["type"] == "goal"]
    score = dict(snap["score"])
    home, away = m.home, m.away
    behind_ever = {home: False, away: False}
    max_deficit = {home: 0, away: 0}
    for g in goals:
        s = g["score"]
        for tid, other in ((home, away), (away, home)):
            d = s[other] - s[tid]
            if d > 0:
                behind_ever[tid] = True
                max_deficit[tid] = max(max_deficit[tid], d)
    if score[home] > score[away]:
        leader, trailer = home, away
    elif score[away] > score[home]:
        leader, trailer = away, home
    else:
        leader, trailer = None, None
    comeback = None
    for tid in (home, away):
        if behind_ever[tid] and score[tid] >= score[home if tid == away else away]:
            comeback = tid
    team = leader or home
    numbers = {"home_goals": score[home], "away_goals": score[away], "minute": _minute(clock),
               "goals_so_far": len(goals), "margin": abs(score[home] - score[away])}
    names = []
    if comeback:
        numbers["comeback_from_goals_down"] = max_deficit[comeback]
        names.append(m.team_name(comeback))
    for_ev = [g for g in goals if leader is None or g["team_id"] == leader]
    against_ev = [g for g in goals if leader is not None and g["team_id"] != leader]
    for g in goals:
        names += [m.player_name(g.get("player_id")), m.surname(g.get("player_id"))]
    if leader:
        summary = f"{m.team_name(leader)} lead {score[home]}-{score[away]}"
    else:
        summary = f"Level at {score[home]}-{score[away]}"
    if comeback:
        summary += f", {m.team_name(comeback)} came back from {max_deficit[comeback]} down"
    pack = _pack(m, point_id="score-state", kind="score_state", team=team, subject=None, t=t, clock=clock,
                 numbers=numbers, names=names, for_ev=for_ev, against_ev=against_ev,
                 strength=1.0 + len(goals) + (3 if comeback else 0), summary=summary)
    pack["leader"] = leader
    pack["leader_name"] = m.team_name(leader) if leader else None
    pack["comeback"] = comeback
    pack["comeback_name"] = m.team_name(comeback) if comeback else None
    pack["score_line"] = f"{score[home]}-{score[away]}"
    pack["home_name"], pack["away_name"] = m.team_name(home), m.team_name(away)
    return [pack]


def _minute(clock: str) -> int:
    head = clock.split(":")[0]
    if "+" in head:
        a, b = head.split("+")
        return int(a) + int(b)
    return int(head)


def analyse(m: Match, upto: list[dict], t: float, clock: str, snap: dict,
            momentum_series: dict[str, list[tuple[float, float]]]) -> list[dict]:
    packs = (detect_anchor(m, upto, t, clock) + detect_duel(m, upto, t, clock)
             + detect_finishing(m, upto, t, clock) + detect_momentum(m, upto, t, clock, snap, momentum_series)
             + detect_score_state(m, upto, t, clock, snap))
    return sorted(packs, key=lambda p: (-p["strength"], p["point_id"]))
