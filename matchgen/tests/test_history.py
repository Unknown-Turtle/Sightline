"""The history archive must be self-consistent and deterministic."""
import json
from collections import Counter

import pytest

from matchgen.history import SEASONS, build_history, season_label
from matchgen.world import default_world


@pytest.fixture(scope="module")
def hist():
    return build_history(7, default_world())


def test_fixture_list_and_calibration(hist):
    assert len(hist.results) == 5 * 380
    for s in SEASONS:
        ms = [r for r in hist.results if r["season_start"] == s]
        pairs = Counter((r["home_id"], r["away_id"]) for r in ms)
        assert len(pairs) == 380 and max(pairs.values()) == 1
        assert Counter(r["matchday"] for r in ms) == {md: 10 for md in range(1, 39)}
    n = len(hist.results)
    goals = sum(r["home_goals"] + r["away_goals"] for r in hist.results) / n
    home = sum(r["home_goals"] > r["away_goals"] for r in hist.results) / n
    draw = sum(r["home_goals"] == r["away_goals"] for r in hist.results) / n
    assert 2.5 < goals < 3.2 and 0.38 < home < 0.55 and 0.18 < draw < 0.32
    cap = {c.id: c.capacity for c in hist.clubs}
    for r in hist.results:
        assert r["attendance"] <= cap[r["home_id"]]
        assert r["ht_home_goals"] <= r["home_goals"] and r["ht_away_goals"] <= r["away_goals"]
        assert len(r["goals"]) == r["home_goals"] + r["away_goals"]


def test_standings_reconcile_with_results(hist):
    for row in hist.standings():
        s = row["season"]
        cid = row["club_id"]
        ms = [r for r in hist.results if r["season"] == s and cid in (r["home_id"], r["away_id"])]
        gf = sum(r["home_goals"] if r["home_id"] == cid else r["away_goals"] for r in ms)
        ga = sum(r["away_goals"] if r["home_id"] == cid else r["home_goals"] for r in ms)
        won = sum((r["home_goals"] > r["away_goals"]) == (r["home_id"] == cid) and r["home_goals"] != r["away_goals"] for r in ms)
        drawn = sum(r["home_goals"] == r["away_goals"] for r in ms)
        assert (row["played"], row["gf"], row["ga"], row["won"], row["drawn"]) == (38, gf, ga, won, drawn)
        assert row["points"] == 3 * won + drawn and row["lost"] == 38 - won - drawn
    per_season = Counter(r["season"] for r in hist.standings())
    assert per_season == {season_label(s): 20 for s in SEASONS}
    assert all(r["position"] == i % 20 + 1 for i, r in enumerate(hist.standings()))


def test_head_to_head_reconciles_with_results(hist):
    h2h = hist.head_to_head()
    assert len(h2h) == 190
    for row in h2h:
        a, b = row["club_a"], row["club_b"]
        ms = [r for r in hist.results if {r["home_id"], r["away_id"]} == {a, b}]
        assert row["played"] == len(ms) == 10
        a_goals = sum(r["home_goals"] if r["home_id"] == a else r["away_goals"] for r in ms)
        assert row["a_goals"] == a_goals
        assert row["a_wins"] + row["draws"] + row["b_wins"] == 10
    ard = next(r for r in h2h if {r["club_a"], r["club_b"]} == {"ARD", "HVL"})
    assert ard["last_meeting_date"]


def test_careers_reconcile_with_goal_events(hist):
    goals = Counter()
    assists = Counter()
    apps = Counter()
    for r in hist.results:
        for g in r["goals"]:
            goals[(g["scorer_id"], r["season"])] += 1
            if g["assist_id"]:
                assists[(g["assist_id"], r["season"])] += 1
        for cid, pids in r["lineups"].items():
            for pid in pids:
                apps[(pid, r["season"])] += 1
    rows = hist.player_careers()
    seen = Counter()
    for row in rows:
        k = (row["player_id"], row["season"])
        seen[k] += 1
        assert row["goals"] == goals.get(k, 0), row
        assert row["assists"] == assists.get(k, 0), row
        assert row["apps"] == apps.get(k, 0), row
    assert max(seen.values()) == 1          # one club per player per season
    assert sum(goals.values()) == sum(r["goals"] for r in rows)
    # every current player has a plausible career: ages 17 and up, at most five seasons
    cur = [r for r in rows if r["current_squad"]]
    assert cur and all(r["age"] >= 17 for r in cur)
    ids = {r["player_id"] for r in cur}
    assert "ARD_09" in ids and "HVL_09" in ids
    moved = {pid for pid in ids if len({r["club_id"] for r in cur if r["player_id"] == pid}) > 1}
    assert moved
    rec = {r["record"] for r in hist.club_records()}
    assert rec == {"biggest_win", "biggest_defeat", "longest_winning_streak", "longest_unbeaten_run",
                   "record_scorer", "record_home_attendance", "most_points_in_a_season", "highest_finish"}
    assert len(hist.scoring_timeline()) == sum(goals.values())
    assert all(1 <= m["remaining"] <= 5 for m in hist.milestones_upcoming())


def test_history_deterministic(tmp_path):
    a = build_history(3, default_world())
    b = build_history(3, default_world())
    assert a.results == b.results
    assert a.tables() == b.tables()
    a.write(str(tmp_path / "h"))
    text = (tmp_path / "h" / "results.jsonl").read_text()
    assert json.loads(text.splitlines()[0])["season"] == "2021-22"
    assert (tmp_path / "h" / "standings.csv").read_text().startswith("season,position,club_id,")
    c = build_history(4, default_world())
    assert c.results != a.results
