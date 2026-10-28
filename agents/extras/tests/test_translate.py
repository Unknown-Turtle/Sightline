from agents.extras.common import Match
from agents.extras.llm import LLM
from agents.extras.translate import translate_fields, translate_insights

SAMPLE = {"match_id": "m_seed587", "mode": "fallback", "model": None, "items": [
    {"id": "i_0001", "t": 4356.0, "kind": "duel", "team": "ARD", "subject": "ARD_05",
     "text": {"casual": "Tremblay has won 6 of his 8 duels.", "tactical": "Tremblay: 6 of 8 duels won, 4 interceptions.", "commentator": "Tremblay again."}}]}


def test_fallback_keeps_english_and_flags_it():
    out = translate_insights(Match(), SAMPLE, "es", LLM())
    assert out["translated"] is False and out["items"][0]["translated"] is False
    assert out["items"][0]["text"] == SAMPLE["items"][0]["text"]


class FakeLLM(LLM):
    def __init__(self, reply):
        self.cfg = {"endpoint": "x", "deployment": "fake", "api_key": "k"}
        self.model = "fake"
        self.reply = reply

    def chat(self, system, user, **kw):
        return {"text": self.reply, "latency_ms": 1, "tokens_in": 1, "tokens_out": 1}


def test_translation_with_changed_number_is_rejected():
    m = Match()
    fields = SAMPLE["items"][0]["text"]
    bad = FakeLLM('{"casual": "Tremblay ha ganado 7 de sus 8 duelos.", "tactical": "Tremblay: 6 de 8 duelos ganados, 4 intercepciones.", "commentator": "Tremblay otra vez."}')
    out, check = translate_fields(bad, fields, "es", m.all_names())
    assert check["translated"] is False and out == fields
    good = FakeLLM('{"casual": "Tremblay ha ganado 6 de sus 8 duelos.", "tactical": "Tremblay: 6 de 8 duelos ganados, 4 intercepciones.", "commentator": "Tremblay otra vez."}')
    out, check = translate_fields(good, fields, "es", m.all_names())
    assert check["translated"] is True and out["casual"].startswith("Tremblay ha ganado 6")
    renamed = FakeLLM('{"casual": "Garrow ha ganado 6 de sus 8 duelos.", "tactical": "Tremblay: 6 de 8 duelos ganados, 4 intercepciones.", "commentator": "Tremblay otra vez."}')
    out, check = translate_fields(renamed, fields, "es", m.all_names())
    assert check["translated"] is False
