import pytest

from agents.extras.checker import allowed_number_set, check_text
from agents.extras.claims import check_claim, classify_keywords, narrate, run_tests, verdict_for
from agents.extras.common import Match
from agents.extras.llm import LLM


@pytest.fixture(scope="module")
def match():
    return Match(frames=True)


def test_off_topic_is_out_of_scope(match):
    for claim in ["Who will win the league this season?", "The referee has been shocking tonight", "Nice weather for it"]:
        r = check_claim(match, claim, 3000.0, llm=LLM())
        assert r["verdict"] == "out_of_scope"
        assert r["tests"] == []


def test_keyword_classifier_maps_types(match):
    assert classify_keywords(match, "Arden have lost all momentum")["type"] == "momentum_lost"
    assert classify_keywords(match, "Hollow Vale are dominating")["type"] == "dominance"
    assert classify_keywords(match, "Arden's press is finally working")["type"] == "pressing_working"
    c = classify_keywords(match, f"{match.surname('ARD_05')} is having a huge game")
    assert c["type"] == "player_big_game" and c["players"] == ["ARD_05"]
    assert classify_keywords(match, "Hollow Vale look tired")["type"] == "tiredness"


def test_made_up_number_is_rejected(match):
    cls = classify_keywords(match, "Hollow Vale have lost the momentum")
    tests, subj = run_tests(match, cls, 4700.0)
    allowed = allowed_number_set([x["value"] for x in tests])
    names = {"Hollow Vale", "Arden Athletic", "Arden", "Hollow", "Vale", "Athletic"}
    good = f"Hollow Vale have faded: {tests[0]['value']}."
    assert check_text(good, allowed, names, match.all_names()) == []
    bad = "Hollow Vale have faded: 2 final-third entries against 17 before."
    issues = check_text(bad, allowed, names, match.all_names())
    assert any("number" in i for i in issues), issues
    wrong_name = f"{match.surname('ARD_09')} has lost the momentum: {tests[0]['value']}."
    assert any("name" in i for i in check_text(wrong_name, allowed, names, match.all_names()))


def test_narrator_rejection_falls_back_to_template(match, monkeypatch):
    class FakeLLM(LLM):
        def __init__(self):
            self.cfg = {"endpoint": "x", "deployment": "fake", "api_key": "k"}
            self.model = "fake"
            self.calls = 0

        def chat(self, system, user, **kw):
            self.calls += 1
            return {"text": '{"casual": "Hollow Vale have made 99 final-third entries.", "tactical": "They have 123 shots."}',
                    "latency_ms": 1, "tokens_in": 1, "tokens_out": 1}

    llm = FakeLLM()
    cls = classify_keywords(match, "Hollow Vale have lost the momentum")
    tests, subj = run_tests(match, cls, 4700.0)
    subj["t"] = 4700.0
    summary, check, receipt = narrate(match, llm, "Hollow Vale have lost the momentum", subj, tests, verdict_for(tests), "tactical", "en")
    assert llm.calls == 2
    assert check["retries"] == 2 and check["issues"]
    assert "99" not in summary["casual"] and "123" not in summary["tactical"]


def test_response_contract(match):
    r = check_claim(match, "Hollow Vale have lost the momentum now", 4700.0)
    for key in ("claim", "verdict", "summary", "tests", "evidence_for", "evidence_against", "check", "receipt"):
        assert key in r
    assert r["verdict"] in ("supported", "partly", "not_supported")
    assert set(r["summary"]) >= {"casual", "tactical"}
    assert all({"name", "value", "passes"} <= set(x) for x in r["tests"])
    assert all(i in match.by_id for i in r["evidence_for"] + r["evidence_against"])
    assert r["receipt"]["mode"] in ("live", "fallback")
