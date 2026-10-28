"""Narrator agent: phrases a fact pack for the three lenses.

Live: the Foundry deployment writes the text under a system prompt that forbids any number
not in the fact pack. The checker verifies it, and on failure the issues are sent back for
at most two retries (3 calls per point). Fallback, or after the retries: the templates below.
Templates are themselves run through the checker, so a template bug cannot leak a number.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field

from .checker import CheckResult, check_lenses
from .llm import Foundry, LLMReply, parse_json_object

MAX_RETRIES = 2
LENSES = ("casual", "tactical", "commentator")

SYSTEM_PROMPT = """You are the narrator for Sightline, a second-screen layer for a football match.
You write three short texts from a FACT PACK and optional TRIVIA that code has already computed.

Hard rules:
1. You must not write any number that does not appear in the fact pack or the trivia. No counting,
   no rounding, no percentages, no minutes, no scores unless the exact value is given. Not even
   number words like "two". If in doubt, leave the number out.
2. You must not name any player, club, ground or person who is not listed under "names" or in the trivia.
3. Never invent facts. Every claim must follow from the fact pack.
4. No em dashes anywhere.

Lenses:
- casual: one or two plain sentences for a fan watching with friends. No jargon, no abbreviations
  (write "expected goals" not "xG", "goals" not "G"). Numbers are allowed but optional.
- tactical: one or two sentences that include the key numbers from the fact pack, written for a coach.
- commentator: exactly one line a commentator could say on air. Use a trivia fact if there is one.

Reply with a JSON object: {"casual": "...", "tactical": "...", "commentator": "..."}"""


@dataclass
class Narration:
    text: dict[str, str]
    check: CheckResult
    retries: int
    calls: list[LLMReply] = field(default_factory=list)
    source: str = "template"   # "llm" or "template"


def template_text(pack: dict, trivia: list[dict]) -> dict[str, str]:
    kind = pack["kind"]
    n = pack["numbers"]
    team = pack["team_name"]
    subj = pack.get("subject_name")
    sur = subj.split(" ")[-1] if subj else None
    tv = trivia[0]["text"] if trivia else None
    if kind == "anchor":
        casual = f"{sur} is holding the {team} defence together."
        tactical = (f"{subj}: {n['defensive_actions']} defensive actions, {n['margin_over_teammates']} more than any teammate, "
                    f"with {n['actions_lost']} lost.")
        comm = tv or f"{subj} is the wall {team} are building this one on."
    elif kind == "duel":
        casual = f"{sur} keeps getting the better of the defender in front of him."
        tactical = f"{subj}: {n['take_ons_won']} of {n['take_ons']} take-ons won"
        if "won_against_top_victim" in n:
            victim = [x for x in pack["names"] if x != subj and " " in x][:1]
            tactical += f", {n['won_against_top_victim']} of them against {victim[0]}" if victim else ""
        tactical += "."
        comm = tv or f"Every time {sur} runs at a defender the crowd rises."
    elif kind == "finishing":
        hot = n["goals_minus_xg"] > 0
        casual = (f"{team} are making the most of very little." if hot else f"{team} are wasting good chances.")
        tactical = f"{team}: {_plural(n['goals'], 'goal')} from {n['xg']:.2f} expected goals across {_plural(n['shots'], 'shot')}."
        comm = tv or (f"{team} have been clinical tonight." if hot else f"{team} will not want to see those misses again.")
    elif kind == "momentum":
        casual = f"{team} are on top right now and pushing the other side back."
        tactical = (f"{team} momentum {n['momentum_now']} after {n['momentum_previous']} in the previous window, "
                    f"{_plural(n['final_third_entries_5min'], 'final-third entry', 'final-third entries')} and "
                    f"{_plural(n['shots_5min'], 'shot')} in the last five minutes.")
        comm = tv or f"You can feel it in the ground: {team} have the momentum."
    elif kind == "score_state":
        hn, an, sl = pack["home_name"], pack["away_name"], pack["score_line"]
        if pack.get("leader"):
            lead_line = f"{max(n['home_goals'], n['away_goals'])}-{min(n['home_goals'], n['away_goals'])}"
            casual = f"{pack['leader_name']} lead {lead_line}."
        else:
            casual = f"It is level at {sl}."
        if pack.get("comeback"):
            casual += f" {pack['comeback_name']} have come back from {n['comeback_from_goals_down']} down."
        tactical = f"{hn} {sl} {an} after {n['minute']} minutes, {_plural(n['goals_so_far'], 'goal')} so far."
        comm = tv or (f"{pack['leader_name']} in front here at {sl}." if pack.get("leader") else f"All square at {sl}.")
    elif kind == "recap":
        return pack["template"]
    else:
        casual = tactical = comm = pack.get("summary", "")
    return {"casual": casual, "tactical": tactical, "commentator": comm}


def _plural(n, one: str, many: str | None = None) -> str:
    return f"{n} {one if n == 1 else (many or one + 's')}"


def _user_message(pack: dict, trivia: list[dict], issues: list[str] | None) -> str:
    slim = {k: v for k, v in pack.items() if k not in ("strength", "template")}
    msg = "FACT PACK (the only source of numbers and names):\n" + json.dumps(slim, indent=1)
    msg += "\n\nTRIVIA (may be quoted, numbers inside are allowed):\n" + (json.dumps(trivia, indent=1) if trivia else "none")
    if issues:
        msg += ("\n\nYour previous draft failed the checker. Fix every issue and reply again:\n- "
                + "\n- ".join(issues))
    return msg


def narrate(pack: dict, trivia: list[dict], foundry: Foundry | None) -> Narration:
    calls: list[LLMReply] = []
    issues: list[str] | None = None
    retries = 0
    if foundry is not None and foundry.configured:
        for attempt in range(MAX_RETRIES + 1):
            reply = foundry.chat(SYSTEM_PROMPT, _user_message(pack, trivia, issues))
            if reply is None:
                break
            calls.append(reply)
            obj = parse_json_object(reply.text) or {}
            text = {lens: str(obj.get(lens, "") or "").strip() for lens in LENSES}
            if not all(text.values()):
                issues = ["reply must be a JSON object with non-empty casual, tactical and commentator strings"]
            else:
                check = check_lenses(text, pack, trivia)
                if check.passed:
                    return Narration(text=text, check=check, retries=retries, calls=calls, source="llm")
                issues = check.issues
            retries += 1
    text = template_text(pack, trivia)
    check = check_lenses(text, pack, trivia)
    return Narration(text=text, check=check, retries=min(retries, MAX_RETRIES), calls=calls, source="template")
