"""Invariant tests: the generator must never produce impossible football."""
import math
from collections import Counter

import pytest

from matchgen.engine import simulate
from matchgen.script import DEMO_SCRIPT, Script
from matchgen.world import default_world

L, W = 105, 68


@pytest.fixture(scope="module")
def match():
    return simulate(default_world(), seed=11, script=Script.from_dict(DEMO_SCRIPT))


def test_deterministic():
    a = simulate(default_world(), seed=3)
    b = simulate(default_world(), seed=3)
    assert a.events == b.events
    assert a.frames[-1] == b.frames[-1]


def test_clock_monotonic(match):
    t = [e["elapsed"] for e in match.events]
    assert t == sorted(t)
    f = [fr["elapsed"] for fr in match.frames]
    assert f == sorted(f)
    assert all(abs((f[i + 1] - f[i]) - 1.0) < 1e-6 for i in range(len(f) - 1))


def test_match_length(match):
    assert 90 * 60 <= match.elapsed <= 90 * 60 + 12 * 60


def test_score_matches_goal_events(match):
    goals = Counter(e["team_id"] for e in match.events if e["type"] == "goal")
    assert goals.get("ARD", 0) == match.home.score
    assert goals.get("HVL", 0) == match.away.score
    shots_scored = Counter(e["team_id"] for e in match.events if e["type"] == "shot" and e["outcome"] == "goal")
    assert shots_scored == goals


def test_coordinates_on_pitch(match):
    for e in match.events:
        for k in ("start", "end"):
            pt = e[k]
            if pt:
                assert -0.01 <= pt["x"] <= L + 0.01 and -0.01 <= pt["y"] <= W + 0.01, e
    for fr in match.frames[::50]:
        for pid, x, y, kmh in fr["players"]:
            assert -2.5 <= x <= L + 2.5 and -2.5 <= y <= W + 2.5
            assert 0 <= kmh < 38


def test_eleven_or_fewer_on_pitch(match):
    for fr in match.frames[::30]:
        c = Counter(pid[:3] for pid, *_ in fr["players"])
        assert all(7 <= n <= 11 for n in c.values()), c


def test_event_ids_unique_and_links_valid(match):
    ids = [e["event_id"] for e in match.events]
    assert len(ids) == len(set(ids))
    known = set(ids)
    for e in match.events:
        if e["related_event_id"]:
            assert e["related_event_id"] in known


def test_shots_have_xg(match):
    for e in match.events:
        if e["type"] == "shot":
            assert 0 < e["extra"]["xg"] < 1


def test_red_card_removes_player():
    eng = simulate(default_world(), seed=5,
                   script=Script.from_dict({"red_cards": [{"minute": 60, "team": "HVL", "player": "HVL_05"}]}))
    reds = [e for e in eng.events if e["type"] == "card" and e["outcome"] in ("red", "second_yellow")]
    assert reds
    sent_off = reds[0]["player_id"]
    after = [fr for fr in eng.frames if fr["elapsed"] > reds[0]["elapsed"] + 2]
    assert all(sent_off not in {p[0] for p in fr["players"]} for fr in after)


def test_event_location_matches_ball_in_tracking(match):
    by_t = {round(fr["elapsed"]): fr for fr in match.frames}
    errs = []
    for e in match.events:
        if e["type"] in ("pass", "carry", "shot") and abs(e["elapsed"] - round(e["elapsed"])) < 0.11:
            fr = by_t.get(round(e["elapsed"]))
            if fr:
                bx, by, _ = fr["ball"]
                errs.append(math.hypot(bx - e["start"]["x"], by - e["start"]["y"]))
    assert errs and sorted(errs)[len(errs) // 2] < 1.0
