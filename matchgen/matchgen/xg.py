"""A simple, transparent expected-goals model.

Inputs are in the shooting team's relative frame (goal at x = 105, y = 34).
Logistic in distance and the angle subtended by the goal mouth, then a set of
named multipliers so every shot's xG can be explained:

  header    0.55 for headed attempts
  pressure  0.80 when an opponent was within 4 m as the shot was struck
  counter   1.15 when the possession began with a regain in the team's own half
            less than 15 s earlier
  lane      0.72 per outfield defender in the shooting lane (capped at four)
  keeper    0.4 to 1.0 when the keeper has come out to within 6 m of a shot
            struck inside roughly 17 m of goal (0.4 + 0.1 x distance in metres)

Penalties are a flat 0.76; direct free kicks use 0.6 x the open-play value,
capped at 0.12. Our own definition, tuned to give realistic values
(penalty-spot open play about 0.3, edge of box about 0.08).
"""
from __future__ import annotations

import math

GOAL_HALF_WIDTH = 3.66
PENALTY_XG = 0.76


def goal_angle(rx: float, ry: float) -> float:
    dx = max(0.5, 105.0 - rx)
    a1 = math.atan2(34 + GOAL_HALF_WIDTH - ry, dx)
    a2 = math.atan2(34 - GOAL_HALF_WIDTH - ry, dx)
    return abs(a1 - a2)


def base_xg(rx: float, ry: float) -> float:
    d = math.hypot(105.0 - rx, 34.0 - ry)
    ang = goal_angle(rx, ry)
    z = -0.52 - 0.14 * d + 1.6 * ang
    return 1.25 / (1.0 + math.exp(-z))


def xg_breakdown(rx: float, ry: float, header: bool = False, under_pressure: bool = False,
                 counter: bool = False, defenders_in_lane: int = 0,
                 gk_distance: float | None = None) -> tuple[float, dict[str, float]]:
    """Return (xg, factors). factors holds the base value and every multiplier applied."""
    base = base_xg(rx, ry)
    factors = {
        "base": round(base, 4),
        "header": 0.55 if header else 1.0,
        "pressure": 0.8 if under_pressure else 1.0,
        "counter": 1.15 if counter else 1.0,
        "lane": round(0.72 ** min(defenders_in_lane, 4), 4),
        "keeper": 1.0,
    }
    if gk_distance is not None and gk_distance < 6.0 and rx > 88:
        factors["keeper"] = round(max(0.4, min(1.0, 0.4 + 0.1 * gk_distance)), 4)
    xg = base
    for k, v in factors.items():
        if k != "base":
            xg *= v
    return max(0.005, min(0.95, xg)), factors


def shot_xg(rx: float, ry: float, header: bool = False, under_pressure: bool = False,
            counter: bool = False) -> float:
    """Location-based xG without lane or keeper context (used for shot propensity)."""
    return xg_breakdown(rx, ry, header=header, under_pressure=under_pressure, counter=counter)[0]
