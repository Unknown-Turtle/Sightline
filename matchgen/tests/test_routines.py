"""Rehearsed routines: attempted at triggers, breakable, and tagged only in the ground-truth file."""
import json
import os

import pytest

from matchgen.engine import simulate
from matchgen.io import write_match
from matchgen.world import World, default_world

OUTCOMES = {"completed", "broken_pressure", "broken_pass", "lost_possession", "abandoned"}


@pytest.fixture(scope="module")
def match():
    return simulate(default_world(), seed=21)


def test_routines_are_attempted_and_consistent(match):
    attempts = match.routine_attempts
    assert len(attempts) >= 10
    by_id = {e["event_id"]: e for e in match.events}
    teams_seen = set()
    for a in attempts:
        assert a["outcome"] in OUTCOMES
        assert a["trigger"] in ("goal_kick", "keeper", "regain_own_third")
        assert 0 <= a["steps_completed"] <= a["steps_total"]
        assert a["event_ids"], a
        teams_seen.add(a["team_id"])
        for eid in a["event_ids"]:
            e = by_id[eid]
            assert e["type"] == "pass" and e["team_id"] == a["team_id"]
            assert e["possession_id"] == a["possession_id"]
            assert a["start_elapsed"] <= e["elapsed"] <= a["end_elapsed"]
        if a["outcome"] == "completed":
            assert a["steps_completed"] == a["steps_total"]
            assert all(by_id[eid]["outcome"] == "complete" for eid in a["event_ids"])
        if a["outcome"] == "broken_pass":
            assert by_id[a["event_ids"][-1]]["outcome"] != "complete"
    assert teams_seen == {"ARD", "HVL"}
    # every attempt is a distinct possession and attempts never overlap in time
    poss = [a["possession_id"] for a in attempts]
    assert len(poss) == len(set(poss))
    ends = [a["end_elapsed"] for a in attempts]
    starts = [a["start_elapsed"] for a in attempts]
    assert all(starts[i + 1] >= ends[i] for i in range(len(attempts) - 1))


def test_no_routine_tags_in_events(match, tmp_path):
    assert not any("routine_id" in e["extra"] or "attempt_id" in e["extra"] for e in match.events)
    meta = write_match(match, str(tmp_path / "m"))
    with open(tmp_path / "m" / "events.jsonl") as f:
        assert "routine_id" not in f.read()
    truth = [json.loads(l) for l in open(tmp_path / "m" / "routines_truth.jsonl")]
    assert len(truth) == len(match.routine_attempts)
    assert truth[0]["attempt_id"] == "r_0001"
    # the playbook (definitions) is public in match.json; the attempts are not
    assert all("routines" in lu for lu in meta["lineups"])
    assert {r["id"] for r in meta["lineups"][0]["routines"]} == {"ARD_R1", "ARD_R2", "ARD_R3"}


def test_rehearsed_dial_zero_means_no_attempts():
    w = default_world()
    w.home.style["rehearsed"] = 0.0
    w.away.style["rehearsed"] = 0.0
    eng = simulate(w, seed=21)
    assert eng.routine_attempts == []
    # and a world without routines still loads and runs
    d = default_world().to_dict()
    for side in ("home", "away"):
        d[side].pop("routines")
    w2 = World.from_dict(d)
    assert w2.home.routines == []
    assert simulate(w2, seed=2).routine_attempts == []
