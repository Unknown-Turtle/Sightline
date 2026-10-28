"""The checker must reject a narrator line with a made-up number or a made-up name,
and accept lines that only use what the fact pack and trivia contain."""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from agents.checker import check_lenses, check_text  # noqa: E402
from agents.narrator import template_text  # noqa: E402

PACK = {
    "point_id": "anchor-ARD_05", "kind": "anchor", "team": "ARD", "subject": "ARD_05",
    "t": 4356.0, "clock": "72:36", "team_name": "Arden Athletic", "subject_name": "Rhys Tremblay",
    "numbers": {"defensive_actions": 22, "next_best_teammate": 10, "margin_over_teammates": 12,
                "actions_lost": 4, "minute": 72},
    "names": ["Rhys Tremblay", "Tremblay", "Arden Athletic", "Hollow Vale"],
    "evidence_for": [{"event_id": "e_000123", "clock": "12:04", "minute": 12, "player": "Rhys Tremblay",
                      "label": "Interception", "zone": "in their own box"}],
    "evidence_against": [{"event_id": "e_000456", "clock": "40:10", "minute": 40, "player": "Rhys Tremblay",
                          "label": "Foul conceded", "zone": "in midfield"}],
    "strength": 16.4, "summary": "Rhys Tremblay has 22 defensive actions, 12 more than any teammate",
}
TRIVIA = [{"text": "Rhys Tremblay has 148 league appearances over the five recorded seasons.",
           "source": "player_careers.csv", "row": "ARD_05,2021-22..2025-26"}]


def test_accepts_numbers_from_the_fact_pack():
    r = check_text("Rhys Tremblay: 22 defensive actions, 12 more than any teammate, with 4 lost.", PACK, TRIVIA)
    assert r.passed, r.issues
    assert r.numbers_checked == 3


def test_accepts_numbers_from_trivia_and_evidence_clocks():
    r = check_text("Tremblay, 148 league appearances in, made that interception at 12:04.", PACK, TRIVIA)
    assert r.passed, r.issues


def test_rejects_made_up_number():
    r = check_text("Rhys Tremblay has made 25 defensive actions tonight.", PACK, TRIVIA)
    assert not r.passed
    assert any("25" in i for i in r.issues)


def test_rejects_made_up_decimal_and_percentage():
    r = check_text("Tremblay wins 87.5 percent of his duels.", PACK, TRIVIA)
    assert not r.passed
    r = check_text("Tremblay wins 88% of his duels.", PACK, TRIVIA)
    assert not r.passed


def test_rejects_made_up_number_word():
    r = check_text("Tremblay has made three interceptions already.", PACK, TRIVIA)
    assert not r.passed
    assert any("three" in i for i in r.issues)


def test_rejects_made_up_clock():
    r = check_text("Tremblay cleared it off the line at 61:30.", PACK, TRIVIA)
    assert not r.passed


def test_rejects_made_up_name():
    r = check_text("Tremblay is holding the line alongside Marcus Rashford tonight.", PACK, TRIVIA)
    assert not r.passed
    assert any("Marcus" in i or "Rashford" in i for i in r.issues)


def test_rejects_made_up_name_at_sentence_start():
    r = check_text("Marcus Rashford is holding the line for Arden Athletic.", PACK, TRIVIA)
    assert not r.passed


def test_rejects_made_up_club():
    r = check_text("Tremblay was the rock when Arden Athletic beat Chelsea last month.", PACK, TRIVIA)
    assert not r.passed


def test_ordinary_sentence_starts_are_not_names():
    r = check_text("Nobody gets past Tremblay. Every clearance lands.", PACK, TRIVIA)
    assert r.passed, r.issues


def test_event_ids_are_not_treated_as_numbers():
    r = check_text("See e_000123 for the interception.", PACK, TRIVIA)
    assert r.passed, r.issues


def test_all_lenses_are_checked_and_issues_are_labelled():
    texts = {"casual": "Tremblay is holding the Arden Athletic defence together.",
             "tactical": "Rhys Tremblay: 22 defensive actions, 12 more than any teammate.",
             "commentator": "Tremblay has made 99 clearances this season."}
    r = check_lenses(texts, PACK, TRIVIA)
    assert not r.passed
    assert r.issues and r.issues[0].startswith("commentator:")


@pytest.mark.parametrize("kind", ["anchor"])
def test_templates_pass_their_own_check(kind):
    texts = template_text(PACK, TRIVIA)
    r = check_lenses(texts, PACK, TRIVIA)
    assert r.passed, r.issues
