"""Incremental match statistics: feed events and tracking frames in time order, snapshot any time.

    engine = StatsEngine(meta)          # meta = match.json dict
    engine.ingest_event(event)
    engine.ingest_frame(frame)
    snap = engine.snapshot()            # JSON-serialisable dict

This module only depends on the standard library and the data schema (SCHEMA.md),
so the same code can run inside the live pipeline. Every metric is defined in
terms of the schema fields; definitions are listed in SCHEMA.md and repeated in
the docstrings below. All iteration is over lists or sorted keys so output is
deterministic.

Conventions:
- Team-relative x (own goal at 0) is `x if attack_dir == 1 else 105 - x`.
- Final third: team-relative x >= 70. Opponent half: x > 52.5. Box: x > 88.5 and 13.84 < y < 54.16.
- Touches: pass, carry, take_on, shot, clearance, ball_recovery, interception, goalkeeper events.
- Defensive actions for PPDA: tackle, interception, foul, ball_recovery, block, clearance.
- Possession share by time: the gap between consecutive events (under 15 s) is
  credited to the team in possession at the earlier event.
- Sprint: speed rising to 25.2 km/h or more. High intensity: 19.8 to 25.2 km/h.
- Big chance: a shot with xG of 0.35 or more.
- Rolling window: the last 300 s of match time before the snapshot.
"""
from __future__ import annotations

import math
from collections import deque

L, W = 105.0, 68.0
SPRINT_KMH = 25.2
HI_KMH = 19.8
BIG_CHANCE_XG = 0.35
WINDOW_S = 300.0
GAP_S = 15.0           # longest gap between events still credited as possession time
COUNTER_PRESS_S = 5.0
HIGH_TURNOVER_RX = 65.0  # within 40 m of the opponent goal
TOUCH_TYPES = ("pass", "carry", "take_on", "shot", "clearance", "ball_recovery", "interception", "goalkeeper")
PPDA_DEF_TYPES = ("tackle", "interception", "foul", "ball_recovery", "block", "clearance")
REGAIN_TYPES = ("tackle", "interception", "ball_recovery")
LOST_IN_PLAY = ("tackle", "interception", "recovery")

TEAM_COUNTERS = [
    "goals", "shots", "shots_on_target", "xg", "big_chances", "passes", "passes_completed",
    "progressive_passes", "final_third_entries", "box_entries", "crosses", "long_balls",
    "possessions", "possession_time_s", "possession_completed", "possession_seconds_total",
    "possession_passes_total", "touches", "final_third_touches", "opp_half_touches",
    "tackles", "interceptions", "recoveries", "clearances", "blocks", "pressures",
    "ppda_passes_allowed", "ppda_defensive_actions", "high_turnovers", "counter_press_regains",
    "corners", "free_kicks", "throw_ins", "offsides", "fouls", "yellows", "reds",
    "distance_m", "sprints", "top_speed_kmh",
]
PLAYER_COUNTERS = [
    "touches", "passes", "passes_completed", "progressive_passes", "key_passes", "assists", "xa",
    "crosses", "shots", "shots_on_target", "goals", "xg", "big_chances", "big_chances_missed",
    "max_shot_speed_kmh", "carries", "progressive_carries", "take_ons", "take_ons_won",
    "dispossessed", "tackles", "tackles_won", "interceptions", "recoveries", "clearances", "blocks",
    "aerial_duels_won", "dribbled_past", "fouls_committed", "fouls_won", "yellow_cards", "red_cards",
    "pressures", "distance_m", "high_intensity_distance_m", "top_speed_kmh", "current_speed_kmh",
    "sprints",
]
GK_COUNTERS = ["saves", "xg_faced", "goals_conceded"]
# team metrics that must equal the sum over the team's players
SUMMABLE = ["goals", "shots", "shots_on_target", "xg", "big_chances", "passes", "passes_completed",
            "progressive_passes", "crosses", "tackles", "interceptions", "recoveries", "clearances",
            "blocks", "pressures", "fouls", "yellows", "reds", "distance_m", "sprints"]


def fmt_clock(period: int, period_seconds: float) -> str:
    base = 0 if period == 1 else 45 * 60
    regular = 45 * 60
    if period_seconds <= regular:
        total = base + period_seconds
        return f"{int(total // 60):02d}:{total % 60:04.1f}"
    extra = period_seconds - regular
    return f"{(base + regular) // 60}+{int(extra // 60)}:{extra % 60:04.1f}"


def rel_x(x: float, attack_dir: int) -> float:
    return x if attack_dir == 1 else L - x


def rel_point(pt: dict, attack_dir: int) -> tuple[float, float]:
    if attack_dir == 1:
        return pt["x"], pt["y"]
    return L - pt["x"], W - pt["y"]


def in_box(rx: float, ry: float) -> bool:
    return rx > 88.5 and 13.84 < ry < 54.16


def _share(a: float, b: float) -> float:
    return a / (a + b) if (a + b) > 0 else 0.0


class StatsEngine:
    """Cumulative and rolling match statistics, updated one message at a time."""

    def __init__(self, meta: dict):
        self.meta = meta
        self.match_id = meta["match_id"]
        self.home = meta["home_team_id"]
        self.away = meta["away_team_id"]
        self.teams = [self.home, self.away]
        self.team_of: dict[str, str] = {}
        self.info: dict[str, dict] = {}
        for lu in meta["lineups"]:
            for entry in lu["starting_xi"]:
                self.team_of[entry["player_id"]] = lu["team_id"]
            for pid in lu["bench"]:
                self.team_of[pid] = lu["team_id"]
        for p in meta.get("players", []):
            self.info[p["id"]] = {"name": p["name"], "position": p["position"], "group": p["group"]}
            self.team_of.setdefault(p["id"], p["id"].rsplit("_", 1)[0])
        self.gk_ids = {p["id"] for p in meta.get("players", []) if p.get("group") == "GK"}
        self.score = {t: 0 for t in self.teams}
        self.t: dict[str, dict[str, float]] = {t: {k: 0 for k in TEAM_COUNTERS} for t in self.teams}
        self.p: dict[str, dict[str, float]] = {}
        self.on_pitch: dict[str, bool] = {}
        self.stints: dict[str, list[list[float | None]]] = {}  # pid -> [[on, off_or_None], ...]
        for lu in meta["lineups"]:
            for entry in lu["starting_xi"]:
                self._player(entry["player_id"], on_at=0.0)
        self.network: dict[str, dict[tuple[str, str], int]] = {t: {} for t in self.teams}
        self.elapsed = 0.0
        self.period = 1
        self.period_start = {1: 0.0}
        self.last_event: dict | None = None
        self.lost_at: dict[str, float | None] = {t: None for t in self.teams}
        self.poss_seen: set[int] = set()
        self.passes_by_id: dict[str, dict] = {}
        self.window: deque[dict] = deque()
        self.last_frame_pos: dict[str, tuple[float, float, float]] = {}
        self.in_sprint: dict[str, bool] = {}

    # ------------------------------------------------------------- players
    def _player(self, pid: str, on_at: float | None = None) -> dict[str, float]:
        if pid not in self.p:
            d = {k: 0 for k in PLAYER_COUNTERS}
            if pid in self.gk_ids:
                d.update({k: 0 for k in GK_COUNTERS})
            self.p[pid] = d
            self.on_pitch[pid] = False
            self.stints[pid] = []
        if on_at is not None and not self.on_pitch[pid]:
            self.on_pitch[pid] = True
            self.stints[pid].append([on_at, None])
        return self.p[pid]

    def _off(self, pid: str, at: float) -> None:
        if self.on_pitch.get(pid):
            self.on_pitch[pid] = False
            self.stints[pid][-1][1] = at

    def _minutes(self, pid: str, at: float) -> float:
        total = 0.0
        for on, off in self.stints.get(pid, []):
            end = at if off is None else min(off, at)
            total += max(0.0, end - on)
        return total / 60.0

    def _team(self, pid: str | None, fallback: str) -> str:
        return self.team_of.get(pid, fallback) if pid else fallback

    def other(self, team: str) -> str:
        return self.away if team == self.home else self.home

    # -------------------------------------------------------------- ingest
    def _clock_update(self, elapsed: float, period: int) -> None:
        if period != self.period and period not in self.period_start:
            self.period_start[period] = elapsed
        self.period = max(self.period, period)
        self.elapsed = max(self.elapsed, elapsed)

    def ingest_frame(self, frame: dict) -> None:
        self._clock_update(frame["elapsed"], frame["period"])
        t = frame["elapsed"]
        for pid, x, y, kmh in frame["players"]:
            team = self._team(pid, pid.rsplit("_", 1)[0])
            pd = self._player(pid, on_at=t if pid not in self.p else None)
            td = self.t[team]
            last = self.last_frame_pos.get(pid)
            if last is not None and t - last[2] <= 1.5:
                step = math.hypot(x - last[0], y - last[1])
                pd["distance_m"] += step
                td["distance_m"] += step
                if HI_KMH <= kmh < SPRINT_KMH:
                    pd["high_intensity_distance_m"] += step
            self.last_frame_pos[pid] = (x, y, t)
            pd["current_speed_kmh"] = kmh
            if kmh > pd["top_speed_kmh"]:
                pd["top_speed_kmh"] = kmh
            if kmh > td["top_speed_kmh"]:
                td["top_speed_kmh"] = kmh
            was = self.in_sprint.get(pid, False)
            if kmh >= SPRINT_KMH and not was:
                pd["sprints"] += 1
                td["sprints"] += 1
            self.in_sprint[pid] = kmh >= SPRINT_KMH

    def ingest_event(self, e: dict) -> None:
        self._clock_update(e["elapsed"], e["period"])
        team = e["team_id"]
        opp = self.other(team)
        pid = e["player_id"]
        ty = e["type"]
        x = e.get("extra") or {}
        td = self.t[team]
        pd = self._player(pid) if pid else None
        self.window.append(e)
        if "score" in e:
            self.score = dict(e["score"])
        # possession time and possession ids
        prev = self.last_event
        if prev is not None:
            gap = e["elapsed"] - prev["elapsed"]
            if 0 <= gap < GAP_S:
                self.t[prev["possession_team_id"]]["possession_time_s"] += gap
        if e["possession_id"] not in self.poss_seen:
            self.poss_seen.add(e["possession_id"])
            self.t[e["possession_team_id"]]["possessions"] += 1
            if prev is not None and prev["possession_team_id"] != e["possession_team_id"]:
                self.lost_at[prev["possession_team_id"]] = e["elapsed"]
        pp = x.get("prev_possession")
        if pp:
            pt = self.t.get(pp["team_id"])
            if pt is not None:
                pt["possession_completed"] += 1
                pt["possession_seconds_total"] += pp["duration_s"]
                pt["possession_passes_total"] += pp["passes"]
        self.last_event = e
        # touches and territory
        if ty in TOUCH_TYPES and pid:
            rx, ry = rel_point(e["start"], e["attack_dir"])
            td["touches"] += 1
            pd["touches"] += 1
            if rx >= 70:
                td["final_third_touches"] += 1
            if rx > 52.5:
                td["opp_half_touches"] += 1
        # PPDA: this team's passes in its own 60% are "allowed" by the opponent;
        # defensive actions in the opponent's own 60% count for the defending team
        if ty == "pass":
            if rel_x(e["start"]["x"], e["attack_dir"]) < 63.0:
                td["ppda_passes_allowed"] += 1
        elif ty in PPDA_DEF_TYPES and pid:
            if rel_x(e["start"]["x"], e["attack_dir"]) > 42.0:
                td["ppda_defensive_actions"] += 1
        handler = getattr(self, f"_on_{ty}", None)
        if handler:
            handler(e, team, opp, pid, pd, td, x)

    # ------------------------------------------------------- event handlers
    def _on_pass(self, e, team, opp, pid, pd, td, x) -> None:
        td["passes"] += 1
        pd["passes"] += 1
        self.passes_by_id[e["event_id"]] = e
        complete = e["outcome"] == "complete"
        if complete:
            td["passes_completed"] += 1
            pd["passes_completed"] += 1
            recv = x.get("receiver_id")
            if recv:
                key = (pid, recv)
                self.network[team][key] = self.network[team].get(key, 0) + 1
        if x.get("progressive"):
            td["progressive_passes"] += 1
            pd["progressive_passes"] += 1
        if complete and x.get("into_final_third"):
            td["final_third_entries"] += 1
        if complete and x.get("into_box"):
            td["box_entries"] += 1
        if "cross" in e["qualifiers"]:
            td["crosses"] += 1
            pd["crosses"] += 1
        if "long_ball" in e["qualifiers"]:
            td["long_balls"] += 1

    def _on_carry(self, e, team, opp, pid, pd, td, x) -> None:
        pd["carries"] += 1
        if e["end"]:
            srx, sry = rel_point(e["start"], e["attack_dir"])
            erx, ery = rel_point(e["end"], e["attack_dir"])
            d0 = math.hypot(L - srx, 34 - sry)
            d1 = math.hypot(L - erx, 34 - ery)
            box = in_box(erx, ery) and not in_box(srx, sry)
            if d1 <= 0.75 * d0 or box:
                pd["progressive_carries"] += 1
            if e["outcome"] == "complete":
                if srx < 70 <= erx:
                    td["final_third_entries"] += 1
                if box:
                    td["box_entries"] += 1

    def _on_take_on(self, e, team, opp, pid, pd, td, x) -> None:
        pd["take_ons"] += 1
        if e["outcome"] == "success":
            pd["take_ons_won"] += 1

    def _on_dribbled_past(self, e, team, opp, pid, pd, td, x) -> None:
        pd["dribbled_past"] += 1

    def _on_shot(self, e, team, opp, pid, pd, td, x) -> None:
        xg = float(x.get("xg", 0.0))
        td["shots"] += 1
        pd["shots"] += 1
        td["xg"] += xg
        pd["xg"] += xg
        on_target = e["outcome"] in ("goal", "saved")
        if on_target:
            td["shots_on_target"] += 1
            pd["shots_on_target"] += 1
        if xg >= BIG_CHANCE_XG:
            td["big_chances"] += 1
            pd["big_chances"] += 1
            if e["outcome"] != "goal":
                pd["big_chances_missed"] += 1
        pd["max_shot_speed_kmh"] = max(pd["max_shot_speed_kmh"], float(x.get("shot_speed_kmh", 0.0)))
        aid = x.get("assist_event_id")
        if aid and aid in self.passes_by_id:
            passer = self.passes_by_id[aid]["player_id"]
            kp = self._player(passer)
            kp["key_passes"] += 1
            kp["xa"] += xg
            if e["outcome"] == "goal":
                kp["assists"] += 1
        if on_target:
            for gk in self._gks_on(opp):
                self.p[gk]["xg_faced"] += xg
                if e["outcome"] == "goal":
                    self.p[gk]["goals_conceded"] += 1

    def _gks_on(self, team: str) -> list[str]:
        return [pid for pid in sorted(self.p) if pid in self.gk_ids and self.on_pitch.get(pid)
                and self.team_of.get(pid) == team]

    def _on_goal(self, e, team, opp, pid, pd, td, x) -> None:
        td["goals"] += 1
        pd["goals"] += 1

    def _on_pressure(self, e, team, opp, pid, pd, td, x) -> None:
        td["pressures"] += 1
        pd["pressures"] += 1

    def _regain(self, e, team, pd, td) -> None:
        rx = rel_x(e["start"]["x"], e["attack_dir"])
        if rx > HIGH_TURNOVER_RX:
            td["high_turnovers"] += 1
        lost = self.lost_at.get(team)
        if lost is not None and 0 <= e["elapsed"] - lost <= COUNTER_PRESS_S:
            td["counter_press_regains"] += 1

    def _on_tackle(self, e, team, opp, pid, pd, td, x) -> None:
        td["tackles"] += 1
        pd["tackles"] += 1
        if e["outcome"] == "won":
            pd["tackles_won"] += 1
            victim = x.get("opponent_id")
            if victim:
                self._player(victim)["dispossessed"] += 1
            # a won tackle is emitted before the possession changes hands, so it is always a regain
            self._regain(e, team, pd, td)

    def _on_interception(self, e, team, opp, pid, pd, td, x) -> None:
        td["interceptions"] += 1
        pd["interceptions"] += 1
        if e["possession_team_id"] == team:
            self._regain(e, team, pd, td)

    def _on_ball_recovery(self, e, team, opp, pid, pd, td, x) -> None:
        td["recoveries"] += 1
        pd["recoveries"] += 1
        if e["possession_team_id"] == team and e["sequence_index"] == 0:
            self._regain(e, team, pd, td)

    def _on_clearance(self, e, team, opp, pid, pd, td, x) -> None:
        td["clearances"] += 1
        pd["clearances"] += 1

    def _on_block(self, e, team, opp, pid, pd, td, x) -> None:
        td["blocks"] += 1
        pd["blocks"] += 1

    def _on_aerial_duel(self, e, team, opp, pid, pd, td, x) -> None:
        if e["outcome"] == "won":
            pd["aerial_duels_won"] += 1

    def _on_goalkeeper(self, e, team, opp, pid, pd, td, x) -> None:
        if e["outcome"] == "save" and "saves" in pd:
            pd["saves"] += 1

    def _on_foul(self, e, team, opp, pid, pd, td, x) -> None:
        td["fouls"] += 1
        pd["fouls_committed"] += 1
        victim = x.get("fouled_player_id")
        if victim:
            self._player(victim)["fouls_won"] += 1
        if not x.get("in_box"):  # a foul in the box gives a penalty, counted as a shot when taken
            self.t[opp]["free_kicks"] += 1

    def _on_card(self, e, team, opp, pid, pd, td, x) -> None:
        if e["outcome"] == "yellow":
            td["yellows"] += 1
            pd["yellow_cards"] += 1
        elif e["outcome"] == "second_yellow":
            td["yellows"] += 1
            td["reds"] += 1
            pd["yellow_cards"] += 1
            pd["red_cards"] += 1
            self._off(pid, e["elapsed"])
        elif e["outcome"] == "red":
            td["reds"] += 1
            pd["red_cards"] += 1
            self._off(pid, e["elapsed"])

    def _on_offside(self, e, team, opp, pid, pd, td, x) -> None:
        td["offsides"] += 1

    def _on_ball_out(self, e, team, opp, pid, pd, td, x) -> None:
        restart = x.get("restart")
        if restart == "corner":
            self.t[opp]["corners"] += 1
        elif restart == "throw_in":
            self.t[opp]["throw_ins"] += 1

    def _on_substitution(self, e, team, opp, pid, pd, td, x) -> None:
        self._off(x["player_out"], e["elapsed"])
        self._player(x["player_in"], on_at=e["elapsed"])

    # ------------------------------------------------------------ snapshot
    def _window_events(self, at: float) -> list[dict]:
        lo = at - WINDOW_S
        while self.window and self.window[0]["elapsed"] < lo - 2 * GAP_S:
            self.window.popleft()
        return [e for e in self.window if lo < e["elapsed"] <= at]

    def _rolling(self, at: float) -> dict[str, dict[str, float]]:
        """Rolling last-5-minute team metrics and the momentum, control and chaos indices.

        momentum = 100 x (0.3 x territory share + 0.3 x final-third entry share + 0.4 x xG share),
                   each share = team / (team + opponent) over the window
        control  = 100 x (0.35 x min(1, mean possession length / 25 s) + 0.40 x pass accuracy
                   + 0.25 x (1 - min(1, turnovers per minute / 1.5)))
        chaos    = 100 x (0.4 x min(1, turnovers per minute / 3) + 0.3 x min(1, possession changes
                   per minute / 4) + 0.3 x min(1, long-ball share / 0.3))
        Turnover: a possession lost in play (tackle, interception or recovery). All three
        indices are 0 when the window holds no events.
        """
        evs = self._window_events(at)
        acc = {t: {"xg": 0.0, "shots": 0, "passes": 0, "passes_completed": 0, "poss_time": 0.0,
                   "final_third_entries": 0, "pressures": 0, "turnovers": 0, "opp_half_touches": 0,
                   "long_balls": 0, "poss_len_total": 0.0, "poss_count": 0} for t in self.teams}
        changes = 0
        prev = None
        for e in evs:
            team = e["team_id"]
            a = acc[team]
            x = e.get("extra") or {}
            ty = e["type"]
            if prev is not None:
                gap = e["elapsed"] - prev["elapsed"]
                if 0 <= gap < GAP_S:
                    acc[prev["possession_team_id"]]["poss_time"] += gap
                if prev["possession_team_id"] != e["possession_team_id"]:
                    changes += 1
            prev = e
            pp = x.get("prev_possession")
            if pp and pp["team_id"] in acc:
                acc[pp["team_id"]]["poss_len_total"] += pp["duration_s"]
                acc[pp["team_id"]]["poss_count"] += 1
                if pp["end_reason"] in LOST_IN_PLAY:
                    acc[pp["team_id"]]["turnovers"] += 1
            if ty == "shot":
                a["xg"] += float(x.get("xg", 0.0))
                a["shots"] += 1
            elif ty == "pass":
                a["passes"] += 1
                if e["outcome"] == "complete":
                    a["passes_completed"] += 1
                    if x.get("into_final_third"):
                        a["final_third_entries"] += 1
                if "long_ball" in e["qualifiers"]:
                    a["long_balls"] += 1
            elif ty == "carry" and e["outcome"] == "complete" and e["end"]:
                if rel_x(e["start"]["x"], e["attack_dir"]) < 70 <= rel_x(e["end"]["x"], e["attack_dir"]):
                    a["final_third_entries"] += 1
            elif ty == "pressure":
                a["pressures"] += 1
            if ty in TOUCH_TYPES and e["player_id"] and rel_x(e["start"]["x"], e["attack_dir"]) > 52.5:
                a["opp_half_touches"] += 1
        span_min = max(1e-9, min(WINDOW_S, at) / 60.0)
        out = {}
        for t in self.teams:
            a, b = acc[t], acc[self.other(t)]
            total_time = a["poss_time"] + b["poss_time"]
            r = {
                "xg": round(a["xg"], 3),
                "shots": a["shots"],
                "passes": a["passes"],
                "pass_accuracy": round(a["passes_completed"] / a["passes"], 3) if a["passes"] else 0.0,
                "possession": round(a["poss_time"] / total_time, 3) if total_time else 0.0,
                "final_third_entries": a["final_third_entries"],
                "pressures": a["pressures"],
                "turnovers": a["turnovers"],
            }
            if evs:
                momentum = 100 * (0.3 * _share(a["opp_half_touches"], b["opp_half_touches"])
                                  + 0.3 * _share(a["final_third_entries"], b["final_third_entries"])
                                  + 0.4 * _share(a["xg"], b["xg"]))
                mean_len = a["poss_len_total"] / a["poss_count"] if a["poss_count"] else 0.0
                tpm = a["turnovers"] / span_min
                control = 100 * (0.35 * min(1.0, mean_len / 25.0) + 0.40 * r["pass_accuracy"]
                                 + 0.25 * (1.0 - min(1.0, tpm / 1.5)))
                direct = a["long_balls"] / a["passes"] if a["passes"] else 0.0
                chaos = 100 * (0.4 * min(1.0, tpm / 3.0) + 0.3 * min(1.0, (changes / span_min) / 4.0)
                               + 0.3 * min(1.0, direct / 0.3))
            else:
                momentum = control = chaos = 0.0
            r["momentum"] = round(momentum, 1)
            r["control"] = round(control, 1)
            r["chaos"] = round(chaos, 1)
            out[t] = r
        return out

    def _team_block(self, t: str, at: float) -> dict:
        d = self.t[t]
        o = self.t[self.other(t)]
        total_poss = d["possession_time_s"] + o["possession_time_s"]
        net = sorted(self.network[t].items(), key=lambda kv: (-kv[1], kv[0]))[:10]
        allowed = o["ppda_passes_allowed"]
        return {
            "goals": d["goals"],
            "shots": d["shots"],
            "shots_on_target": d["shots_on_target"],
            "xg": round(d["xg"], 3),
            "xg_per_shot": round(d["xg"] / d["shots"], 3) if d["shots"] else 0.0,
            "big_chances": d["big_chances"],
            "passes": d["passes"],
            "passes_completed": d["passes_completed"],
            "pass_accuracy": round(d["passes_completed"] / d["passes"], 3) if d["passes"] else 0.0,
            "progressive_passes": d["progressive_passes"],
            "final_third_entries": d["final_third_entries"],
            "box_entries": d["box_entries"],
            "crosses": d["crosses"],
            "long_ball_share": round(d["long_balls"] / d["passes"], 3) if d["passes"] else 0.0,
            "possession": round(d["possession_time_s"] / total_poss, 3) if total_poss else 0.0,
            "possessions": d["possessions"],
            "avg_possession_s": round(d["possession_seconds_total"] / d["possession_completed"], 1) if d["possession_completed"] else 0.0,
            "avg_possession_passes": round(d["possession_passes_total"] / d["possession_completed"], 2) if d["possession_completed"] else 0.0,
            "field_tilt": round(_share(d["final_third_touches"], o["final_third_touches"]), 3),
            "territory": round(_share(d["opp_half_touches"], o["opp_half_touches"]), 3),
            "tackles": d["tackles"],
            "interceptions": d["interceptions"],
            "recoveries": d["recoveries"],
            "clearances": d["clearances"],
            "blocks": d["blocks"],
            "pressures": d["pressures"],
            "ppda": round(allowed / d["ppda_defensive_actions"], 2) if d["ppda_defensive_actions"] else 0.0,
            "high_turnovers": d["high_turnovers"],
            "counter_press_regains": d["counter_press_regains"],
            "corners": d["corners"],
            "free_kicks": d["free_kicks"],
            "throw_ins": d["throw_ins"],
            "offsides": d["offsides"],
            "fouls": d["fouls"],
            "yellows": d["yellows"],
            "reds": d["reds"],
            "distance_km": round(d["distance_m"] / 1000.0, 2),
            "sprints": d["sprints"],
            "top_speed_kmh": d["top_speed_kmh"],
            "pass_network": [{"from": a, "to": b, "count": n} for (a, b), n in net],
        }

    def _player_block(self, pid: str, at: float) -> dict:
        d = self.p[pid]
        info = self.info.get(pid, {})
        out = {
            "team_id": self.team_of.get(pid, pid.rsplit("_", 1)[0]),
            "name": info.get("name"),
            "position": info.get("position"),
            "on_pitch": bool(self.on_pitch.get(pid, False)),
            "minutes": round(self._minutes(pid, at), 1),
            "touches": d["touches"],
            "passes": d["passes"],
            "passes_completed": d["passes_completed"],
            "pass_accuracy": round(d["passes_completed"] / d["passes"], 3) if d["passes"] else 0.0,
            "progressive_passes": d["progressive_passes"],
            "key_passes": d["key_passes"],
            "assists": d["assists"],
            "xa": round(d["xa"], 3),
            "crosses": d["crosses"],
            "shots": d["shots"],
            "shots_on_target": d["shots_on_target"],
            "goals": d["goals"],
            "xg": round(d["xg"], 3),
            "big_chances": d["big_chances"],
            "big_chances_missed": d["big_chances_missed"],
            "max_shot_speed_kmh": d["max_shot_speed_kmh"],
            "carries": d["carries"],
            "progressive_carries": d["progressive_carries"],
            "take_ons": d["take_ons"],
            "take_ons_won": d["take_ons_won"],
            "dispossessed": d["dispossessed"],
            "tackles": d["tackles"],
            "tackles_won": d["tackles_won"],
            "interceptions": d["interceptions"],
            "recoveries": d["recoveries"],
            "clearances": d["clearances"],
            "blocks": d["blocks"],
            "aerial_duels_won": d["aerial_duels_won"],
            "dribbled_past": d["dribbled_past"],
            "fouls_committed": d["fouls_committed"],
            "fouls_won": d["fouls_won"],
            "yellow_cards": d["yellow_cards"],
            "red_cards": d["red_cards"],
            "pressures": d["pressures"],
            "distance_km": round(d["distance_m"] / 1000.0, 3),
            "high_intensity_distance_km": round(d["high_intensity_distance_m"] / 1000.0, 3),
            "top_speed_kmh": d["top_speed_kmh"],
            "current_speed_kmh": d["current_speed_kmh"] if self.on_pitch.get(pid) else 0.0,
            "sprints": d["sprints"],
        }
        if "saves" in d:
            out["saves"] = d["saves"]
            out["xg_faced"] = round(d["xg_faced"], 3)
            out["goals_prevented"] = round(d["xg_faced"] - d["goals_conceded"], 3)
        return out

    def snapshot(self, at: float | None = None) -> dict:
        """Full snapshot. `at` (match seconds) fixes the clock; defaults to the latest message seen."""
        at = self.elapsed if at is None else max(at, self.elapsed)
        period = self.period
        ps = self.period_start.get(period, 0.0)
        rolling = self._rolling(at)
        teams = {}
        for t in self.teams:
            block = self._team_block(t, at)
            block["last_5_min"] = rolling[t]
            teams[t] = block
        minute = (45 if period == 2 else 0) + int((at - ps) // 60)
        return {
            "kind": "snapshot",
            "schema_version": self.meta.get("schema_version"),
            "match_id": self.match_id,
            "elapsed": round(at, 1),
            "period": period,
            "clock": fmt_clock(period, at - ps),
            "minute": minute,
            "score": dict(self.score),
            "teams": teams,
            "players": {pid: self._player_block(pid, at) for pid in sorted(self.p)},
        }


def clock_to_elapsed(text: str, meta: dict) -> float:
    """Parse '14', '14:00', '45+2:00' or '90+3:00' into match seconds, using match.json stoppage."""
    text = text.strip()
    stop1 = float(meta.get("stoppage_seconds", {}).get("1", 0.0))
    if ":" in text:
        mm, ss = text.split(":", 1)
        secs = float(ss)
    else:
        mm, secs = text, 0.0
    if "+" in mm:
        base, extra = mm.split("+", 1)
        base, extra = int(base), int(extra)
        if base <= 45:
            return 45 * 60 + extra * 60 + secs
        return 45 * 60 + stop1 + 45 * 60 + extra * 60 + secs
    minute = int(mm)
    if minute < 45:
        return minute * 60 + secs
    return 45 * 60 + stop1 + (minute - 45) * 60 + secs


def snapshots_every(meta: dict, events: list[dict], frames: list[dict], every: float):
    """Yield snapshots every `every` seconds of match time, plus half time and full time."""
    import heapq
    engine = StatsEngine(meta)
    stream = heapq.merge(((f["elapsed"], 0, "frame", f) for f in frames),
                         ((e["elapsed"], 1, "event", e) for e in events), key=lambda m: (m[0], m[1]))
    next_at = every
    for t, _, kind, data in stream:
        while t > next_at:
            yield engine.snapshot(at=next_at)
            next_at += every
        if kind == "frame":
            engine.ingest_frame(data)
        else:
            engine.ingest_event(data)
            if data["type"] == "period_end":
                snap = engine.snapshot()
                snap["label"] = "half_time" if data["extra"].get("period") == 1 else "full_time"
                yield snap
                next_at = (math.floor(t / every) + 1) * every
