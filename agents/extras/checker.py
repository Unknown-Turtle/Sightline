"""The checker: every number and every name in model text must come from the computed results.

check_text(text, allowed_numbers, allowed_names, vocabulary) returns a list of issues (empty when the
text passes). Numbers are compared as strings after normalising (so "9.5", "9,5" and "9.50" match) and
also as floats to one decimal, so "0.56 xG" passes when 0.556 was computed and rounded to 0.56.
Names: any word in the match vocabulary (player names, surnames, club names) that is not in the
allowed set is an issue. Everyday small numbers that describe the window ("last 10 minutes") are
allowed through `allowed_numbers` too, the caller adds them.
"""
from __future__ import annotations

import re

NUM_RE = re.compile(r"(?<![A-Za-z_])[-+]?\d+(?:[.,]\d+)?(?:\s?%)?")
WORD_RE = re.compile(r"[A-Za-zÀ-ÿ'\-]+")


def _norm_num(s: str) -> str:
    s = s.replace(",", ".").replace("%", "").replace("+", "").strip()
    try:
        f = float(s)
    except ValueError:
        return s
    return f"{f:.3f}".rstrip("0").rstrip(".") if "." in f"{f}" else str(int(f))


def number_tokens(text: str) -> list[str]:
    return [m.group(0).strip() for m in NUM_RE.finditer(text)]


def allowed_number_set(values) -> set[str]:
    """Normalised strings for every number (and the numbers inside strings) in the computed values."""
    out: set[str] = set()
    for v in values:
        if isinstance(v, bool):
            continue
        if isinstance(v, (int, float)):
            out.add(_norm_num(str(v)))
            out.add(_norm_num(f"{float(v):.1f}"))
            out.add(_norm_num(f"{float(v):.2f}"))
            out.add(_norm_num(str(round(float(v)))))
            if 0 <= float(v) <= 1:
                out.add(_norm_num(str(round(float(v) * 100))))
        elif isinstance(v, str):
            for tok in number_tokens(v):
                out.add(_norm_num(tok))
    return out


def check_text(text: str, allowed_numbers: set[str], allowed_names: set[str], vocabulary: set[str]) -> list[str]:
    issues: list[str] = []
    for tok in number_tokens(text):
        n = _norm_num(tok)
        if n not in allowed_numbers:
            issues.append(f"number not in results: {tok}")
    words = WORD_RE.findall(text)
    # check single words and two-word sequences against the vocabulary
    cands = set(words) | {f"{a} {b}" for a, b in zip(words, words[1:])}
    for w in cands:
        if w in vocabulary and w not in allowed_names and not any(w in a for a in allowed_names):
            issues.append(f"name not in results: {w}")
    return sorted(set(issues))


def numbers_in(text: str) -> int:
    return len(number_tokens(text))
