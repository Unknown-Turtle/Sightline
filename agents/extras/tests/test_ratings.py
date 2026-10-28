from agents.extras.common import Match
from agents.extras.ratings import compute_ratings, event_effects, W, LOW, HIGH


def test_ratings_reconcile_with_event_log():
    match = Match()
    data = compute_ratings(match)
    # every reason's effect, summed per player over all ticks, equals the independent event walk
    expected: dict[str, float] = {}
    for _, pid, reason in event_effects(match):
        expected[pid] = expected.get(pid, 0.0) + reason["effect"]
    for pid, entries in data["players"].items():
        total = sum(r["effect"] for e in entries for r in e["reasons"])
        assert abs(total - expected.get(pid, 0.0)) < 1e-6, pid
        for e in entries:
            assert LOW <= e["rating"] <= HIGH
    # goals credited in reasons equal goals in the event log, per player
    goals_log: dict[str, int] = {}
    for e in match.events:
        if e["type"] == "shot" and e["outcome"] == "goal":
            goals_log[e["player_id"]] = goals_log.get(e["player_id"], 0) + 1
    goals_rated = {}
    for pid, entries in data["players"].items():
        n = sum(1 for e in entries for r in e["reasons"] if r["label"] == "Goal")
        if n:
            goals_rated[pid] = n
    assert goals_rated == goals_log
    # every reason points at a real event, and every reason event id is in the log
    for entries in data["players"].values():
        for e in entries:
            for r in e["reasons"]:
                assert r["event_id"] in match.by_id
    # deterministic
    assert compute_ratings(match) == data
