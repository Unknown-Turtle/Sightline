"""A simple, transparent expected-goals model.

Inputs are in the shooting team's relative frame (goal at x = 105, y = 34).
Logistic in distance and the angle subtended by the goal mouth, with
adjustments for headers, pressure and fast breaks. Our own definition; it is
tuned to give realistic values (penalty-spot open play ~0.3, edge of box ~0.08).
"""
from __future__ import annotations

import math

GOAL_HALF_WIDTH = 3.66


def goal_angle(rx: float, ry: float) -> float:
    dx = max(0.5, 105.0 - rx)
    a1 = math.atan2(34 + GOAL_HALF_WIDTH - ry, dx)
    a2 = math.atan2(34 - GOAL_HALF_WIDTH - ry, dx)
    return abs(a1 - a2)


def shot_xg(rx: float, ry: float, header: bool = False, under_pressure: bool = False,
            counter: bool = False) -> float:
    d = math.hypot(105.0 - rx, 34.0 - ry)
    ang = goal_angle(rx, ry)
    z = -0.52 - 0.14 * d + 1.6 * ang
    xg = 1.25 / (1.0 + math.exp(-z))
    if header:
        xg *= 0.55
    if under_pressure:
        xg *= 0.8
    if counter:
        xg *= 1.15
    return max(0.005, min(0.95, xg))
