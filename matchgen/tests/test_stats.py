"""The incremental stats engine must agree with the files, with itself, and with simple counts."""
import heapq
import json
from collections import Counter, defaultdict

import pytest

from matchgen.engine import simulate
from matchgen.io import match_metadata
from matchgen.script import DEMO_SCRIPT, Script
from matchgen.stats import SUMMABLE, StatsEngine, clock_to_elapsed, snapshots_every
from matchgen.summary import summarise
from matchgen.world import default_world

PLAYER_KEY = {"fouls": "fouls_committed", "yellows": "yellow_cards", "reds": "red_cards"}


@pytest.fixture(scope="module")
def data():
    eng = simulate(default_world(), seed=11, script=Script.from_dict(DEMO_SCRIPT))
    meta = match_metadata(eng)
    # round trip through JSON, as the files and the live feed would
    events = [json.loads(json.dumps(e)) for e in eng.events]
    frames = [json.loads(json.dumps(f)) for f in eng.frames]
    return meta, events, frames


def _full(meta, events, frames):
    se = StatsEngine(meta)
    for e in events:
        se.ingest_event(e)
    for f in frames:
        se.ingest_frame(f)
    return se


def test_full_time_agrees_with_independent_counts(data):
    meta, events, frames = data
    snap = _full(meta, events, frames).snapshot()
    c = {t: Counter() for t in (meta["home_team_id"], meta["away_team_id"])}
    for e in events:
        t, ty = e["team_id"], e["type"]
        o = [x for x in c if x != t][0]
        if ty == "pass":
            c[t]["passes"] += 1
            c[t]["passes_completed"] += e["outcome"] == "complete"
            c[t]["crosses"] += "cross" in e["qualifiers"]
        elif ty == "shot":
            c[t]["shots"] += 1
            c[t]["shots_on_target"] += e["outcome"] in ("goal", "saved")
        elif ty == "goal":
            c[t]["goals"] += 1
        elif ty in ("tackle", "interception", "clearance", "block", "pressure", "foul", "offside"):
            c[t][ty + "s"] += 1
        elif ty == "ball_recovery":
            c[t]["recoveries"] += 1
        elif ty == "card":
            c[t]["yellows"] += e["outcome"] in ("yellow", "second_yellow")
            c[t]["reds"] += e["outcome"] in ("red", "second_yellow")
        elif ty == "ball_out":
            r = e["extra"]["restart"]
            if r == "corner":
                c[o]["corners"] += 1
            elif r == "throw_in":
                c[o]["throw_ins"] += 1
    for t, cnt in c.items():
        for k, v in cnt.items():
            assert snap["teams"][t][k] == v, (t, k, snap["teams"][t][k], v)
    assert snap["score"] == meta["final_score"]
    assert summarise(meta, events, frames)[meta["home_team_id"]]["passes"] == snap["teams"][meta["home_team_id"]]["passes"]


def test_team_totals_equal_sum_of_players(data):
    meta, events, frames = data
    snap = _full(meta, events, frames).snapshot()
    for t, tb in snap["teams"].items():
        players = [p for p in snap["players"].values() if p["team_id"] == t]
        for k in SUMMABLE:
            pk = PLAYER_KEY.get(k, k)
            if k == "distance_m":
                assert abs(tb["distance_km"] - sum(p["distance_km"] for p in players)) < 0.05
                continue
            assert abs(tb[k] - sum(p[pk] for p in players)) < 1e-6, (t, k)
        assert tb["top_speed_kmh"] == max(p["top_speed_kmh"] for p in players)


def test_minute_zero_snapshot_is_all_zero(data):
    meta, _events, _frames = data
    snap = StatsEngine(meta).snapshot(at=0.0)
    assert snap["elapsed"] == 0 and snap["clock"] == "00:00.0" and snap["minute"] == 0

    def leaves(d):
        for k, v in d.items():
            if isinstance(v, dict):
                yield from leaves(v)
            elif isinstance(v, list):
                assert v == [], k
            elif isinstance(v, (int, float)) and not isinstance(v, bool):
                yield k, v
    for block in list(snap["teams"].values()) + list(snap["players"].values()):
        for k, v in leaves(block):
            assert v == 0, (k, v)
    assert sum(p["on_pitch"] for p in snap["players"].values()) == 22
    assert len(snap["players"]) == 22


def test_stream_order_equals_file_order(data):
    meta, events, frames = data
    whole = _full(meta, events, frames).snapshot()
    se = StatsEngine(meta)
    merged = heapq.merge(((f["elapsed"], 0, "frame", f) for f in frames),
                         ((e["elapsed"], 1, "event", e) for e in events), key=lambda m: (m[0], m[1]))
    for _t, _k, kind, d in merged:
        (se.ingest_frame if kind == "frame" else se.ingest_event)(d)
    assert se.snapshot() == whole


def test_snapshot_is_json_serialisable(data):
    meta, events, frames = data
    snap = _full(meta, events, frames).snapshot()
    text = json.dumps(snap)
    assert json.loads(text) == snap
    assert snap["kind"] == "snapshot"
    for t in snap["teams"].values():
        assert set(t["last_5_min"]) >= {"xg", "shots", "passes", "pass_accuracy", "possession",
                                        "final_third_entries", "pressures", "turnovers", "momentum", "control", "chaos"}
        assert 0 <= t["last_5_min"]["momentum"] <= 100
        assert len(t["pass_network"]) == 10 and all({"from", "to", "count"} == set(p) for p in t["pass_network"])


def test_players_include_subs_and_minutes(data):
    meta, events, frames = data
    snap = _full(meta, events, frames).snapshot()
    subs = [e for e in events if e["type"] == "substitution"]
    assert subs
    for e in subs:
        pin, pout = e["extra"]["player_in"], e["extra"]["player_out"]
        assert snap["players"][pin]["on_pitch"] is True
        assert snap["players"][pout]["on_pitch"] is False
        assert abs(snap["players"][pout]["minutes"] - e["elapsed"] / 60) < 0.1
        assert abs(snap["players"][pin]["minutes"] - (snap["elapsed"] - e["elapsed"]) / 60) < 0.1
    gk = snap["players"][meta["home_team_id"] + "_01"]
    assert {"saves", "xg_faced", "goals_prevented"} <= set(gk)
    # key passes and assists are credited from the shot events
    kp = sum(p["key_passes"] for p in snap["players"].values())
    assert kp == sum(1 for e in events if e["type"] == "shot" and "assist_event_id" in e["extra"])
    assert sum(p["assists"] for p in snap["players"].values()) == sum(
        1 for e in events if e["type"] == "goal" and e["extra"].get("assist_event_id"))


def test_snapshots_every_and_clock_parsing(data):
    meta, events, frames = data
    snaps = list(snapshots_every(meta, events, frames, 300))
    labels = [s.get("label") for s in snaps]
    assert labels.count("half_time") == 1 and labels[-1] == "full_time"
    el = [s["elapsed"] for s in snaps]
    assert el == sorted(el)
    assert snaps[-1]["score"] == meta["final_score"]
    stop1 = meta["stoppage_seconds"]["1"]
    assert clock_to_elapsed("14", meta) == 840
    assert clock_to_elapsed("14:30", meta) == 870
    assert clock_to_elapsed("45+2:00", meta) == 2700 + 120
    assert clock_to_elapsed("63:12", meta) == 2700 + stop1 + 18 * 60 + 12
    assert clock_to_elapsed("90+3:00", meta) == 2700 + stop1 + 2700 + 180
    # a snapshot at an arbitrary moment carries that clock
    se = StatsEngine(meta)
    for e in events:
        if e["elapsed"] <= 840:
            se.ingest_event(e)
    s = se.snapshot(at=840)
    assert s["clock"] == "14:00.0" and s["minute"] == 14 and s["period"] == 1
