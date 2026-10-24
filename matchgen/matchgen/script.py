"""Storyline scripting: bias the simulation so a demo match has drama on cue.

A script never forces a goal. It shifts probabilities (momentum, pressing,
control) for a team over a window of minutes, boosts a standout player, or
schedules a red card. Example:

{
  "segments": [
    {"from": 0,  "to": 20, "team": "ARD", "control": 0.3},
    {"from": 55, "to": 72, "team": "HVL", "momentum": 0.5, "press": 0.6}
  ],
  "standouts": [{"player": "ARD_07", "boost": 10}],
  "red_cards": [{"minute": 68, "team": "HVL", "player": "HVL_05"}],
  "context": {"weather": "rain", "stakes": "relegation six-pointer"}
}

`context` overrides any of the seeded match-context fields (referee, weather,
attendance, kickoff_local, matchday, stakes) and takes precedence over the same
block in the world JSON.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field


@dataclass
class Segment:
    start: float
    end: float
    team: str
    momentum: float = 0.0  # attacking intent: shot and forward-pass propensity
    control: float = 0.0   # pass security and patience
    press: float = 0.0     # pressing intensity out of possession


@dataclass
class Script:
    segments: list[Segment] = field(default_factory=list)
    standouts: dict[str, int] = field(default_factory=dict)
    red_cards: list[dict] = field(default_factory=list)
    context: dict = field(default_factory=dict)

    @staticmethod
    def from_dict(d: dict) -> "Script":
        segs = [Segment(start=s["from"], end=s["to"], team=s["team"],
                        momentum=s.get("momentum", 0.0), control=s.get("control", 0.0),
                        press=s.get("press", 0.0)) for s in d.get("segments", [])]
        stand = {s["player"]: int(s.get("boost", 10)) for s in d.get("standouts", [])}
        return Script(segments=segs, standouts=stand, red_cards=list(d.get("red_cards", [])),
                      context=dict(d.get("context", {})))

    @staticmethod
    def load(path: str) -> "Script":
        with open(path) as f:
            return Script.from_dict(json.load(f))

    def mods(self, team_id: str, minute: float) -> tuple[float, float, float]:
        m = c = p = 0.0
        for s in self.segments:
            if s.team == team_id and s.start <= minute < s.end:
                m += s.momentum
                c += s.control
                p += s.press
        return m, c, p


DEMO_SCRIPT = {
    "segments": [
        {"from": 0, "to": 25, "team": "ARD", "control": 0.35, "press": 0.3},
        {"from": 25, "to": 40, "team": "HVL", "momentum": 0.3},
        {"from": 55, "to": 75, "team": "HVL", "momentum": 0.45, "press": 0.5},
        {"from": 75, "to": 95, "team": "ARD", "momentum": 0.5, "control": 0.2},
    ],
    "standouts": [{"player": "ARD_05", "boost": 12}, {"player": "HVL_09", "boost": 10}],
    "red_cards": [],
}
