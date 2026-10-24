"""Fictional football world: clubs, players, formations.

Everything here is invented. Formations are expressed as anchor points in a
team-relative frame: x = 0 is the team's own goal line, x = 105 the opponent's,
y = 0 the team's right touchline, y = 68 its left.
"""
from __future__ import annotations

import json
import random
from dataclasses import asdict, dataclass, field

PITCH_LENGTH = 105.0
PITCH_WIDTH = 68.0

# role, anchor_x, anchor_y, group
FORMATIONS: dict[str, list[tuple[str, float, float, str]]] = {
    "4-3-3": [
        ("GK", 5, 34, "GK"),
        ("RB", 30, 8, "DEF"),
        ("RCB", 23, 24, "DEF"),
        ("LCB", 23, 44, "DEF"),
        ("LB", 30, 60, "DEF"),
        ("CDM", 38, 34, "MID"),
        ("RCM", 48, 22, "MID"),
        ("LCM", 48, 46, "MID"),
        ("RW", 64, 9, "FWD"),
        ("ST", 70, 34, "FWD"),
        ("LW", 64, 59, "FWD"),
    ],
    "3-4-2-1": [
        ("GK", 5, 34, "GK"),
        ("RCB", 23, 18, "DEF"),
        ("CB", 21, 34, "DEF"),
        ("LCB", 23, 50, "DEF"),
        ("RWB", 42, 6, "DEF"),
        ("RDM", 38, 26, "MID"),
        ("LDM", 38, 42, "MID"),
        ("LWB", 42, 62, "DEF"),
        ("RAM", 58, 24, "MID"),
        ("LAM", 58, 44, "MID"),
        ("ST", 70, 34, "FWD"),
    ],
    "4-2-3-1": [
        ("GK", 5, 34, "GK"),
        ("RB", 30, 8, "DEF"),
        ("RCB", 23, 24, "DEF"),
        ("LCB", 23, 44, "DEF"),
        ("LB", 30, 60, "DEF"),
        ("RDM", 38, 26, "MID"),
        ("LDM", 38, 42, "MID"),
        ("RAM", 58, 12, "MID"),
        ("CAM", 58, 34, "MID"),
        ("LAM", 58, 56, "MID"),
        ("ST", 70, 34, "FWD"),
    ],
}

# attribute emphasis per group: (pace, passing, dribbling, finishing, tackling, pressing, aerial, keeping)
_GROUP_BIAS = {
    "GK": (45, 55, 30, 20, 25, 30, 60, 75),
    "DEF": (68, 62, 50, 35, 74, 66, 72, 10),
    "MID": (68, 74, 66, 55, 62, 70, 58, 10),
    "FWD": (78, 64, 74, 74, 38, 64, 62, 10),
}
_ATTRS = ("pace", "passing", "dribbling", "finishing", "tackling", "pressing", "aerial", "keeping")

_FIRST = [
    "Tomas", "Elias", "Kofi", "Mateo", "Rhys", "Jonah", "Idris", "Lukas", "Ravi", "Callum",
    "Nils", "Dario", "Femi", "Owen", "Sami", "Arlo", "Teodor", "Kian", "Bruno", "Ezra",
    "Malik", "Joaquin", "Finn", "Yusuf", "Leon", "Caspar", "Ade", "Marek", "Hugo", "Isak",
    "Reuben", "Tariq", "Emil", "Santi", "Jude", "Oskar", "Niko", "Ellis", "Ayo", "Viktor",
]
_LAST = [
    "Marlowe", "Okafor", "Brannigan", "Vescovi", "Thorne", "Adeyemi-Lowe", "Kestrel", "Halloran",
    "Dunmore", "Castellan", "Rowntree", "Ibekwe", "Saltash", "Varga", "Penhallow", "Moreau",
    "Ashdown", "Quarrie", "Lindqvist", "Fairhurst", "Oduya", "Rennick", "Calloway", "Strand",
    "Wexley", "Amadi", "Harrowgate", "Novak", "Pelletier", "Garrow", "Mbeki-Shaw", "Tolland",
    "Brisco", "Delacroix", "Hendry", "Kowal", "Sorensen", "Achterberg", "Mabry", "Falconer",
    "Ostrowski", "Bellamy", "Nakamura-Reid", "Carrick", "Egwu", "Tremblay", "Vasquez", "Lindgren",
    "Oyelaran", "Pembrook", "Steinmetz", "Abara", "Wilde", "Montenegro", "Haugen", "Keane",
    "Ferrante", "Obuya", "Rasmussen", "Delgado", "Whitlock", "Nwosu", "Bergstrom", "Cavanagh",
    "Takeda", "Larkin", "Mensah", "Pires", "Aldana", "Rutherford", "Sokolov", "Byrne",
]
_NATIONS = ["England", "Scotland", "Wales", "Ireland", "France", "Spain", "Portugal", "Netherlands",
            "Germany", "Denmark", "Sweden", "Norway", "Brazil", "Argentina", "Nigeria", "Ghana",
            "Senegal", "Ivory Coast", "Japan", "Korea Republic", "USA", "Belgium", "Poland", "Serbia"]


@dataclass
class Player:
    id: str
    name: str
    number: int
    position: str
    group: str
    foot: str
    age: int
    nationality: str
    pace: int
    passing: int
    dribbling: int
    finishing: int
    tackling: int
    pressing: int
    aerial: int
    keeping: int
    stamina: int

    def attr(self, name: str) -> int:
        return getattr(self, name)


@dataclass
class Team:
    id: str
    name: str
    short_name: str
    colour: str
    formation: str
    style: dict  # directness, press, control in [0, 1]
    players: list[Player] = field(default_factory=list)
    starting_xi: list[str] = field(default_factory=list)  # ids in formation slot order
    bench: list[str] = field(default_factory=list)

    def player(self, pid: str) -> Player:
        for p in self.players:
            if p.id == pid:
                return p
        raise KeyError(pid)


@dataclass
class World:
    competition: str
    venue: str
    home: Team
    away: Team
    venue_capacity: int = 31400
    # optional overrides for the seeded match context (referee, weather, attendance,
    # kickoff_local, matchday, stakes); see engine.build_context
    context: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(d: dict) -> "World":
        def team(td: dict) -> Team:
            players = [Player(**p) for p in td.pop("players")]
            return Team(players=players, **td)
        return World(competition=d["competition"], venue=d["venue"],
                     home=team(dict(d["home"])), away=team(dict(d["away"])),
                     venue_capacity=int(d.get("venue_capacity", 31400)),
                     context=dict(d.get("context", {})))

    @staticmethod
    def load(path: str) -> "World":
        with open(path) as f:
            return World.from_dict(json.load(f))


def pick_name(rng: random.Random, used_names: set[str], used_surnames: set[str] | None = None) -> str:
    """A seeded fictional name. Surnames are unique while any remain unused, full names always are."""
    if used_surnames is None:
        used_surnames = {n.split(" ", 1)[1] for n in used_names}
    free = [n for n in _LAST if n not in used_surnames]
    pool = free or _LAST
    for _ in range(200):
        name = f"{rng.choice(_FIRST)} {rng.choice(pool)}"
        if name not in used_names:
            break
    else:  # pragma: no cover - 40 x 80 names, only reachable with thousands of players
        name = f"{rng.choice(_FIRST)} {rng.choice(_LAST)} {len(used_names) + 1}"
    used_names.add(name)
    used_surnames.add(name.split(" ", 1)[1])
    return name


def _make_player(rng: random.Random, team_id: str, number: int, role: str, group: str,
                 quality: int, used_names: set[str]) -> Player:
    name = pick_name(rng, used_names)
    bias = _GROUP_BIAS[group]
    vals = {}
    for a, b in zip(_ATTRS, bias):
        v = b + (quality - 70) + rng.gauss(0, 7)
        vals[a] = int(max(15, min(97, round(v))))
    if group != "GK":
        vals["keeping"] = rng.randint(5, 15)
    return Player(
        id=f"{team_id}_{number:02d}",
        name=name,
        number=number,
        position=role,
        group=group,
        foot="left" if (role.startswith("L") and rng.random() < 0.7) or rng.random() < 0.15 else "right",
        age=rng.randint(18, 34),
        nationality=rng.choice(_NATIONS),
        stamina=int(max(40, min(97, rng.gauss(74, 8)))),
        **vals,
    )


def build_team(rng: random.Random, team_id: str, name: str, short: str, colour: str,
               formation: str, quality: int, style: dict, used_names: set[str]) -> Team:
    slots = FORMATIONS[formation]
    players: list[Player] = []
    numbers = iter([1, 2, 5, 6, 3, 4, 8, 10, 7, 9, 11])
    xi = []
    for role, _, _, group in slots:
        n = next(numbers)
        p = _make_player(rng, team_id, n, role, group, quality, used_names)
        players.append(p)
        xi.append(p.id)
    # bench: GK, 2 DEF, 3 MID, 2 FWD
    bench_roles = [("GK", "GK"), ("CB", "DEF"), ("FB", "DEF"), ("CM", "MID"), ("CM", "MID"),
                   ("AM", "MID"), ("W", "FWD"), ("ST", "FWD")]
    bench = []
    for i, (role, group) in enumerate(bench_roles):
        p = _make_player(rng, team_id, 12 + i + (1 if 12 + i >= 13 else 0), role, group,
                         quality - 3, used_names)
        players.append(p)
        bench.append(p.id)
    return Team(id=team_id, name=name, short_name=short, colour=colour, formation=formation,
                style=style, players=players, starting_xi=xi, bench=bench)


def default_world(seed: int = 2026) -> World:
    """Two fictional clubs with contrasting styles."""
    rng = random.Random(seed)
    used: set[str] = set()
    home = build_team(rng, "ARD", "Arden Athletic", "Arden", "#C8102E", "4-3-3", quality=76,
                      style={"directness": 0.35, "press": 0.7, "control": 0.65}, used_names=used)
    away = build_team(rng, "HVL", "Hollow Vale", "Hollow Vale", "#1D4E89", "3-4-2-1", quality=74,
                      style={"directness": 0.6, "press": 0.45, "control": 0.45}, used_names=used)
    return World(competition="Fictional Premier Division", venue="Arden Park", home=home, away=away)
