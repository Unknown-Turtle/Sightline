from agents.extras.common import Match
from agents.extras.routines import detect, evaluate


def test_detection_finds_playbook_routines_without_truth(match=None):
    match = Match()
    data = detect(match)
    playbook = [p for p in data["patterns"] if p["source"] == "playbook"]
    assert len(playbook) == sum(len(r) for r in match.routines.values())
    assert sum(len(p["attempts"]) for p in playbook) >= 5
    for p in data["patterns"]:
        for a in p["attempts"]:
            assert all(i in match.by_id for i in a["event_ids"])
            assert a["outcome"] in ("shot", "lost", "completed")
    ev = evaluate(match, data)
    assert ev and ev["precision"] >= 0.5 and ev["recall"] >= 0.5
    # the detection output never mentions truth attempt ids
    assert "attempt_id" not in str(data["patterns"])
