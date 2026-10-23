"""Match engine: a possession state machine driving a physics-lite tracking model.

Events and tracking are produced together, so every event's location is where
the ball actually is in the tracking data, receivers are picked from players'
real positions, and pressure is measured from real distances.

Coordinates in all output are absolute: x in [0, 105], y in [0, 68].
Each event carries attack_dir (+1 = acting team attacks towards x = 105).
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass, field

from .script import Script
from .world import FORMATIONS, PITCH_LENGTH as L, PITCH_WIDTH as W, Player, Team, World
from .xg import shot_xg

DT = 0.2  # physics step, seconds
SPRINT_KMH = 25.2


def clamp(v: float, lo: float, hi: float) -> float:
    return lo if v < lo else hi if v > hi else v


def dist(a: tuple[float, float], b: tuple[float, float]) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def fmt_clock(period: int, period_seconds: float) -> str:
    base = 0 if period == 1 else 45 * 60
    regular = 45 * 60
    if period_seconds <= regular:
        total = base + period_seconds
        return f"{int(total // 60):02d}:{total % 60:04.1f}"
    extra = period_seconds - regular
    return f"{(base + regular) // 60}+{int(extra // 60)}:{extra % 60:04.1f}"


@dataclass
class PlayerState:
    p: Player
    team_id: str
    role: str
    ax: float  # anchor in team-relative frame
    ay: float
    x: float = 0.0
    y: float = 0.0
    vx: float = 0.0
    vy: float = 0.0
    on_pitch: bool = True
    yellow: int = 0
    jitter: tuple[float, float] = (0.0, 0.0)
    entered_at: float = 0.0  # elapsed seconds when they came on
    boost: int = 0

    def a(self, name: str) -> float:
        return self.p.attr(name) + self.boost

    @property
    def is_gk(self) -> bool:
        return self.role == "GK"

    @property
    def pos(self) -> tuple[float, float]:
        return (self.x, self.y)

    @property
    def speed(self) -> float:
        return math.hypot(self.vx, self.vy)


@dataclass
class TeamState:
    team: Team
    players: dict[str, PlayerState] = field(default_factory=dict)
    dir: int = 1
    bench: list[str] = field(default_factory=list)
    subs_made: int = 0
    sub_minutes: list[float] = field(default_factory=list)
    natural_momentum: float = 0.0
    score: int = 0

    @property
    def id(self) -> str:
        return self.team.id

    def active(self) -> list[PlayerState]:
        return [s for s in self.players.values() if s.on_pitch]

    def outfield(self) -> list[PlayerState]:
        return [s for s in self.active() if not s.is_gk]

    def gk(self) -> PlayerState | None:
        for s in self.active():
            if s.is_gk:
                return s
        return None

    def rel(self, x: float, y: float) -> tuple[float, float]:
        return (x, y) if self.dir == 1 else (L - x, W - y)

    def abs(self, rx: float, ry: float) -> tuple[float, float]:
        return (rx, ry) if self.dir == 1 else (L - rx, W - ry)


class MatchEngine:
    def __init__(self, world: World, seed: int = 1, script: Script | None = None,
                 tracking_hz: float = 1.0, match_id: str = "m_0001"):
        self.world = world
        self.rng = random.Random(seed)
        self.script = script or Script()
        self.match_id = match_id
        self.tracking_interval = 1.0 / tracking_hz
        self.home = self._team_state(world.home)
        self.away = self._team_state(world.away)
        self.events: list[dict] = []
        self.frames: list[dict] = []
        self.elapsed = 0.0          # monotonic seconds since kickoff (includes stoppage)
        self.period = 1
        self.period_start = 0.0     # elapsed when this period began
        self.next_frame_at = 0.0
        self.ball = (L / 2, W / 2)
        self.ball_z = 0.0
        self.poss: TeamState = self.home
        self.carrier: PlayerState | None = None
        self.poss_id = 0
        self.seq = 0
        self.play_pattern = "kickoff"
        self.last_event_id: str | None = None
        self._eid = 0
        self.pending_reds = list(self.script.red_cards)
        self._mom: dict[str, float] = {}
        self._press: dict[str, float] = {}
        self.stoppage = {1: self.rng.choice([1, 2, 2, 3]) * 60.0, 2: self.rng.choice([3, 4, 4, 5, 6]) * 60.0}

    # ------------------------------------------------------------------ setup
    def _team_state(self, team: Team) -> TeamState:
        ts = TeamState(team=team, bench=list(team.bench))
        slots = FORMATIONS[team.formation]
        for pid, (role, ax, ay, _group) in zip(team.starting_xi, slots):
            ps = PlayerState(p=team.player(pid), team_id=team.id, role=role, ax=ax, ay=ay)
            ps.boost = self.script.standouts.get(pid, 0) if hasattr(self, "script") else 0
            ts.players[pid] = ps
        ts.sub_minutes = sorted(self.rng.uniform(56, 84) for _ in range(self.rng.choice([3, 4, 5])))
        return ts

    def other(self, t: TeamState) -> TeamState:
        return self.away if t is self.home else self.home

    @property
    def minute(self) -> float:
        return (self.period_start_minute + (self.elapsed - self.period_start) / 60.0)

    @property
    def period_start_minute(self) -> float:
        return 0.0 if self.period == 1 else 45.0

    def mods(self, t: TeamState) -> tuple[float, float, float]:
        m, c, p = self.script.mods(t.id, self.minute)
        return (clamp(m + t.natural_momentum, -0.8, 1.2), clamp(c, -0.8, 1.0), clamp(p, -0.8, 1.0))

    # --------------------------------------------------------------- physics
    def _vmax(self, s: PlayerState) -> float:
        base = 6.9 + (s.a("pace") - 50) * 0.05
        on_for = (self.elapsed - s.entered_at) / 5700.0
        fatigue = 1.0 - 0.12 * on_for * (1.3 - s.p.stamina / 100.0)
        return base * fatigue

    def _target(self, t: TeamState, s: PlayerState, in_poss: bool) -> tuple[float, float]:
        brx, bry = t.rel(*self.ball)
        if s.is_gk:
            rx = clamp(4 + (brx - 52.5) * 0.12, 2, 18)
            ry = 34 + (bry - 34) * 0.18
        else:
            mom_poss = self._mom.get(self.poss.id, 0.0)
            if in_poss:
                k, width, lat, shift = 0.62, 1.12, 0.22, 4.0 + 7.0 * mom_poss
            else:
                k, width, lat, shift = 0.52, 0.82, 0.42, -3.0 - 5.0 * max(0.0, mom_poss) + 4.0 * self._press.get(t.id, 0.0)
            rx = s.ax + (brx - 52.5) * k + shift
            ry = 34 + (s.ay - 34) * width + (bry - 34) * lat
            rx = clamp(rx, 6, 93 if in_poss else 100)
            if not in_poss and s.p.group == "DEF":
                rx = max(rx, 7.0)
            ry = clamp(ry, 2, 66)
        rx += s.jitter[0]
        ry += s.jitter[1]
        return t.abs(rx, ry)

    def advance(self, duration: float, ball_to: tuple[float, float] | None = None,
                carrier: PlayerState | None = None, receiver: PlayerState | None = None,
                height: float = 0.0, chase: bool = True, dead: bool = False) -> None:
        """Move the world forward. Ball travels linearly to ball_to over duration."""
        steps = max(1, int(round(duration / DT)))
        start = self.ball
        end = ball_to or self.ball
        defending = self.other(self.poss)
        _m, _c, press = self.mods(defending)
        press_level = clamp(defending.team.style["press"] + press, 0, 1.5)
        self._mom = {t.id: self.mods(t)[0] for t in (self.home, self.away)}
        self._press = {t.id: self.mods(t)[2] for t in (self.home, self.away)}
        for i in range(1, steps + 1):
            frac = i / steps
            self.ball = (start[0] + (end[0] - start[0]) * frac, start[1] + (end[1] - start[1]) * frac)
            self.ball_z = 4 * height * frac * (1 - frac)
            chasers: set[str] = set()
            if chase and not dead:
                outs = sorted(defending.outfield(), key=lambda s: dist(s.pos, self.ball))
                n = 1
                brx_def, _ = defending.rel(*self.ball)
                if brx_def > 55 and press_level > 0.55:
                    n = 2
                if brx_def > 40 and press_level > 0.9:
                    n = 3
                if brx_def < 30:
                    n = 2
                chasers = {s.p.id for s in outs[:n] if dist(s.pos, self.ball) < 30}
            marks: dict[str, tuple[float, float]] = {}
            if not dead:
                brx_def, _ = defending.rel(*self.ball)
                if brx_def < 42:
                    gx, gy = defending.abs(0, 34)
                    attackers = self.poss.outfield()
                    for d_ in defending.outfield():
                        if d_.p.id in chasers or d_.p.group == "FWD":
                            continue
                        a_ = min(attackers, key=lambda a: dist(a.pos, d_.pos))
                        if dist(a_.pos, d_.pos) < 16:
                            vx, vy = gx - a_.x, gy - a_.y
                            n_ = math.hypot(vx, vy) or 1.0
                            marks[d_.p.id] = (a_.x + vx / n_ * 1.6, a_.y + vy / n_ * 1.6)
            for t in (self.home, self.away):
                in_poss = t is self.poss
                for s in t.active():
                    if carrier is s:
                        tx, ty = self.ball
                    elif receiver is s:
                        tx, ty = end
                    elif s.p.id in chasers:
                        tx, ty = self.ball
                    elif s.p.id in marks:
                        sx_, sy_ = self._target(t, s, in_poss)
                        mx_, my_ = marks[s.p.id]
                        tx, ty = 0.7 * mx_ + 0.3 * sx_, 0.7 * my_ + 0.3 * sy_
                    else:
                        tx, ty = self._target(t, s, in_poss)
                    self._move(s, tx, ty, carrying=carrier is s,
                               boost=1.0 + 0.08 * max(0.0, self._press.get(t.id, 0.0)) if s.p.id in chasers else 1.0)
                    if carrier is s:
                        s.x, s.y = self.ball
            self.elapsed += DT
            if self.rng.random() < DT / 9.0:
                self._refresh_jitter()
            while self.elapsed >= self.next_frame_at - 1e-6:
                self._emit_frame()
                self.next_frame_at += self.tracking_interval

    def _move(self, s: PlayerState, tx: float, ty: float, carrying: bool = False, boost: float = 1.0) -> None:
        dx, dy = tx - s.x, ty - s.y
        d = math.hypot(dx, dy)
        vmax = self._vmax(s) * (0.9 if carrying else 1.0) * boost
        desired = min(vmax, d * 0.45)
        if d > 1e-6:
            dvx, dvy = dx / d * desired, dy / d * desired
        else:
            dvx = dvy = 0.0
        ax, ay = (dvx - s.vx) / DT, (dvy - s.vy) / DT
        amax = 4.0
        a = math.hypot(ax, ay)
        if a > amax:
            ax, ay = ax / a * amax, ay / a * amax
        s.vx += ax * DT
        s.vy += ay * DT
        s.x = clamp(s.x + s.vx * DT, -2, L + 2)
        s.y = clamp(s.y + s.vy * DT, -2, W + 2)

    def _refresh_jitter(self) -> None:
        for t in (self.home, self.away):
            for s in t.active():
                if not s.is_gk:
                    s.jitter = (self.rng.gauss(0, 3.6), self.rng.gauss(0, 3.6))

    def _emit_frame(self) -> None:
        players = []
        for t in (self.home, self.away):
            for s in t.active():
                players.append([s.p.id, round(s.x, 2), round(s.y, 2), round(s.speed * 3.6, 1)])
        self.frames.append({
            "match_id": self.match_id,
            "elapsed": round(self.next_frame_at, 2),
            "period": self.period,
            "clock": fmt_clock(self.period, self.next_frame_at - self.period_start),
            "ball": [round(self.ball[0], 2), round(self.ball[1], 2), round(self.ball_z, 2)],
            "players": players,
        })

    # ---------------------------------------------------------------- events
    def emit(self, type_: str, s: PlayerState | None, team: TeamState, outcome: str | None = None,
             start: tuple[float, float] | None = None, end: tuple[float, float] | None = None,
             body_part: str | None = None, qualifiers: list[str] | None = None,
             related: str | None = None, under_pressure: bool = False,
             pressure_player: str | None = None, extra: dict | None = None,
             count_in_sequence: bool = True) -> str:
        self._eid += 1
        eid = f"e_{self._eid:06d}"
        start = start or self.ball
        start = (clamp(start[0], 0, L), clamp(start[1], 0, W))
        if end:
            end = (clamp(end[0], 0, L), clamp(end[1], 0, W))
        ev = {
            "event_id": eid,
            "match_id": self.match_id,
            "elapsed": round(self.elapsed, 2),
            "period": self.period,
            "clock": fmt_clock(self.period, self.elapsed - self.period_start),
            "minute": int(self.minute),
            "team_id": team.id,
            "player_id": s.p.id if s else None,
            "type": type_,
            "outcome": outcome,
            "start": {"x": round(start[0], 2), "y": round(start[1], 2)},
            "end": {"x": round(end[0], 2), "y": round(end[1], 2)} if end else None,
            "attack_dir": team.dir,
            "body_part": body_part,
            "possession_id": self.poss_id,
            "possession_team_id": self.poss.id,
            "sequence_index": self.seq,
            "play_pattern": self.play_pattern,
            "under_pressure": under_pressure,
            "pressure_player_id": pressure_player,
            "related_event_id": related,
            "qualifiers": qualifiers or [],
            "extra": extra or {},
        }
        self.events.append(ev)
        if count_in_sequence:
            self.seq += 1
        self.last_event_id = eid
        return eid

    # ------------------------------------------------------------ possession
    def new_possession(self, team: TeamState, carrier: PlayerState, pattern: str) -> None:
        self.poss = team
        self.carrier = carrier
        self.poss_id += 1
        self.seq = 0
        self.play_pattern = pattern

    def nearest(self, team: TeamState, point: tuple[float, float], outfield: bool = True,
                exclude: PlayerState | None = None) -> PlayerState:
        pool = team.outfield() if outfield else team.active()
        pool = [s for s in pool if s is not exclude] or team.active()
        return min(pool, key=lambda s: dist(s.pos, point))

    # ------------------------------------------------------------ main loop
    def run(self) -> None:
        self._place_for_kickoff(first=True)
        kickoff_team = self.home if self.rng.random() < 0.5 else self.away
        first_kicker = kickoff_team
        for period in (1, 2):
            self.period = period
            self.period_start = self.elapsed
            if period == 2:
                self.home.dir, self.away.dir = -1, 1
                self._place_for_kickoff()
                kickoff_team = self.other(first_kicker)
            else:
                self.home.dir, self.away.dir = 1, -1
                self._place_for_kickoff()
            self.next_frame_at = max(self.next_frame_at, self.elapsed)
            self.restart_kickoff(kickoff_team)
            end_at = self.period_start + 45 * 60 + self.stoppage[period]
            minute_tick = self.elapsed
            while self.elapsed < end_at:
                if self.elapsed - minute_tick >= 60:
                    minute_tick = self.elapsed
                    for t in (self.home, self.away):
                        t.natural_momentum = 0.85 * t.natural_momentum + self.rng.gauss(0, 0.1)
                self.step()
            self.emit("period_end", None, self.home, extra={"period": period}, count_in_sequence=False)

    def _place_for_kickoff(self, first: bool = False) -> None:
        self.ball = (L / 2, W / 2)
        for t in (self.home, self.away):
            for s in t.active():
                rx = min(s.ax * 0.75 + 4, 48) if not s.is_gk else 5
                x, y = t.abs(rx, s.ay)
                s.x, s.y, s.vx, s.vy = x, y, 0.0, 0.0

    # --------------------------------------------------------------- restarts
    def restart_kickoff(self, team: TeamState) -> None:
        self.ball = (L / 2, W / 2)
        taker = max(team.outfield(), key=lambda s: s.ax)  # striker
        taker.x, taker.y = self.ball
        self.new_possession(team, taker, "kickoff")
        self.do_pass(kind="kickoff")

    def dead_ball(self, seconds: float) -> None:
        self.advance(seconds, chase=False, dead=True)

    def restart(self, kind: str, team: TeamState, at: tuple[float, float]) -> None:
        self._maybe_substitutions()
        self.ball = (clamp(at[0], 0, L), clamp(at[1], 0, W))
        rx, ry = team.rel(*self.ball)
        if kind == "throw_in":
            taker = min(team.outfield(), key=lambda s: dist(s.pos, self.ball) + (0 if s.role.endswith("B") else 4))
            wait = self.rng.uniform(8, 20)
        elif kind == "goal_kick":
            taker = team.gk() or self.nearest(team, self.ball)
            self.ball = team.abs(6, 34 + self.rng.choice([-9, 9]))
            wait = self.rng.uniform(16, 30)
        elif kind == "corner":
            taker = max(team.outfield(), key=lambda s: s.a("passing") + (8 if s.role in ("RW", "LW", "RAM", "LAM", "CAM") else 0))
            self.ball = team.abs(L - 0.5, 0.5 if ry < 34 else W - 0.5)
            wait = self.rng.uniform(22, 38)
        elif kind == "free_kick":
            taker = max(team.outfield(), key=lambda s: s.a("passing") - dist(s.pos, self.ball) * 0.6)
            wait = self.rng.uniform(15, 35)
        elif kind == "penalty":
            taker = max(team.outfield(), key=lambda s: s.a("finishing"))
            self.ball = team.abs(L - 11, 34)
            wait = self.rng.uniform(45, 80)
        elif kind == "keeper":
            taker = team.gk() or self.nearest(team, self.ball)
            self.ball = team.abs(10, 34 + self.rng.uniform(-8, 8))
            wait = self.rng.uniform(4, 9)
        else:
            raise ValueError(kind)
        self.dead_ball(wait)
        taker.x, taker.y = self.ball
        self.new_possession(team, taker, kind)
        if kind == "corner":
            self.do_cross(from_set_piece=True)
        elif kind == "penalty":
            self.do_shot(penalty=True)
        elif kind == "free_kick":
            rx, ry = team.rel(*self.ball)
            xg = shot_xg(rx, ry)
            if rx > 78 and xg > 0.04 and self.rng.random() < 0.35:
                self.do_shot(direct_free_kick=True)
            elif rx > 72 and self.rng.random() < 0.6:
                self.do_cross(from_set_piece=True)
            else:
                self.do_pass(kind="free_kick")
        elif kind == "throw_in":
            self.do_pass(kind="throw_in")
        elif kind == "goal_kick":
            self.do_pass(kind="goal_kick")
        else:
            self.do_pass(kind="keeper")

    def _maybe_substitutions(self) -> None:
        for t in (self.home, self.away):
            while t.sub_minutes and self.minute >= t.sub_minutes[0] and t.bench:
                t.sub_minutes.pop(0)
                self._substitute(t)

    def _substitute(self, t: TeamState) -> None:
        outs = [s for s in t.outfield()]
        if not outs:
            return
        # most tired relative to stamina, prefer attackers late on
        def tiredness(s: PlayerState) -> float:
            return (self.elapsed - s.entered_at) * (1.2 - s.p.stamina / 100) + (300 if s.role in ("ST", "RW", "LW", "RAM", "LAM", "CAM") else 0) + self.rng.uniform(0, 400)
        off = max(outs, key=tiredness)
        group = off.p.group
        cands = [pid for pid in t.bench if t.team.player(pid).group == group and t.team.player(pid).group != "GK"]
        if not cands:
            cands = [pid for pid in t.bench if t.team.player(pid).group != "GK"]
        if not cands:
            return
        pid = self.rng.choice(cands)
        t.bench.remove(pid)
        on = PlayerState(p=t.team.player(pid), team_id=t.id, role=off.role, ax=off.ax, ay=off.ay,
                         entered_at=self.elapsed, boost=self.script.standouts.get(pid, 0))
        on.x, on.y = t.abs(52.5, 0 if off.ay < 34 else W)
        off.on_pitch = False
        t.players[pid] = on
        t.subs_made += 1
        self.emit("substitution", off, t, extra={"player_in": pid, "player_out": off.p.id},
                  count_in_sequence=False)
        self.dead_ball(self.rng.uniform(15, 30))

    # ----------------------------------------------------------------- step
    def step(self) -> None:
        if self._forced_red():
            return
        t = self.poss
        s = self.carrier
        if s is None or not s.on_pitch:
            s = self.nearest(t, self.ball)
            self.carrier = s
        opp = self.other(t)
        rx, ry = t.rel(*self.ball)
        presser = self.nearest(opp, self.ball)
        pd = dist(presser.pos, self.ball)
        under = pd < 4.0
        if under:
            self.emit("pressure", presser, opp, start=presser.pos, related=self.last_event_id,
                      extra={"target_player_id": s.p.id, "distance_m": round(pd, 1)},
                      count_in_sequence=False)
        mom, ctrl, _press = self.mods(t)
        # challenges that end in a foul without a formal tackle (shirt pulls, late ones)
        if under and not s.is_gk:
            r0 = self.rng.random()
            box_now = rx > 88.5 and 13.84 < ry < 54.16
            if r0 < (0.006 if box_now else 0.055):
                self._foul(presser, s, self.last_event_id)
                return
            if r0 < 0.13:
                # standing tackle attempt
                win = clamp(0.5 + (presser.a("tackling") - s.a("dribbling")) * 0.01, 0.25, 0.8)
                if self.rng.random() < win:
                    self.emit("tackle", presser, opp, "won", start=self.ball, related=self.last_event_id,
                              extra={"opponent_id": s.p.id})
                    self.new_possession(opp, presser, "regain")
                    presser.x, presser.y = self.ball
                    return
                self.emit("tackle", presser, opp, "lost", start=self.ball, related=self.last_event_id,
                          extra={"opponent_id": s.p.id}, count_in_sequence=False)
        # decision time on the ball
        hold = self.rng.uniform(0.9, 2.8) * (0.6 if under else 1.0) * (1.0 + 0.3 * ctrl)
        self.advance(hold, carrier=s)
        if s.is_gk:
            self.do_pass(kind="open", under=under, presser=presser)
            return
        xg_here = shot_xg(rx, ry)
        in_box = rx > 88.5 and 13.84 < ry < 54.16
        p_shot = 0.0
        if rx > 76:
            p_shot = clamp(0.005 + xg_here * 0.45 + mom * 0.06, 0, 0.45) * (0.7 if under else 1.0)
            if in_box:
                p_shot = max(p_shot, 0.085 + 0.07 * mom)
            elif rx > 78 and 18 < ry < 50:
                # edge-of-box efforts
                p_shot = max(p_shot, (0.21 + 0.08 * mom) * (0.6 if under else 1.0))
        elif rx > 70 and 22 < ry < 46:
            # speculative long-range efforts
            p_shot = (0.035 + 0.02 * mom) * (0.5 if under else 1.0)
        wide = ry < 16 or ry > 52
        p_cross = 0.32 if (rx > 80 and wide) else 0.0
        drib = s.a("dribbling")
        p_drib = clamp(0.012 + (drib - 60) * 0.0012 + (0.05 if (under and rx > 55) else 0), 0.005, 0.15)
        space_ahead = min((dist(o.pos, t.abs(min(rx + 8, L), ry)) for o in opp.active()), default=20)
        p_carry = (0.30 if space_ahead > 8 else 0.12) * (0.5 if under else 1.0)
        p_clear = 0.55 if (rx < 22 and under) else 0.0
        r = self.rng.random()
        if r < p_clear:
            self.do_clearance(under=under, presser=presser)
            return
        r = self.rng.random()
        if r < p_shot:
            self.do_shot(under=under, presser=presser)
        elif r < p_shot + p_cross:
            self.do_cross(under=under, presser=presser)
        elif r < p_shot + p_cross + p_drib:
            self.do_dribble(presser)
        elif r < p_shot + p_cross + p_drib + p_carry:
            self.do_carry(under=under, presser=presser)
        else:
            self.do_pass(kind="open", under=under, presser=presser)

    # ---------------------------------------------------------------- passes
    def _choose_receiver(self, t: TeamState, s: PlayerState, kind: str) -> PlayerState:
        opp = self.other(t)
        brx, bry = t.rel(*self.ball)
        directness = t.team.style["directness"] + self.mods(t)[0] * 0.3 - self.mods(t)[1] * 0.2
        long_ball = (kind in ("goal_kick", "keeper") and self.rng.random() < 0.35 + directness * 0.4) or \
                    (kind == "open" and self.rng.random() < 0.05 + directness * 0.07)
        pref, sd = (38.0, 10.0) if long_ball else (15.0, 9.0)
        if kind == "throw_in":
            pref, sd = 11.0, 6.0
        if kind == "kickoff":
            pref, sd = 10.0, 5.0
        best, best_w = None, -1.0
        weights = []
        for c in t.active():
            if c is s:
                continue
            crx, cry = t.rel(c.x, c.y)
            d = dist(c.pos, self.ball)
            gain = crx - brx
            if kind == "kickoff" and gain > 0:
                continue
            open_d = min((dist(o.pos, c.pos) for o in opp.active()), default=10)
            w = math.exp(-((d - pref) / sd) ** 2)
            w *= 1.0 + max(0.0, gain) / 25.0 * (0.6 + directness)
            w *= min(open_d, 7.0) / 7.0 + 0.12
            if c.is_gk:
                w *= 0.35 if brx < 35 else 0.0
            if gain < -15 and brx > 60:
                w *= 0.5
            weights.append((c, w))
            if w > best_w:
                best, best_w = c, w
        total = sum(w for _, w in weights)
        if total <= 0:
            return best or self.nearest(t, self.ball, exclude=s)
        r = self.rng.random() * total
        for c, w in weights:
            r -= w
            if r <= 0:
                return c
        return weights[-1][0]

    def do_pass(self, kind: str = "open", under: bool = False, presser: PlayerState | None = None) -> None:
        t, s = self.poss, self.carrier
        opp = self.other(t)
        mom, ctrl, _ = self.mods(t)
        recv = self._choose_receiver(t, s, kind)
        brx, bry = t.rel(*self.ball)
        crx, cry = t.rel(recv.x, recv.y)
        lead = 2.5 if crx > brx else 0.5
        trx = clamp(crx + lead + self.rng.gauss(0, 1.2), 1, L - 1)
        try_ = clamp(cry + self.rng.gauss(0, 1.2), 1, W - 1)
        target = t.abs(trx, try_)
        length = dist(self.ball, target)
        height = "ground"
        if kind in ("goal_kick", "keeper") and length > 30:
            height = "high"
        elif length > 28:
            height = "high" if self.rng.random() < 0.6 else "low"
        gain = trx - brx
        p = 0.935 - 0.0042 * length
        p -= 0.12 if under else 0.0
        p -= 0.06 if trx > 83 else 0.0
        p -= 0.04 if gain > 12 else 0.0
        p += 0.04 if gain < 0 else 0.0
        p += (s.a("passing") - 70) * 0.004
        p += ctrl * 0.05 + mom * 0.03 + t.team.style["control"] * 0.03
        opp_near_target = min((dist(o.pos, target) for o in opp.active()), default=10)
        if opp_near_target < 3:
            p -= 0.08
        if kind in ("throw_in", "kickoff"):
            p += 0.06
        p = clamp(p, 0.25, 0.985)
        quals = []
        if kind != "open":
            quals.append(kind)
        if length > 32:
            quals.append("long_ball")
        if abs(try_ - bry) > 35:
            quals.append("switch")
        deepest = min((opp.rel(o.x, o.y)[0] for o in opp.outfield()), default=0)
        if gain > 12 and (L - deepest) < trx:
            quals.append("through_ball")
        body = "hands" if kind == "throw_in" else ("right_foot" if s.p.foot == "right" else "left_foot")
        if kind == "keeper" and self.rng.random() < 0.4:
            body = "hands"
        success = self.rng.random() < p
        offside = "through_ball" in quals and success and self.rng.random() < 0.18
        ball_speed = 15.0 if height == "ground" else 19.0
        duration = max(0.5, length / ball_speed)
        h = {"ground": 0.0, "low": 1.5, "high": 9.0}[height] * (length / 40.0 if height != "ground" else 0)
        extra = {"length_m": round(length, 1), "height": height, "receiver_id": recv.p.id,
                 "ball_speed_kmh": round(ball_speed * 3.6 * self.rng.uniform(0.85, 1.25), 1)}
        if offside:
            eid = self.emit("pass", s, t, "offside", start=self.ball, end=target, body_part=body,
                            qualifiers=quals, under_pressure=under,
                            pressure_player=presser.p.id if presser and under else None, extra=extra)
            self.advance(duration, ball_to=target, receiver=recv, height=h)
            self.emit("offside", recv, t, related=eid, count_in_sequence=False)
            self.restart("free_kick", opp, self.ball)
            return
        if success:
            self.emit("pass", s, t, "complete", start=self.ball, end=target, body_part=body,
                      qualifiers=quals, under_pressure=under,
                      pressure_player=presser.p.id if presser and under else None, extra=extra)
            self.advance(duration, ball_to=target, receiver=recv, height=h)
            recv.x, recv.y = target
            self.carrier = recv
            return
        # failed pass
        out_side = try_ < 9 or try_ > W - 9 or length > 30
        if out_side and self.rng.random() < 0.55:
            out_pt = (clamp(target[0] + self.rng.gauss(0, 3), 1, L - 1), 0.0 if target[1] < W / 2 else W)
            eid = self.emit("pass", s, t, "out", start=self.ball, end=out_pt, body_part=body,
                            qualifiers=quals, under_pressure=under,
                            pressure_player=presser.p.id if presser and under else None, extra=extra)
            self.advance(max(0.5, dist(self.ball, out_pt) / ball_speed), ball_to=out_pt, height=h)
            self.emit("ball_out", None, t, start=out_pt, related=eid, extra={"restart": "throw_in"},
                      count_in_sequence=False)
            self.restart("throw_in", opp, out_pt)
            return
        frac = self.rng.uniform(0.55, 1.0)
        cut = (self.ball[0] + (target[0] - self.ball[0]) * frac, self.ball[1] + (target[1] - self.ball[1]) * frac)
        interceptor = self.nearest(opp, cut, outfield=False)
        eid = self.emit("pass", s, t, "incomplete", start=self.ball, end=cut, body_part=body,
                        qualifiers=quals, under_pressure=under,
                        pressure_player=presser.p.id if presser and under else None, extra=extra)
        self.advance(duration * frac, ball_to=cut, receiver=interceptor, height=h * frac)
        interceptor.x, interceptor.y = cut
        self.new_possession(opp, interceptor, "regain")
        # cut out in flight = interception; overhit or misplaced and picked up = recovery
        kind_ = "interception" if frac < 0.68 else "ball_recovery"
        self.emit(kind_, interceptor, opp, outcome="won", start=cut, related=eid)

    # ---------------------------------------------------------------- carries
    def do_carry(self, under: bool = False, presser: PlayerState | None = None,
                 after_dribble: bool = False) -> None:
        t, s = self.poss, self.carrier
        opp = self.other(t)
        rx, ry = t.rel(*self.ball)
        length = self.rng.uniform(5, 9) if after_dribble else self.rng.uniform(4, 15)
        ang = self.rng.gauss(0, 0.5)
        if rx > 70:
            ang += (34 - ry) / 34 * 0.4  # cut inside
        trx = clamp(rx + length * math.cos(ang), 1, L - 1)
        try_ = clamp(ry + length * math.sin(ang), 1, W - 1)
        target = t.abs(trx, try_)
        duration = length / (self._vmax(s) * 0.82)
        if under and not after_dribble and self.rng.random() < 0.16 and presser:
            stop = (self.ball[0] + (target[0] - self.ball[0]) * 0.4, self.ball[1] + (target[1] - self.ball[1]) * 0.4)
            eid = self.emit("carry", s, t, "dispossessed", start=self.ball, end=stop, under_pressure=True,
                            pressure_player=presser.p.id, extra={"length_m": round(dist(self.ball, stop), 1)})
            self.advance(duration * 0.4, ball_to=stop, carrier=s)
            self._tackle(presser, s, related=eid)
            return
        self.emit("carry", s, t, "complete", start=self.ball, end=target, under_pressure=under,
                  pressure_player=presser.p.id if presser and under else None,
                  extra={"length_m": round(length, 1)})
        self.advance(duration, ball_to=target, carrier=s)

    def do_dribble(self, defender: PlayerState) -> None:
        t, s = self.poss, self.carrier
        mom, _c, _p = self.mods(t)
        p = clamp(0.52 + (s.a("dribbling") - defender.a("tackling")) * 0.012 + mom * 0.05, 0.2, 0.85)
        ok = self.rng.random() < p
        eid = self.emit("take_on", s, t, "success" if ok else "fail", start=self.ball,
                        extra={"opponent_id": defender.p.id})
        self.advance(self.rng.uniform(0.6, 1.2), carrier=s)
        if ok:
            self.emit("dribbled_past", defender, self.other(t), related=eid, count_in_sequence=False)
            self.do_carry(after_dribble=True)
        else:
            self._tackle(defender, s, related=eid)

    def _tackle(self, defender: PlayerState, victim: PlayerState, related: str | None) -> None:
        t = self.poss
        opp = self.other(t)
        rx, ry = t.rel(*self.ball)
        foul_p = 0.12 + (0.08 if rx > 60 else 0) - (defender.a("tackling") - 70) * 0.003
        if rx > 88.5 and 13.84 < ry < 54.16:
            foul_p *= 0.15
        if self.rng.random() < foul_p:
            self._foul(defender, victim, related)
            return
        eid = self.emit("tackle", defender, opp, "won", start=self.ball, related=related,
                        extra={"opponent_id": victim.p.id})
        self.new_possession(opp, defender, "regain")
        defender.x, defender.y = self.ball

    def _foul(self, defender: PlayerState, victim: PlayerState, related: str | None,
              force_red: bool = False) -> None:
        t = self.poss  # fouled team
        opp = self.other(t)
        rx, ry = t.rel(*self.ball)
        in_box = rx > 88.5 and 13.84 < ry < 54.16
        eid = self.emit("foul", defender, opp, start=self.ball, related=related,
                        extra={"fouled_player_id": victim.p.id, "in_box": in_box},
                        count_in_sequence=False)
        card = None
        if force_red:
            card = "red"
        else:
            yp = 0.09 + (0.22 if rx > 55 and self.play_pattern == "regain" else 0) + (0.2 if in_box else 0)
            if defender.yellow:
                yp *= 0.3
            if self.rng.random() < yp:
                defender.yellow += 1
                card = "second_yellow" if defender.yellow >= 2 else "yellow"
            elif self.rng.random() < 0.006:
                card = "red"
        if card:
            self.emit("card", defender, opp, outcome=card, related=eid, count_in_sequence=False)
            if card in ("red", "second_yellow"):
                defender.on_pitch = False
        self.restart("penalty" if in_box else "free_kick", t, self.ball)

    def _forced_red(self) -> bool:
        for rc in list(self.pending_reds):
            if self.minute >= rc["minute"] and self.poss.id != rc["team"] and self.carrier is not None:
                team = self.home if self.home.id == rc["team"] else self.away
                cand = team.players.get(rc.get("player", ""))
                if cand is None or not cand.on_pitch or cand.is_gk:
                    cand = self.nearest(team, self.ball)
                self.pending_reds.remove(rc)
                # the offender closes in, then fouls
                self.advance(1.0, carrier=self.carrier, receiver=None)
                cand.x, cand.y = self.ball[0] + 0.8, self.ball[1]
                self._foul(cand, self.carrier, self.last_event_id, force_red=True)
                return True
        return False

    # ------------------------------------------------------------- crossing
    def do_cross(self, from_set_piece: bool = False, under: bool = False,
                 presser: PlayerState | None = None) -> None:
        t, s = self.poss, self.carrier
        opp = self.other(t)
        trx = self.rng.uniform(92, 101)
        try_ = self.rng.uniform(26, 42)
        target = t.abs(trx, try_)
        attackers = [c for c in t.outfield() if c is not s]
        attackers.sort(key=lambda c: dist(c.pos, target) - c.a("aerial") * 0.15)
        att = attackers[0] if attackers else s
        defs = sorted(opp.active(), key=lambda c: dist(c.pos, target))
        deff = defs[0]
        p = 0.20 + (att.a("aerial") - deff.a("aerial")) * 0.006 + (s.a("passing") - 70) * 0.003
        p += 0.04 if from_set_piece else 0
        p = clamp(p, 0.08, 0.5)
        ok = self.rng.random() < p
        length = dist(self.ball, target)
        quals = ["cross"] + (["set_piece"] if from_set_piece else [])
        extra = {"length_m": round(length, 1), "height": "high", "receiver_id": att.p.id,
                 "ball_speed_kmh": round(self.rng.uniform(55, 80), 1)}
        eid = self.emit("pass", s, t, "complete" if ok else "incomplete", start=self.ball, end=target,
                        body_part="right_foot" if s.p.foot == "right" else "left_foot", qualifiers=quals,
                        under_pressure=under, pressure_player=presser.p.id if presser and under else None,
                        extra=extra)
        self.advance(max(0.8, length / 19.0), ball_to=target, receiver=att if ok else deff, height=5.0)
        if ok:
            att.x, att.y = target
            self.carrier = att
            if self.rng.random() < 0.6:
                header = self.rng.random() < 0.7
                self.do_shot(header=header, assisted_by=eid)
            return
        if deff.is_gk:
            deff.x, deff.y = target
            self.emit("goalkeeper", deff, opp, "claim", start=target, related=eid)
            self.restart("keeper", opp, target)
            return
        self._clear_by(deff, opp, related=eid)

    def do_clearance(self, under: bool, presser: PlayerState | None) -> None:
        self._clear_by(self.carrier, self.poss, related=self.last_event_id, by_possessor=True)

    def _clear_by(self, s: PlayerState, team: TeamState, related: str | None, by_possessor: bool = False) -> None:
        rx, ry = team.rel(*self.ball)
        land = team.abs(clamp(rx + self.rng.uniform(25, 50), 30, 95), clamp(ry + self.rng.gauss(0, 15), 3, W - 3))
        eid = self.emit("clearance", s, team, start=self.ball, end=land, body_part="head" if self.ball_z > 1.5 else None,
                        related=related, count_in_sequence=by_possessor)
        if self.rng.random() < 0.3:
            # sliced into touch
            side = 0.0 if land[1] < W / 2 else W
            land = (land[0], side)
            self.advance(dist(self.ball, land) / 20.0, ball_to=land, height=8.0)
            self.emit("ball_out", None, team, related=eid, extra={"restart": "throw_in"}, count_in_sequence=False)
            self.restart("throw_in", self.other(team), land)
            return
        self.advance(dist(self.ball, land) / 20.0, ball_to=land, height=8.0)
        other = self.other(team)
        # contest the second ball
        a = self.nearest(team, land)
        b = self.nearest(other, land)
        da, db = dist(a.pos, land), dist(b.pos, land)
        winner, wteam = (a, team) if da + self.rng.gauss(0, 3) < db else (b, other)
        if self.rng.random() < 0.35:
            loser = b if winner is a else a
            self.emit("aerial_duel", winner, wteam, "won", start=land, extra={"opponent_id": loser.p.id},
                      count_in_sequence=False)
        winner.x, winner.y = land
        if wteam is not self.poss:
            self.new_possession(wteam, winner, "second_ball")
        else:
            self.carrier = winner
        self.emit("ball_recovery", winner, wteam, start=land, related=eid)

    # --------------------------------------------------------------- shooting
    def do_shot(self, under: bool = False, presser: PlayerState | None = None, header: bool = False,
                penalty: bool = False, direct_free_kick: bool = False, assisted_by: str | None = None) -> None:
        t, s = self.poss, self.carrier
        opp = self.other(t)
        rx, ry = t.rel(*self.ball)
        if penalty:
            xg = 0.76
        else:
            xg = shot_xg(rx, ry, header=header, under_pressure=under,
                         counter=self.play_pattern == "regain" and self.seq < 6)
            if direct_free_kick:
                xg = min(xg * 0.6, 0.12)
            else:
                # defenders between the ball and the goal mouth shrink the chance
                in_cone = 0
                for o in opp.active():
                    orx, ory = t.rel(o.x, o.y)
                    if orx > rx and abs(ory - (ry + (34 - ry) * (orx - rx) / max(1.0, 105 - rx))) < 3.0:
                        in_cone += 0 if o.is_gk else 1
                xg *= 0.72 ** min(in_cone, 4)
                xg = max(xg, 0.005)
        fin = s.a("finishing") if not header else (s.a("finishing") + s.a("aerial")) / 2
        gk = opp.gk()
        keep = gk.a("keeping") if gk else 40
        p_goal = clamp(xg * (1 + (fin - 75) * 0.01) * (1 - (keep - 80) * 0.008), 0.005, 0.95)
        blockers = [o for o in opp.outfield() if dist(o.pos, self.ball) < 6]
        p_block = 0.0 if (penalty or direct_free_kick or header or not blockers) else clamp(0.08 + 0.07 * len(blockers), 0, 0.4)
        shot_speed = (self.rng.uniform(55, 80) if header else self.rng.uniform(85, 125)) * (0.9 if under else 1.0)
        gx = L if t.dir == 1 else 0.0
        mouth_y = W / 2 + self.rng.uniform(-3.4, 3.4)
        goal_point = (gx, mouth_y)
        body = "head" if header else ("right_foot" if s.p.foot == "right" else "left_foot")
        quals = (["penalty"] if penalty else []) + (["free_kick"] if direct_free_kick else [])
        extra = {"xg": round(xg, 3), "shot_speed_kmh": round(shot_speed, 1),
                 "distance_m": round(math.hypot(L - rx, 34 - ry), 1)}
        if assisted_by:
            extra["assist_event_id"] = assisted_by
        r = self.rng.random()
        if r < p_block:
            blocker = min(blockers, key=lambda o: dist(o.pos, self.ball))
            eid = self.emit("shot", s, t, "blocked", start=self.ball, end=blocker.pos, body_part=body,
                            qualifiers=quals, under_pressure=under,
                            pressure_player=presser.p.id if presser and under else None, extra=extra)
            self.emit("block", blocker, opp, start=blocker.pos, related=eid, count_in_sequence=False)
            self.advance(0.4, ball_to=blocker.pos)
            if self.rng.random() < 0.3:
                self.restart("corner", t, self.ball)
            else:
                self._loose_ball(related=eid)
            return
        r = self.rng.random()
        travel = max(0.3, math.hypot(L - rx, 34 - ry) / (shot_speed / 3.6))
        if r < p_goal:
            extra["placement"] = {"y": round(mouth_y - W / 2, 2), "z": round(self.rng.uniform(0.1, 2.3), 2)}
            eid = self.emit("shot", s, t, "goal", start=self.ball, end=goal_point, body_part=body,
                            qualifiers=quals, under_pressure=under,
                            pressure_player=presser.p.id if presser and under else None, extra=extra)
            self.advance(travel, ball_to=goal_point, height=1.0, chase=False)
            t.score += 1
            self.emit("goal", s, t, related=eid, extra={"score": {self.home.id: self.home.score, self.away.id: self.away.score}},
                      count_in_sequence=False)
            self.dead_ball(self.rng.uniform(45, 75))
            self._maybe_substitutions()
            self._place_for_kickoff()
            self.restart_kickoff(opp)
            return
        p_on = clamp(0.36 + (fin - 70) * 0.006 + xg * 0.5, 0.15, 0.8)
        if self.rng.random() < p_on and gk:
            extra["placement"] = {"y": round(mouth_y - W / 2, 2), "z": round(self.rng.uniform(0.1, 2.3), 2)}
            eid = self.emit("shot", s, t, "saved", start=self.ball, end=goal_point, body_part=body,
                            qualifiers=quals, under_pressure=under,
                            pressure_player=presser.p.id if presser and under else None, extra=extra)
            self.advance(travel, ball_to=goal_point, height=1.0, chase=False)
            self.emit("goalkeeper", gk, opp, "save", start=goal_point, related=eid, count_in_sequence=False)
            r2 = self.rng.random()
            if r2 < 0.5:
                self.restart("keeper", opp, goal_point)
            elif r2 < 0.8:
                self.restart("corner", t, goal_point)
            else:
                self._loose_ball(related=eid, near=t.abs(97, 34 + self.rng.uniform(-10, 10)))
            return
        wide_point = (gx, W / 2 + self.rng.choice([-1, 1]) * self.rng.uniform(4.2, 12))
        eid = self.emit("shot", s, t, "off_target", start=self.ball, end=wide_point, body_part=body,
                        qualifiers=quals, under_pressure=under,
                        pressure_player=presser.p.id if presser and under else None, extra=extra)
        self.advance(travel, ball_to=wide_point, height=2.0, chase=False)
        self.restart("goal_kick", opp, wide_point)

    def _loose_ball(self, related: str | None, near: tuple[float, float] | None = None) -> None:
        pt = near or (clamp(self.ball[0] + self.rng.gauss(0, 6), 1, L - 1), clamp(self.ball[1] + self.rng.gauss(0, 6), 1, W - 1))
        self.advance(0.8, ball_to=pt, chase=False)
        a = self.nearest(self.home, pt, outfield=False)
        b = self.nearest(self.away, pt, outfield=False)
        winner, wteam = (a, self.home) if dist(a.pos, pt) + self.rng.gauss(0, 2) < dist(b.pos, pt) else (b, self.away)
        winner.x, winner.y = pt
        if wteam is not self.poss:
            self.new_possession(wteam, winner, "second_ball")
        else:
            self.carrier = winner
        self.emit("ball_recovery", winner, wteam, start=pt, related=related)


def simulate(world: World, seed: int = 1, script: Script | None = None, tracking_hz: float = 1.0,
             match_id: str = "m_0001") -> MatchEngine:
    eng = MatchEngine(world, seed=seed, script=script, tracking_hz=tracking_hz, match_id=match_id)
    # standout boosts need the script in place before team states are built
    for t in (eng.home, eng.away):
        for pid, ps in t.players.items():
            ps.boost = eng.script.standouts.get(pid, 0)
    eng.run()
    return eng
