"""Translations of insights.json: every `text` field is translated by the model, numbers and names must
survive unchanged (the checker runs on each translation), and in fallback mode the files carry the English
text with "translated": false so the viewer can say so.

Output: viewer/public/data/insights.<lang>.json, same shape as insights.json plus:
  "lang", "translated" (true when every item was translated and checked), "source": "insights.json",
  and per item "translated": bool and "check" (numbers_checked, issues).
"""
from __future__ import annotations

import json
from pathlib import Path

from .checker import allowed_number_set, check_text, number_tokens, numbers_in
from .common import Match, VIEWER_DATA, write_json
from .llm import LLM

LANG_NAMES = {"es": "Spanish", "fr": "French", "pt": "Portuguese", "ar": "Arabic", "de": "German", "it": "Italian"}

TRANSLATE_SYSTEM = """You translate short football commentary into {lang}. Keep every number exactly as written (same digits,
same decimal point) and keep every player and club name exactly as written. Do not add or drop any number or name.
Return JSON only, with the same keys as the input."""


def names_in(text: str, vocab: set[str]) -> set[str]:
    return {n for n in vocab if n in text}


def translate_fields(llm: LLM, fields: dict[str, str], lang: str, vocab: set[str]) -> tuple[dict[str, str], dict]:
    """Translate one item's text fields. Returns (fields, check) where check lists any issues; on failure after
    one retry the English text is returned with translated=False."""
    allowed_nums = allowed_number_set(list(fields.values()))
    required_nums = {tok for v in fields.values() for tok in number_tokens(v)}
    allowed_names = set()
    for v in fields.values():
        allowed_names |= names_in(v, vocab)
    issues: list[str] = []
    receipt = {"latency_ms": 0, "tokens_in": 0, "tokens_out": 0}
    for attempt in range(2):
        user = json.dumps(fields, ensure_ascii=False)
        if issues:
            user += "\nThe previous translation was rejected: " + "; ".join(issues) + ". Keep every number and name unchanged."
        try:
            data, res = llm.chat_json(TRANSLATE_SYSTEM.format(lang=LANG_NAMES.get(lang, lang)), user, max_tokens=600)
        except Exception as exc:
            return dict(fields), {"passed": False, "translated": False, "numbers_checked": 0, "retries": attempt, "issues": [f"transport: {str(exc)[:120]}"], **receipt}
        for k in receipt:
            receipt[k] += res.get(k, 0)
        if not data or set(data) != set(fields) or not all(isinstance(v, str) for v in data.values()):
            issues = ["response did not keep the same keys"]
            continue
        issues = []
        for k, v in data.items():
            issues += [f"{k}: {i}" for i in check_text(v, allowed_nums, allowed_names, vocab)]
            missing = {tok for tok in number_tokens(fields[k])} - set(number_tokens(v))
            if missing:
                issues.append(f"{k}: numbers dropped: {', '.join(sorted(missing))}")
            for name in names_in(fields[k], vocab):
                if name not in v and not any(name in w for w in allowed_names if w in v):
                    issues.append(f"{k}: name dropped: {name}")
        if not issues:
            return data, {"passed": True, "translated": True, "numbers_checked": sum(numbers_in(v) for v in data.values()), "retries": attempt, "issues": [], **receipt}
    return dict(fields), {"passed": False, "translated": False, "numbers_checked": len(required_nums), "retries": 2, "issues": issues, **receipt}


def translate_insights(match: Match, insights: dict, lang: str, llm: LLM | None = None) -> dict:
    llm = llm or LLM()
    vocab = match.all_names()
    out = {k: v for k, v in insights.items() if k != "items"}
    out.update(lang=lang, source="insights.json", translation_mode=llm.mode, translation_model=llm.model)
    items = []
    all_ok = llm.available
    for item in insights.get("items", []):
        new = dict(item)
        text = item.get("text") or {}
        if llm.available and text:
            fields, check = translate_fields(llm, {k: v for k, v in text.items() if isinstance(v, str)}, lang, vocab)
            new["text"] = {**text, **fields}
            new["translated"] = check["translated"]
            new["translation_check"] = {k: check[k] for k in ("passed", "numbers_checked", "retries", "issues")}
            all_ok = all_ok and check["translated"]
        else:
            new["translated"] = False
            new["translation_check"] = {"passed": True, "numbers_checked": 0, "retries": 0, "issues": ["fallback mode: English text kept"]}
        items.append(new)
    out["items"] = items
    out["translated"] = bool(items) and all_ok
    if not llm.available:
        out["note"] = "No Foundry configuration: English text kept, translated is false on every item."
    return out


def write_translations(match: Match, src: Path, out_dir: Path = VIEWER_DATA, langs=("es", "fr", "pt", "ar")) -> dict[str, str]:
    llm = LLM()
    if src.exists():
        insights = json.load(open(src, encoding="utf-8"))
    else:
        insights = {"match_id": match.match_id, "generated_at": None, "mode": "fallback", "model": None, "items": [],
                    "note": f"{src.name} was not present when translations ran; rerun python -m agents.extras translate once it exists"}
    results = {}
    for lang in langs:
        data = translate_insights(match, insights, lang, llm)
        write_json(out_dir / f"insights.{lang}.json", data)
        n = len(data["items"])
        done = sum(1 for i in data["items"] if i.get("translated"))
        results[lang] = f"{done}/{n} items translated, mode {llm.mode}" + ("" if src.exists() else " (no insights.json yet)")
    return results
