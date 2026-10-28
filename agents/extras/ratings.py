"""Transparent, deterministic match ratings from 0 to 10, recomputed every 60 s of match time.

Formula (documented in RATINGS.md):
    rating(t) = clamp(6.0 + DAMP * scale(minutes) * sum(effect of every event by the player up to t), 3.0, 10.0)
    scale(minutes) = min(1, minutes_played / RAMP_MINUTES)
Every event that moves the rating is recorded with its event id, a label and its raw effect in
`reasons`, so the number can always be traced back to the event log.
"""
from __future__ import annotations

from pathlib import Path

from .common import Match, VIEWER_DATA, rel_point, zone_text, write_json

START = 6.0
LOW, HIGH = 3.0, 10.0
DAMP = 0.75              # global damping of the summed effects so a full match of volume stats stays under 10
RAMP_MINUTES = 20.0      # a player's deviation from 6.0 ramps in over the first 20 minutes on the pitch
ERROR_WINDOW_S = 10.0    # a loss in own third followed by an opponent shot within this window is an error
OWN_THIRD_RX = 35.0

# weights per event type and outcome, see RATINGS.md
W = {
    "goal": 1.0, "assist": 0.5, "key_pass": 0.1, "xg_per_shot": 0.6, "xa_per_key_pass": 0.6,
    "shot_on_target": 0.15, "shot_off_target": -0.05, "shot_blocked": 0.0, "big_chance_missed": -0.3,
    "pass_progressive": 0.03, "pass_into_final_third": 0.02, "pass_into_box": 0.04, "pass_incomplete": -0.05,
    "cross_complete": 0.05, "take_on_success": 0.1, "take_on_fail": -0.08, "progressive_carry": 0.04,
    "dispossessed": -0.1, "dribbled_past": -0.1,
    "tackle_won": 0.12, "tackle_lost": -0.08, "interception": 0.12, "clearance": 0.08, "block": 0.2,
    "recovery": 0.03, "aerial_won": 0.08,
    "foul": -0.08, "yellow": -0.3, "second_yellow": -0.5, "red": -1.0, "offside": -0.03,
    "error_leading_to_shot": -0.4, "error_leading_to_goal": -0.4,
    "gk_save": 0.3, "gk_save_xg": 1.0, "gk_claim": 0.05, "gk_goal_conceded": -0.2,
}

FORMULA = ("start 6.0; add documented weights per event (goals, assists, key passes, xG and xA, progressive "
           "passes, take-ons, tackles, interceptions, clearances, blocks, recoveries, saves and goals prevented) "
           "and subtract for losses, fouls, cards and errors leading to shots; multiply by 0.75 and by min(1, minutes/20); "
           "clamp to 3.0 to 10.0")


def _reason(e: dict, label: str, effect: float, player: str | None = None) -> dict:
    return {"event_id": e["event_id"], "label": label, "effect": round(effect, 3), **({"player": player} if player else {})}


def event_effects(match: Match) -> list[tuple[float, str, dict]]:
    """Every (elapsed, player_id, reason) triple in the match, in event order. Pure function of the events."""
    out: list[tuple[float, str, dict]] = []
    events = match.events
    gk_on: dict[str, str] = {}
    for lu in match.meta["lineups"]:
        for entry in lu["starting_xi"]:
            if entry["slot"] == "GK":
                gk_on[lu["team_id"]] = entry["player_id"]
    # last losing on-ball action per team (for errors leading to shots)
    last_loss: dict[str, tuple[float, str, dict]] = {}

    def add(e, pid, label, effect):
        if pid and abs(effect) > 1e-9:
            out.append((e["elapsed"], pid, _reason(e, label, effect)))

    for e in events:
        ty, oc, pid, team, x = e["type"], e.get("outcome"), e.get("player_id"), e["team_id"], e.get("extra") or {}
        zone = zone_text(e)
        if ty == "pass":
            if oc == "complete":
                if "cross" in e["qualifiers"]:
                    add(e, pid, "Cross completed", W["cross_complete"])
                if x.get("progressive"):
                    add(e, pid, f"Progressive pass {zone}".strip(), W["pass_progressive"])
                if x.get("into_final_third"):
                    add(e, pid, "Pass into the final third", W["pass_into_final_third"])
                if x.get("into_box"):
                    add(e, pid, "Pass into the box", W["pass_into_box"])
            else:
                add(e, pid, f"Pass lost {zone}".strip(), W["pass_incomplete"])
                if rel_point(e["start"], e["attack_dir"])[0] < OWN_THIRD_RX and oc in ("incomplete",):
                    last_loss[team] = (e["elapsed"], pid, e)
        elif ty == "carry":
            if oc == "dispossessed":
                add(e, pid, f"Dispossessed {zone}".strip(), W["dispossessed"])
                if rel_point(e["start"], e["attack_dir"])[0] < OWN_THIRD_RX:
                    last_loss[team] = (e["elapsed"], pid, e)
            elif e.get("end") and e.get("start"):
                sx = rel_point(e["start"], e["attack_dir"])[0]
                ex = rel_point(e["end"], e["attack_dir"])[0]
                if ex - sx >= 10:
                    add(e, pid, "Progressive carry", W["progressive_carry"])
        elif ty == "take_on":
            if oc == "success":
                add(e, pid, f"Beat a man {zone}".strip(), W["take_on_success"])
            else:
                add(e, pid, f"Take-on lost {zone}".strip(), W["take_on_fail"])
                if rel_point(e["start"], e["attack_dir"])[0] < OWN_THIRD_RX:
                    last_loss[team] = (e["elapsed"], pid, e)
        elif ty == "dribbled_past":
            add(e, pid, "Beaten by a dribble", W["dribbled_past"])
        elif ty == "shot":
            xg = float(x.get("xg", 0.0))
            if oc == "goal":
                add(e, pid, "Goal", W["goal"])
            elif oc == "saved":
                add(e, pid, "Shot on target", W["shot_on_target"])
            elif oc == "off_target":
                add(e, pid, "Shot off target", W["shot_off_target"])
            add(e, pid, f"Shot worth {xg:.2f} xG", W["xg_per_shot"] * xg)
            if xg >= 0.35 and oc != "goal":
                add(e, pid, "Big chance missed", W["big_chance_missed"])
            aid = x.get("assist_event_id")
            if aid and aid in match.by_id:
                passer = match.by_id[aid].get("player_id")
                if oc == "goal":
                    add(e, passer, "Assist", W["assist"])
                add(e, passer, "Key pass", W["key_pass"])
                add(e, passer, f"Key pass worth {xg:.2f} xA", W["xa_per_key_pass"] * xg)
            # error leading to shot: the opponent lost it in their own third within the window
            opp = match.other(team)
            loss = last_loss.get(opp)
            if loss and e["elapsed"] - loss[0] <= ERROR_WINDOW_S and e["possession_team_id"] == team:
                label = "Error leading to a goal" if oc == "goal" else "Error leading to a shot"
                add(e, loss[1], label, W["error_leading_to_goal" if oc == "goal" else "error_leading_to_shot"])
                last_loss.pop(opp, None)
            # keeper facing the shot
            gk = gk_on.get(opp)
            if gk:
                if oc == "saved":
                    add(e, gk, f"Save from a {xg:.2f} xG shot", W["gk_save"] + W["gk_save_xg"] * xg)
                elif oc == "goal":
                    add(e, gk, "Goal conceded", W["gk_goal_conceded"])
        elif ty == "tackle":
            add(e, pid, f"Tackle won {zone}".strip() if oc == "won" else f"Tackle lost {zone}".strip(),
                W["tackle_won"] if oc == "won" else W["tackle_lost"])
        elif ty == "interception":
            add(e, pid, f"Interception {zone}".strip(), W["interception"])
        elif ty == "clearance":
            add(e, pid, f"Clearance {zone}".strip(), W["clearance"])
        elif ty == "block":
            add(e, pid, "Shot blocked", W["block"])
        elif ty == "ball_recovery":
            add(e, pid, f"Loose ball won {zone}".strip(), W["recovery"])
        elif ty == "aerial_duel":
            add(e, pid, "Aerial duel won", W["aerial_won"])
        elif ty == "goalkeeper" and oc == "claim":
            add(e, pid, "Cross claimed", W["gk_claim"])
        elif ty == "foul":
            add(e, pid, f"Foul {zone}".strip(), W["foul"])
        elif ty == "card":
            add(e, pid, {"yellow": "Yellow card", "second_yellow": "Second yellow", "red": "Red card"}[oc], W[oc])
        elif ty == "offside":
            add(e, pid, "Offside", W["offside"])
        elif ty == "substitution":
            if x["player_out"] in gk_on.values():
                gk_on[team] = x["player_in"]
    return out


def minutes_on(match: Match) -> dict[str, list[tuple[float, float | None]]]:
    """Intervals [on, off) in elapsed seconds per player."""
    spans: dict[str, list] = {}
    for lu in match.meta["lineups"]:
        for entry in lu["starting_xi"]:
            spans[entry["player_id"]] = [[0.0, None]]
    for e in match.events:
        if e["type"] == "substitution":
            spans.setdefault(e["extra"]["player_out"], [[0.0, None]])[-1][1] = e["elapsed"]
            spans.setdefault(e["extra"]["player_in"], []).append([e["elapsed"], None])
        elif e["type"] == "card" and e["outcome"] in ("red", "second_yellow") and e.get("player_id"):
            spans.setdefault(e["player_id"], [[0.0, None]])[-1][1] = e["elapsed"]
    return spans


def _played(spans: list, t: float) -> float:
    total = 0.0
    for on, off in spans:
        if t <= on:
            continue
        total += min(t, off if off is not None else t) - on
    return total / 60.0


def compute_ratings(match: Match, every_s: float = 60.0) -> dict:
    effects = event_effects(match)
    spans = minutes_on(match)
    ticks = [float(k * every_s) for k in range(1, int(match.duration // every_s) + 1)]
    if not ticks or ticks[-1] < match.duration:
        ticks.append(match.duration)
    players: dict[str, list] = {}
    raw: dict[str, float] = {}
    prev_rating: dict[str, float] = {}
    i = 0
    for t in ticks:
        bucket: dict[str, list] = {}
        while i < len(effects) and effects[i][0] <= t:
            _, pid, reason = effects[i]
            raw[pid] = raw.get(pid, 0.0) + reason["effect"]
            bucket.setdefault(pid, []).append(reason)
            i += 1
        for pid, sp in spans.items():
            mins = _played(sp, t)
            if mins <= 0:
                continue
            scale = min(1.0, mins / RAMP_MINUTES)
            rating = max(LOW, min(HIGH, START + DAMP * scale * raw.get(pid, 0.0)))
            rating = round(rating, 2)
            delta = round(rating - prev_rating.get(pid, START), 2)
            prev_rating[pid] = rating
            players.setdefault(pid, []).append({"t": t, "rating": rating, "delta": delta, "minutes": round(mins, 1),
                                                "reasons": bucket.get(pid, [])})
    return {"match_id": match.match_id, "every_s": every_s, "formula": FORMULA, "weights": W,
            "start": START, "clamp": [LOW, HIGH], "ramp_minutes": RAMP_MINUTES, "damp": DAMP,
            "players": {pid: players[pid] for pid in sorted(players)}}


def rating_at(ratings: dict, pid: str, t: float) -> dict | None:
    """The latest rating entry for a player at or before t."""
    last = None
    for entry in ratings["players"].get(pid, []):
        if entry["t"] <= t:
            last = entry
        else:
            break
    return last


def write_ratings(match: Match, out: Path = VIEWER_DATA / "ratings.json", every_s: float = 60.0) -> dict:
    data = compute_ratings(match, every_s)
    write_json(out, data)
    return data
