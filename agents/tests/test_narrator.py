"""The narrator loop: a model reply with a made-up number is sent back with the issues, a clean
reply is accepted, and after two failed retries the template takes over. Uses a fake model so
the loop is proven without credentials."""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from agents.llm import LLMReply  # noqa: E402
from agents.narrator import MAX_RETRIES, narrate  # noqa: E402
from agents.tests.test_checker import PACK, TRIVIA  # noqa: E402


class FakeFoundry:
    configured = True
    deployment = "fake-deployment"

    def __init__(self, replies):
        self.replies = list(replies)
        self.prompts = []

    def chat(self, system, user):
        self.prompts.append(user)
        if not self.replies:
            return None
        text = self.replies.pop(0)
        return LLMReply(text=json.dumps(text) if isinstance(text, dict) else text,
                        latency_ms=5, tokens_in=100, tokens_out=40, model=self.deployment)


GOOD = {"casual": "Tremblay is holding the Arden Athletic defence together.",
        "tactical": "Rhys Tremblay: 22 defensive actions, 12 more than any teammate, with 4 lost.",
        "commentator": "Tremblay, 148 league appearances in, is the rock tonight."}
BAD_NUMBER = dict(GOOD, tactical="Rhys Tremblay: 25 defensive actions, 12 more than any teammate.")
BAD_NAME = dict(GOOD, commentator="Tremblay is doing a Virgil van Dijk impression tonight.")


def test_clean_reply_is_accepted_first_time():
    f = FakeFoundry([GOOD])
    n = narrate(PACK, TRIVIA, f)
    assert n.source == "llm" and n.retries == 0 and n.check.passed
    assert n.text == GOOD and len(n.calls) == 1


def test_bad_number_is_sent_back_then_fixed():
    f = FakeFoundry([BAD_NUMBER, GOOD])
    n = narrate(PACK, TRIVIA, f)
    assert n.source == "llm" and n.retries == 1 and n.check.passed
    assert "25" in f.prompts[1] and "failed the checker" in f.prompts[1]
    assert sum(c.tokens_in for c in n.calls) == 200


def test_falls_back_to_template_after_two_retries():
    f = FakeFoundry([BAD_NUMBER, BAD_NAME, BAD_NUMBER, GOOD])
    n = narrate(PACK, TRIVIA, f)
    assert n.source == "template" and n.retries == MAX_RETRIES and n.check.passed
    assert len(f.prompts) == MAX_RETRIES + 1, "at most 3 calls per point"
    assert "22 defensive actions" in n.text["tactical"]


def test_unparseable_reply_counts_as_a_retry():
    f = FakeFoundry(["not json at all", GOOD])
    n = narrate(PACK, TRIVIA, f)
    assert n.source == "llm" and n.retries == 1


def test_model_failure_falls_back_immediately():
    f = FakeFoundry([])
    n = narrate(PACK, TRIVIA, f)
    assert n.source == "template" and n.check.passed and n.calls == []


def test_system_prompt_forbids_numbers_outside_the_fact_pack():
    from agents.narrator import SYSTEM_PROMPT
    assert "must not write any number that does not appear in the fact pack" in SYSTEM_PROMPT
