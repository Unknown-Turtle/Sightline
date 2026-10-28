"""End to end in fallback mode on the sample match: every item checks out and follows the contract."""
import json
import os
import sys

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, ROOT)
MATCH = os.path.join(ROOT, "matchgen", "sample", "demo_seed587")
HISTORY = os.path.join(ROOT, "matchgen", "sample", "history")

pytestmark = pytest.mark.skipif(not os.path.isdir(MATCH), reason="sample match not present")


@pytest.fixture(scope="module")
def result():
    from agents.data import load_history, load_match
    from agents.pipeline import build
    return build(load_match(MATCH), load_history(HISTORY), None)


def test_contract_shape(result):
    assert result["mode"] == "fallback" and result["model"] is None
    assert result["match_id"] == "m_seed587"
    keys = {"id", "t", "clock", "kind", "point_id", "team", "subject", "text", "evidence_for",
            "evidence_against", "trivia", "check", "receipt"}
    for item in result["items"]:
        assert keys <= set(item)
        assert set(item["text"]) == {"casual", "tactical", "commentator"}
        assert item["kind"] in ("anchor", "duel", "finishing", "momentum", "score_state", "recap")
        for f in item["trivia"]:
            assert f["source"] and f["row"] and f["text"]
    json.dumps(result)


def test_every_item_passes_the_checker(result):
    assert result["items"]
    assert all(i["check"]["passed"] for i in result["items"])


def test_items_are_in_time_order_with_recaps(result):
    ts = [i["t"] for i in result["items"]]
    assert ts == sorted(ts)
    assert {i["point_id"] for i in result["items"] if i["kind"] == "recap"} == {"recap-ht", "recap-ft"}


def test_demo_story_is_detected(result):
    kinds = {(i["kind"], i["point_id"]) for i in result["items"]}
    assert ("anchor", "anchor-ARD_05") in kinds
    last_score = [i for i in result["items"] if i["kind"] == "score_state"][-1]
    assert "3-2" in last_score["text"]["tactical"]
    assert any("come back" in i["text"]["casual"] for i in result["items"] if i["kind"] == "score_state")


def test_casual_has_no_jargon(result):
    for i in result["items"]:
        assert "xG" not in i["text"]["casual"]


def test_dead_endpoint_still_completes_and_reports_fallback():
    from agents.data import load_history, load_match
    from agents.llm import Foundry
    from agents.pipeline import build
    foundry = Foundry(endpoint="https://127.0.0.1:9/", deployment="gpt-4o", api_key="x")
    out = build(load_match(MATCH), load_history(HISTORY), foundry, max_items=2)
    assert out["mode"] == "fallback" and out["model"] is None
    assert out["items"] and all(i["check"]["passed"] for i in out["items"])
    assert all(i["receipt"]["source"] == "template" for i in out["items"])
