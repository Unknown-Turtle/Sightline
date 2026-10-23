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


# ----------------------------------------------------------------- v0.2.0 engine fixes

def _rel(e, key):
    pt = e[key]
    if e["attack_dir"] == 1:
        return pt["x"], pt["y"]
    return L - pt["x"], W - pt["y"]


def test_names_unique_across_squads():
    w = default_world()
    players = w.home.players + w.away.players
    names = [p.name for p in players]
    surnames = [n.split(" ", 1)[1] for n in names]
    assert len(set(names)) == len(names)
    assert len(set(surnames)) == len(surnames)


def test_no_central_carry_walks_in(match):
    ev = match.events
    for i, e in enumerate(ev):
        if e["type"] != "carry" or not e["end"]:
            continue
        rx, ry = _rel(e, "end")
        srx, _ = _rel(e, "start")
        if rx > 96.05 and abs(ry - 34) < 20.16 and rx > srx + 0.05:
            prev = ev[i - 1]
            assert prev["type"] == "dribbled_past" or (prev["type"] == "take_on" and prev["outcome"] == "success"), e


def test_keeper_stays_in_box(match):
    gks = {t.team.id: {s.p.id for s in t.players.values() if s.is_gk} for t in (match.home, match.away)}
    dirs = {1: {"ARD": 1, "HVL": -1}, 2: {"ARD": -1, "HVL": 1}}
    for fr in match.frames[::7]:
        for pid, x, y, _k in fr["players"]:
            tid = pid[:3]
            if pid in gks[tid]:
                rx = x if dirs[fr["period"]][tid] == 1 else L - x
                assert rx <= 16.6 and 13.7 <= y <= 54.3, (fr["clock"], pid, x, y)


def test_ball_out_for_every_restart(match):
    ev = match.events
    seen = Counter()
    for i, e in enumerate(ev):
        if e["type"] in ("pass", "shot") and e["play_pattern"] in ("corner", "goal_kick", "throw_in") \
                and e["sequence_index"] == 0:
            # the previous non-dead-ball event of interest must be a ball_out with the matching restart
            j = i - 1
            while ev[j]["type"] in ("substitution", "card", "pressure"):
                j -= 1
            assert ev[j]["type"] == "ball_out", (e["clock"], e["play_pattern"], ev[j]["type"])
            assert ev[j]["extra"]["restart"] == e["play_pattern"], (e["clock"], ev[j]["extra"])
            seen[e["play_pattern"]] += 1
    assert seen["corner"] >= 1 and seen["goal_kick"] >= 3 and seen["throw_in"] >= 5, seen


def test_keepers_pass_in_build_up(match):
    gk_passes = Counter(e["team_id"] for e in match.events
                        if e["type"] == "pass" and e["player_id"] and e["player_id"].endswith("_01"))
    assert all(v >= 12 for v in gk_passes.values()), gk_passes


def test_standout_gets_more_defensive_actions():
    """The boosted centre back ARD_05 must out-work the other centre back ARD_06 (demo script)."""
    kinds = ("tackle", "interception", "clearance", "block", "ball_recovery")
    tot = Counter()
    for seed in range(1, 7):
        eng = simulate(default_world(), seed=seed, script=Script.from_dict(DEMO_SCRIPT))
        tot.update(e["player_id"] for e in eng.events if e["type"] in kinds and e["player_id"] in ("ARD_05", "ARD_06"))
    print(f"\nARD_05 {tot['ARD_05'] / 6:.1f} vs ARD_06 {tot['ARD_06'] / 6:.1f} defensive actions per match (6 seeds)")
    assert tot["ARD_05"] > 1.25 * tot["ARD_06"], tot
