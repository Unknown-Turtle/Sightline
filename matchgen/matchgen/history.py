"""Fictional league history for commentator trivia.

Builds a 20-club league (Arden Athletic and Hollow Vale included, same ids and
names as the match world), five past seasons of double round-robin fixtures
with dates, and derived tables: results, standings, head to head, club
records, player careers, a scoring timeline and upcoming milestones. See
HISTORY.md for every table and column.

Scores come from a fast seeded Poisson-style goal model driven by club
strength and home advantage (about 2.8 goals a match and a 45 / 25 / 30 home,
draw, away split), not from the match engine. Everything is deterministic per
seed and everything is fictional.
"""
from __future__ import annotations

import csv
import datetime as dt
import json
import math
import os
import random
from dataclasses import asdict, dataclass, field

from .world import World, pick_name

SEASONS = [2021, 2022, 2023, 2024, 2025]          # start years: 2021-22 to 2025-26
CURRENT_SEASON_END = 2027                        # the simulated match belongs to 2026-27
HOME_ADV = 1.13
BASE_GOALS = 1.34                                # per team per match before home advantage
STRENGTH_K = 0.025                               # goal rate multiplier per strength point
RED_CARD_RATE = 0.065                            # per team per match

# id, name, short, city, stadium, founded, capacity, strength
_CLUBS = [
    ("ARD", "Arden Athletic", "Arden", "Arden", "Arden Park", 1898, 31400, 76),
    ("HVL", "Hollow Vale", "Hollow Vale", "Hollow Vale", "The Hollow", 1904, 26800, 74),
    ("KSB", "Kestrel Bay", "Kestrel Bay", "Kestrel Bay", "Harbour Ground", 1887, 42000, 82),
    ("THB", "Thornbridge United", "Thornbridge", "Thornbridge", "Bridge Road", 1892, 38500, 80),
    ("MRM", "Marrowmere Town", "Marrowmere", "Marrowmere", "Mere Lane", 1909, 24000, 70),
    ("SWK", "Saltwick Rovers", "Saltwick", "Saltwick", "Saltwick Stadium", 1901, 22500, 67),
    ("EGA", "Eastgate Albion", "Eastgate", "Eastgate", "The Gatehouse", 1885, 35200, 78),
    ("WRF", "Wrenfield City", "Wrenfield", "Wrenfield", "Wrenfield Park", 1911, 29600, 72),
    ("GGW", "Gallowgate Wanderers", "Gallowgate", "Gallowgate", "Hilltop", 1879, 33000, 75),
    ("ASH", "Ashcombe", "Ashcombe", "Ashcombe", "Combe Lane", 1920, 18900, 63),
    ("BMA", "Blackmoor Athletic", "Blackmoor", "Blackmoor", "Moor End", 1896, 27200, 71),
    ("CRH", "Carrow Heath", "Carrow Heath", "Carrow", "Heath Park", 1908, 21000, 66),
    ("DNC", "Dunholm County", "Dunholm", "Dunholm", "County Ground", 1890, 25500, 69),
    ("FWR", "Fenwick Rangers", "Fenwick", "Fenwick", "Fen Road", 1915, 19800, 64),
    ("GHU", "Greyhaven United", "Greyhaven", "Greyhaven", "Haven Field", 1883, 40100, 81),
    ("IRB", "Ironbridge", "Ironbridge", "Ironbridge", "Foundry Park", 1899, 23700, 68),
    ("LKT", "Larkspur Town", "Larkspur", "Larkspur", "Meadow Lane", 1923, 17600, 62),
    ("MCR", "Moorcroft", "Moorcroft", "Moorcroft", "Croft Road", 1902, 20400, 65),
    ("PNC", "Pennycross", "Pennycross", "Pennycross", "Cross Street", 1906, 22100, 66),
    ("SBH", "Stonebrook Harriers", "Stonebrook", "Stonebrook", "Brook Park", 1894, 30300, 73),
]
_POS_BY_SLOT = ["GK", "RB", "CB", "CB", "LB", "DM", "CM", "CM", "RW", "ST", "LW",
                "GK", "CB", "FB", "CM", "CM", "AM", "W", "ST"]
_GROUP = {"GK": "GK", "RB": "DEF", "CB": "DEF", "LB": "DEF", "FB": "DEF", "RCB": "DEF", "LCB": "DEF",
          "RWB": "DEF", "LWB": "DEF", "DM": "MID", "CM": "MID", "AM": "MID", "CDM": "MID", "RCM": "MID",
          "LCM": "MID", "RDM": "MID", "LDM": "MID", "RAM": "MID", "LAM": "MID", "CAM": "MID",
          "RW": "FWD", "LW": "FWD", "W": "FWD", "ST": "FWD"}
_SCORING = {"GK": 0.01, "DEF": 0.12, "MID": 0.35, "FWD": 1.0}
_SCORING_POS = {"ST": 1.9, "RW": 0.9, "LW": 0.9, "W": 0.9, "AM": 0.75, "CAM": 0.75, "RAM": 0.7, "LAM": 0.7,
                "CM": 0.35, "RCM": 0.35, "LCM": 0.35, "DM": 0.18, "CDM": 0.18, "RDM": 0.18, "LDM": 0.18}
_ASSISTING = {"GK": 0.03, "DEF": 0.45, "MID": 1.0, "FWD": 0.8}
LINEUP_SIZE = 14                                 # players used per match (starters plus three subs)
FILLERS = 12                                     # generated squad members for Arden and Hollow Vale


def scoring_weight(position: str, group: str) -> float:
    return _SCORING_POS.get(position, _SCORING[group])


@dataclass
class Club:
    id: str
    name: str
    short_name: str
    city: str
    stadium: str
    founded: int
    capacity: int
    strength: float


@dataclass
class HistPlayer:
    id: str
    name: str
    position: str
    group: str
    born: int                 # year of birth
    debut_season: int         # first season start year with a professional contract
    scoring: float            # relative goal-scoring talent
    assisting: float
    starter: float            # probability of playing a given match when at the club
    clubs: dict[int, str] = field(default_factory=dict)   # season start year -> club id
    current: bool = False     # a member of the current ARD or HVL squad


def poisson(rng: random.Random, lam: float) -> int:
    """Knuth's method, deterministic for a seeded rng."""
    limit = math.exp(-lam)
    k, p = 0, rng.random()
    while p > limit:
        k += 1
        p *= rng.random()
    return k


def season_label(start: int) -> str:
    return f"{start}-{(start + 1) % 100:02d}"


def round_robin(ids: list[str]) -> list[list[tuple[str, str]]]:
    """38 matchdays of (home, away) pairs for an even number of clubs (circle method, then reversed)."""
    n = len(ids)
    rot = list(ids)
    first_half = []
    for r in range(n - 1):
        pairs = []
        for i in range(n // 2):
            a, b = rot[i], rot[n - 1 - i]
            pairs.append((a, b) if (r + i) % 2 == 0 else (b, a))
        first_half.append(pairs)
        rot = [rot[0]] + [rot[-1]] + rot[1:-1]
    second_half = [[(b, a) for a, b in md] for md in first_half]
    return first_half + second_half


def matchday_dates(start_year: int) -> list[dt.date]:
    """Saturdays from the second Saturday of August, weekly, with three two-week breaks."""
    d = dt.date(start_year, 8, 1)
    while d.weekday() != 5:
        d += dt.timedelta(days=1)
    d += dt.timedelta(days=7)
    dates = []
    for md in range(1, 39):
        dates.append(d)
        d += dt.timedelta(days=14 if md in (4, 8, 12) else 7)
    return dates


class HistoryBuilder:
    def __init__(self, seed: int, world: World | None = None):
        self.seed = seed
        self.rng = random.Random(seed)
        self.world = world
        self.clubs = [Club(*c) for c in _CLUBS]
        self.club_by_id = {c.id: c for c in self.clubs}
        self.players: dict[str, HistPlayer] = {}
        self.used_names: set[str] = set()
        self.results: list[dict] = []
        self.strength: dict[int, dict[str, float]] = {}

    # ------------------------------------------------------------- squads
    def _gen_player(self, club_id: str, idx: int, pos: str, season: int, quality: float) -> HistPlayer:
        rng = self.rng
        group = _GROUP[pos]
        born = season - rng.randint(18, 33)
        pid = f"{club_id}_H{idx:02d}"
        p = HistPlayer(id=pid, name=pick_name(rng, self.used_names), position=pos, group=group, born=born,
                       debut_season=min(season, born + rng.randint(17, 20)),
                       scoring=scoring_weight(pos, group) * rng.uniform(0.6, 1.5) * (quality / 70) ** 2,
                       assisting=_ASSISTING[group] * rng.uniform(0.6, 1.4),
                       starter=3.0 if idx < 11 else 1.0)
        self.players[pid] = p
        return p

    def build_squads(self) -> dict[int, dict[str, list[str]]]:
        """Season squads: {season: {club_id: [player_id, ...]}} with continuity across seasons."""
        rng = self.rng
        squads: dict[int, dict[str, list[str]]] = {s: {} for s in SEASONS}
        current_ids: set[str] = set()
        if self.world is not None:
            for team in (self.world.home, self.world.away):
                for wp in team.players:
                    group = wp.group
                    born = CURRENT_SEASON_END - 1 - wp.age
                    debut = born + rng.randint(17, 20)
                    hp = HistPlayer(id=wp.id, name=wp.name, position=wp.position, group=group, born=born,
                                    debut_season=debut,
                                    scoring=scoring_weight(wp.position, group) * (wp.finishing / 70) ** 2 * rng.uniform(0.8, 1.2),
                                    assisting=_ASSISTING[group] * (wp.passing / 70) * rng.uniform(0.8, 1.2),
                                    starter=3.0 if wp.id in team.starting_xi else 1.0, current=True)
                    self.used_names.add(wp.name)
                    # career: joined the current club in some season; before that another club or youth
                    joined = rng.choice([2019, 2020, 2021, 2022, 2023, 2024, 2025, 2026])
                    joined = max(joined, debut)
                    previous = rng.choice([c.id for c in self.clubs if c.id != team.id]) if rng.random() < 0.7 else None
                    for s in SEASONS:
                        if s < debut:
                            continue
                        if s >= joined:
                            hp.clubs[s] = team.id
                        elif previous is not None:
                            hp.clubs[s] = previous
                    self.players[wp.id] = hp
                    current_ids.add(wp.id)
        for club in self.clubs:
            slots = _POS_BY_SLOT if club.id not in ("ARD", "HVL") or self.world is None else _POS_BY_SLOT[:FILLERS]
            base = [self._gen_player(club.id, i, pos, SEASONS[0], club.strength) for i, pos in enumerate(slots)]
            if len(slots) < len(_POS_BY_SLOT):
                for p in base:
                    p.starter = 1.2   # fillers around the real squad
            extra_idx = len(_POS_BY_SLOT)
            roster = list(base)
            for s in SEASONS:
                # churn: two or three generated players leave and are replaced each season
                if s != SEASONS[0]:
                    leaving = rng.sample(range(len(roster)), rng.choice([2, 3]))
                    for li in leaving:
                        old = roster[li]
                        roster[li] = self._gen_player(club.id, extra_idx, old.position, s, club.strength)
                        extra_idx += 1
                for p in roster:
                    if s >= p.debut_season:
                        p.clubs[s] = club.id
                squads[s][club.id] = [p.id for p in roster if s in p.clubs]
        for pid in sorted(current_ids):
            hp = self.players[pid]
            for s, cid in hp.clubs.items():
                squads[s][cid].append(pid)
        return squads

    # ------------------------------------------------------------ matches
    def season_strengths(self) -> None:
        rng = self.rng
        for i, s in enumerate(SEASONS):
            self.strength[s] = {}
            for c in self.clubs:
                drift = sum(rng.gauss(0, 2.0) for _ in range(i + 1))
                self.strength[s][c.id] = c.strength + drift

    def play_match(self, season: int, matchday: int, date: dt.date, home: str, away: str,
                   squads: dict[str, list[str]]) -> dict:
        rng = self.rng
        sh, sa = self.strength[season][home], self.strength[season][away]
        lam_h = BASE_GOALS * HOME_ADV * math.exp(STRENGTH_K * (sh - sa))
        lam_a = BASE_GOALS / HOME_ADV * math.exp(STRENGTH_K * (sa - sh))
        gh, ga = poisson(rng, lam_h), poisson(rng, lam_a)
        goals = []
        lineups = {}
        for side, cid, n in (("home", home, gh), ("away", away, ga)):
            squad = squads[cid]
            # weighted sample without replacement: the 14 players used on the day
            keyed = sorted(((rng.random() ** (1.0 / self.players[pid].starter), pid) for pid in squad), reverse=True)
            playing = sorted(pid for _k, pid in keyed[:LINEUP_SIZE])
            lineups[cid] = playing
            weights = [self.players[pid].scoring for pid in playing]
            aweights = [self.players[pid].assisting for pid in playing]
            for _ in range(n):
                minute = self._goal_minute()
                scorer = rng.choices(playing, weights=weights)[0]
                assister = None
                if rng.random() < 0.82:
                    others = [(p, w) for p, w in zip(playing, aweights) if p != scorer]
                    assister = rng.choices([p for p, _ in others], weights=[w for _, w in others])[0]
                goals.append({"minute": minute, "side": side, "team_id": cid, "scorer_id": scorer,
                              "assist_id": assister})
        goals.sort(key=lambda g: (g["minute"], g["side"]))
        reds = []
        for side, cid in (("home", home), ("away", away)):
            if rng.random() < RED_CARD_RATE:
                reds.append({"side": side, "team_id": cid, "player_id": rng.choice(lineups[cid]),
                             "minute": rng.randint(20, 90)})
        cap = self.club_by_id[home].capacity
        interest = 0.78 + 0.1 * (sa > 76) + 0.06 * (away in ("ARD", "HVL") and home in ("ARD", "HVL"))
        attendance = min(cap, int(cap * min(1.0, rng.uniform(interest - 0.1, interest + 0.14))))
        ht_h = sum(1 for g in goals if g["side"] == "home" and g["minute"] <= 45)
        ht_a = sum(1 for g in goals if g["side"] == "away" and g["minute"] <= 45)
        score = {home: 0, away: 0}
        for g in goals:
            score[g["team_id"]] += 1
            g["score_after"] = f"{score[home]}-{score[away]}"
        return {
            "match_id": f"h_{season}_{matchday:02d}_{home}_{away}",
            "season": season_label(season),
            "season_start": season,
            "matchday": matchday,
            "date": date.isoformat(),
            "home_id": home,
            "away_id": away,
            "home_goals": gh,
            "away_goals": ga,
            "ht_home_goals": ht_h,
            "ht_away_goals": ht_a,
            "first_scorer_side": goals[0]["side"] if goals else "none",
            "attendance": attendance,
            "goals": goals,
            "red_cards": reds,
            "lineups": lineups,
        }

    def _goal_minute(self) -> int:
        r = self.rng.random()
        if r < 0.44:
            return self.rng.randint(1, 45)
        if r < 0.96:
            return self.rng.randint(46, 90)
        return self.rng.randint(91, 96)

    def build(self) -> "History":
        squads = self.build_squads()
        self.season_strengths()
        order = [c.id for c in self.clubs]
        for s in SEASONS:
            ids = list(order)
            self.rng.shuffle(ids)
            dates = matchday_dates(s)
            for md, pairs in enumerate(round_robin(ids), start=1):
                for i, (h, a) in enumerate(pairs):
                    offset = -1 if i == 0 else (1 if i >= 7 else 0)   # one Friday, three Sunday games
                    date = dates[md - 1] + dt.timedelta(days=offset)
                    self.results.append(self.play_match(s, md, date, h, a, squads[s]))
        self.results.sort(key=lambda r: (r["date"], r["match_id"]))
        return History(self.clubs, self.players, self.results, squads, self.seed)


class History:
    """Derived tables over a set of historical results."""

    def __init__(self, clubs: list[Club], players: dict[str, HistPlayer], results: list[dict],
                 squads: dict[int, dict[str, list[str]]], seed: int):
        self.clubs = clubs
        self.players = players
        self.results = results
        self.squads = squads
        self.seed = seed

    # ---------------------------------------------------------- tables
    def clubs_table(self) -> list[dict]:
        return [asdict(c) for c in self.clubs]

    def results_table(self) -> list[dict]:
        rows = []
        for r in self.results:
            row = {k: v for k, v in r.items() if k not in ("goals", "red_cards", "lineups")}
            row["home_red_cards"] = sum(1 for x in r["red_cards"] if x["side"] == "home")
            row["away_red_cards"] = sum(1 for x in r["red_cards"] if x["side"] == "away")
            row["goal_minutes"] = ";".join(f"{g['minute']}:{g['scorer_id']}" for g in r["goals"])
            rows.append(row)
        return rows

    def standings(self) -> list[dict]:
        rows = []
        for s in SEASONS:
            table = {c.id: {"played": 0, "won": 0, "drawn": 0, "lost": 0, "gf": 0, "ga": 0, "points": 0}
                     for c in self.clubs}
            for r in self.results:
                if r["season_start"] != s:
                    continue
                h, a, gh, ga = r["home_id"], r["away_id"], r["home_goals"], r["away_goals"]
                for cid, f, g in ((h, gh, ga), (a, ga, gh)):
                    t = table[cid]
                    t["played"] += 1
                    t["gf"] += f
                    t["ga"] += g
                    if f > g:
                        t["won"] += 1
                        t["points"] += 3
                    elif f == g:
                        t["drawn"] += 1
                        t["points"] += 1
                    else:
                        t["lost"] += 1
            order = sorted(table, key=lambda c: (-table[c]["points"], -(table[c]["gf"] - table[c]["ga"]),
                                                 -table[c]["gf"], c))
            for pos, cid in enumerate(order, start=1):
                t = table[cid]
                rows.append({"season": season_label(s), "position": pos, "club_id": cid, **t,
                             "gd": t["gf"] - t["ga"]})
        return rows

    def head_to_head(self) -> list[dict]:
        ids = [c.id for c in self.clubs]
        rows = []
        for i, a in enumerate(ids):
            for b in ids[i + 1:]:
                ms = [r for r in self.results if {r["home_id"], r["away_id"]} == {a, b}]
                aw = dw = bw = ag = bg = 0
                for r in ms:
                    ga_ = r["home_goals"] if r["home_id"] == a else r["away_goals"]
                    gb_ = r["away_goals"] if r["home_id"] == a else r["home_goals"]
                    ag += ga_
                    bg += gb_
                    if ga_ > gb_:
                        aw += 1
                    elif ga_ == gb_:
                        dw += 1
                    else:
                        bw += 1
                last = ms[-1] if ms else None
                rows.append({"club_a": a, "club_b": b, "played": len(ms), "a_wins": aw, "draws": dw,
                             "b_wins": bw, "a_goals": ag, "b_goals": bg,
                             "last_meeting_date": last["date"] if last else None,
                             "last_meeting": (f"{last['home_id']} {last['home_goals']}-{last['away_goals']} "
                                              f"{last['away_id']}") if last else None})
        return rows

    def club_records(self) -> list[dict]:
        rows = []
        careers = self.player_careers()
        for c in self.clubs:
            cid = c.id
            ms = [r for r in self.results if cid in (r["home_id"], r["away_id"])]
            best_win = best_loss = None
            best_margin, worst_margin = -1, -1
            streak = unbeaten = best_streak = best_unbeaten = 0
            for r in ms:
                f = r["home_goals"] if r["home_id"] == cid else r["away_goals"]
                g = r["away_goals"] if r["home_id"] == cid else r["home_goals"]
                if f - g > best_margin:
                    best_margin, best_win = f - g, r
                if g - f > worst_margin:
                    worst_margin, best_loss = g - f, r
                streak = streak + 1 if f > g else 0
                unbeaten = unbeaten + 1 if f >= g else 0
                best_streak = max(best_streak, streak)
                best_unbeaten = max(best_unbeaten, unbeaten)
            home_att = max((r for r in ms if r["home_id"] == cid), key=lambda r: (r["attendance"], r["date"]))
            goals_for = {}
            for row in careers:
                if row["club_id"] == cid:
                    goals_for[row["player_id"]] = goals_for.get(row["player_id"], 0) + row["goals"]
            top = max(sorted(goals_for), key=lambda p: goals_for[p]) if goals_for else None
            seasons = [r for r in self.standings() if r["club_id"] == cid]
            best_season = min(seasons, key=lambda r: (r["position"], -r["points"]))
            most_points = max(seasons, key=lambda r: (r["points"], r["season"]))

            def desc(r):
                return f"{r['date']} {r['home_id']} {r['home_goals']}-{r['away_goals']} {r['away_id']}"
            rows += [
                {"club_id": cid, "record": "biggest_win", "value": best_margin, "detail": desc(best_win)},
                {"club_id": cid, "record": "biggest_defeat", "value": worst_margin, "detail": desc(best_loss)},
                {"club_id": cid, "record": "longest_winning_streak", "value": best_streak, "detail": "league matches"},
                {"club_id": cid, "record": "longest_unbeaten_run", "value": best_unbeaten, "detail": "league matches"},
                {"club_id": cid, "record": "record_scorer", "value": goals_for.get(top, 0),
                 "detail": f"{top} {self.players[top].name}" if top else ""},
                {"club_id": cid, "record": "record_home_attendance", "value": home_att["attendance"], "detail": desc(home_att)},
                {"club_id": cid, "record": "most_points_in_a_season", "value": most_points["points"], "detail": most_points["season"]},
                {"club_id": cid, "record": "highest_finish", "value": best_season["position"], "detail": best_season["season"]},
            ]
        return rows

    def player_careers(self) -> list[dict]:
        if hasattr(self, "_careers"):
            return self._careers
        apps: dict[tuple[str, int, str], int] = {}
        goals: dict[tuple[str, int, str], int] = {}
        assists: dict[tuple[str, int, str], int] = {}
        for r in self.results:
            s = r["season_start"]
            for cid, pids in r["lineups"].items():
                for pid in pids:
                    apps[(pid, s, cid)] = apps.get((pid, s, cid), 0) + 1
            for g in r["goals"]:
                k = (g["scorer_id"], s, g["team_id"])
                goals[k] = goals.get(k, 0) + 1
                if g["assist_id"]:
                    k2 = (g["assist_id"], s, g["team_id"])
                    assists[k2] = assists.get(k2, 0) + 1
        rows = []
        for pid in sorted(self.players):
            p = self.players[pid]
            for s in SEASONS:
                cid = p.clubs.get(s)
                if cid is None:
                    continue
                k = (pid, s, cid)
                rows.append({"player_id": pid, "name": p.name, "position": p.position, "season": season_label(s),
                             "club_id": cid, "age": s - p.born, "apps": apps.get(k, 0), "goals": goals.get(k, 0),
                             "assists": assists.get(k, 0), "current_squad": p.current})
        self._careers = rows
        return rows

    def scoring_timeline(self) -> list[dict]:
        rows = []
        for r in self.results:
            for g in r["goals"]:
                rows.append({"match_id": r["match_id"], "season": r["season"], "date": r["date"],
                             "matchday": r["matchday"], "home_id": r["home_id"], "away_id": r["away_id"],
                             "minute": g["minute"], "side": g["side"], "team_id": g["team_id"],
                             "scorer_id": g["scorer_id"], "assist_id": g["assist_id"],
                             "score_after": g["score_after"]})
        return rows

    def milestones_upcoming(self) -> list[dict]:
        """Current players within reach of a round-number career total (league matches only)."""
        totals: dict[str, dict[str, int]] = {}
        for row in self.player_careers():
            t = totals.setdefault(row["player_id"], {"apps": 0, "goals": 0, "assists": 0})
            for k in ("apps", "goals", "assists"):
                t[k] += row[k]
        rows = []
        for pid in sorted(totals):
            p = self.players[pid]
            if not p.current:
                continue
            for metric, step, reach in (("apps", 50, 5), ("goals", 10, 3), ("assists", 10, 3)):
                cur = totals[pid][metric]
                nxt = (cur // step + 1) * step
                if nxt - cur <= reach and cur > 0:
                    rows.append({"player_id": pid, "name": p.name, "club_id": p.clubs.get(SEASONS[-1]),
                                 "metric": metric, "current": cur, "milestone": nxt, "remaining": nxt - cur})
        return rows

    # ----------------------------------------------------------- output
    def tables(self) -> dict[str, list[dict]]:
        return {
            "clubs": self.clubs_table(),
            "results": self.results_table(),
            "standings": self.standings(),
            "head_to_head": self.head_to_head(),
            "club_records": self.club_records(),
            "player_careers": self.player_careers(),
            "scoring_timeline": self.scoring_timeline(),
            "milestones_upcoming": self.milestones_upcoming(),
        }

    def write(self, out_dir: str) -> dict[str, int]:
        os.makedirs(out_dir, exist_ok=True)
        counts = {}
        for name, rows in self.tables().items():
            counts[name] = len(rows)
            with open(os.path.join(out_dir, f"{name}.jsonl"), "w") as f:
                for row in rows:
                    f.write(json.dumps(row, separators=(",", ":")) + "\n")
            with open(os.path.join(out_dir, f"{name}.csv"), "w", newline="") as f:
                if rows:
                    w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
                    w.writeheader()
                    w.writerows(rows)
        # the full match records (goals, red cards, lineups) for anything the tables do not answer
        with open(os.path.join(out_dir, "matches.jsonl"), "w") as f:
            for r in self.results:
                f.write(json.dumps(r, separators=(",", ":")) + "\n")
        counts["matches"] = len(self.results)
        with open(os.path.join(out_dir, "manifest.json"), "w") as f:
            json.dump({"seed": self.seed, "seasons": [season_label(s) for s in SEASONS],
                       "clubs": len(self.clubs), "tables": counts, "note": "All clubs, players and results are fictional."},
                      f, indent=2)
        return counts


def build_history(seed: int, world: World | None = None) -> History:
    return HistoryBuilder(seed, world).build()
