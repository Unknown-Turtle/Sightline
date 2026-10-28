"""Checker agent: deterministic verification that narrated text only uses numbers and names
that appear in the fact pack or the trivia.

Numbers: every numeric token in the text (digits, decimals, percentages, scorelines like 2-1
and clocks like 72:36) and the number words one to twelve must match a value from the fact pack
or the trivia, at the precision the text uses. Names: every capitalised token that is not an
ordinary sentence word must be a word of a name listed in the fact pack or found in the trivia.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

NUMBER_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
                "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12}
# ordinary words that start sentences or are capitalised for other reasons
STOPWORDS = {
    "a", "an", "the", "and", "but", "or", "nor", "so", "yet", "for", "in", "on", "at", "to", "of", "by", "with",
    "from", "into", "over", "under", "after", "before", "between", "through", "it", "its", "it's", "they", "their",
    "them", "he", "his", "she", "her", "we", "our", "you", "your", "this", "that", "these", "those", "there", "here",
    "is", "are", "was", "were", "be", "been", "being", "has", "have", "had", "do", "does", "did", "not", "no",
    "yes", "if", "as", "than", "then", "when", "while", "where", "who", "what", "which", "how", "why", "all",
    "any", "both", "each", "few", "more", "most", "other", "some", "such", "only", "own", "same", "very", "just",
    "now", "still", "again", "once", "right", "left", "up", "down", "out", "off", "back", "ahead", "level",
    "goal", "goals", "shot", "shots", "half", "first", "second", "time", "minute", "minutes", "match", "game",
    "momentum", "pressure", "defence", "defense", "attack", "midfield", "keeper", "box", "chance", "chances",
    "expected", "actions", "record", "league", "season", "seasons", "home", "away", "today", "tonight", "early",
    "late", "big", "good", "better", "best", "well", "much", "many", "little", "less", "least", "last", "next",
    "new", "old", "long", "short", "high", "low", "top", "bottom", "full", "every", "another", "something",
    "nothing", "everything", "lead", "leads", "leading", "led", "trail", "trailing", "comeback", "draw", "level",
    "take", "takes", "taking", "won", "win", "wins", "lost", "loss", "losing", "making", "wasting", "holding",
    "keeps", "keep", "kept", "getting", "pushing", "finishing", "scoring", "scored", "score", "scores",
    "deficit", "despite", "even", "far", "already", "also", "too", "almost", "about", "around", "per", "versus",
    "against", "across", "since", "until", "because", "though", "although", "unless", "within", "without",
    "mr", "mrs", "ms", "dr", "sir", "x", "vs", "v", "one", "two", "three", "four", "five", "six", "seven",
    "eight", "nine", "ten", "eleven", "twelve", "arden", "hollow", "vale", "park", "th", "nd", "rd", "st",
    "points", "point", "times", "meeting", "meetings", "clean", "sheet", "possession", "control", "chaos",
    "territory", "entries", "entry", "final", "third", "thirds", "area", "penalty", "corner", "corners", "free",
    "kick", "kicks", "foul", "fouls", "card", "cards", "yellow", "red", "sub", "substitute", "bench", "starting",
    "lineup", "captain", "referee", "crowd", "stadium", "fans", "supporters", "side", "sides", "team", "teams",
    "club", "clubs", "player", "players", "man", "men", "boys", "lads", "visitors", "hosts", "on-air", "live",
    "whistle", "break", "interval", "period", "stoppage", "added", "extra", "regular", "normal", "quiet", "loud",
    "fast", "slow", "quick", "sharp", "tight", "open", "closed", "wide", "narrow", "deep", "direct", "sideways",
    "forward", "forwards", "backward", "backwards", "cross", "crosses", "pass", "passes", "passing", "carry",
    "carries", "dribble", "dribbles", "tackle", "tackles", "block", "blocks", "clearance", "clearances",
    "interception", "interceptions", "save", "saves", "saved", "xg", "duel", "duels", "anchor", "statistically",
    "roughly", "exactly", "nearly", "over", "clock", "shortly", "plus", "minus", "and", "percent", "%",
}
_PUNCT = ".,;:!?()[]{}\"'`"


@dataclass
class CheckResult:
    passed: bool
    numbers_checked: int
    names_checked: int
    issues: list[str] = field(default_factory=list)

    def as_dict(self, retries: int) -> dict:
        return {"passed": self.passed, "numbers_checked": self.numbers_checked, "retries": retries,
                "issues": list(self.issues)}


_NUM_RE = re.compile(r"(?<![A-Za-z_])(\d+(?:\.\d+)?)")
_CLOCK_RE = re.compile(r"\b\d{1,2}(?:\+\d{1,2})?:\d{2}\b")
_IDS_RE = re.compile(r"\b[A-Za-z]+_[A-Za-z0-9_]+\b")


def _walk_numbers(obj, out: set[float]) -> None:
    if isinstance(obj, bool):
        return
    if isinstance(obj, (int, float)):
        out.add(float(obj))
    elif isinstance(obj, dict):
        for k, v in obj.items():
            if k in ("event_id", "t", "strength"):
                continue
            _walk_numbers(v, out)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            _walk_numbers(v, out)
    elif isinstance(obj, str):
        for tok in _NUM_RE.findall(obj):
            out.add(float(tok))
        for word, value in NUMBER_WORDS.items():
            if re.search(rf"\b{word}\b", obj, flags=re.IGNORECASE):
                out.add(float(value))


def allowed_numbers(pack: dict, trivia: list[dict]) -> set[float]:
    """Every number a narrator may use: the fact pack's numbers block, evidence clocks and
    minutes, the score line, plus every number inside the trivia rows."""
    out: set[float] = set()
    _walk_numbers(pack.get("numbers", {}), out)
    for ev in pack.get("evidence_for", []) + pack.get("evidence_against", []):
        _walk_numbers({k: v for k, v in ev.items() if k != "event_id"}, out)
    for key in ("score_line", "xg_timeline", "score_numbers", "extra_numbers"):
        if key in pack:
            _walk_numbers(pack[key], out)
    for f in trivia:
        _walk_numbers(f.get("text", ""), out)
        _walk_numbers(f.get("row", ""), out)
    # ratios and percentages the narrator may legitimately derive from an allowed pair
    for v in list(out):
        if v > 1:
            out.add(round(v, 1))
    return out


def allowed_clocks(pack: dict) -> set[str]:
    clocks = {pack.get("clock", "")}
    for ev in pack.get("evidence_for", []) + pack.get("evidence_against", []):
        clocks.add(ev.get("clock", ""))
    return {c for c in clocks if c}


def allowed_name_tokens(pack: dict, trivia: list[dict]) -> set[str]:
    toks: set[str] = set()
    for n in pack.get("names", []):
        for w in n.replace("-", " ").split():
            toks.add(w.strip(_PUNCT).lower())
    for key in ("team_name", "subject_name", "leader_name", "comeback_name", "home_name", "away_name"):
        v = pack.get(key)
        if v:
            for w in str(v).split():
                toks.add(w.strip(_PUNCT).lower())
    for f in trivia:
        for w in f.get("text", "").replace("-", " ").split():
            w = w.strip(_PUNCT)
            if w[:1].isupper():
                toks.add(w.lower())
    toks.discard("")
    return toks


def _matches(value: float, text_token: str, allowed: set[float]) -> bool:
    dp = len(text_token.split(".")[1]) if "." in text_token else 0
    for a in allowed:
        if round(a, dp) == value or abs(a - value) < 1e-9:
            return True
    return False


def check_text(text: str, pack: dict, trivia: list[dict]) -> CheckResult:
    """Verify one narrated string against the fact pack and trivia."""
    issues: list[str] = []
    nums = allowed_numbers(pack, trivia)
    clocks = allowed_clocks(pack)
    names = allowed_name_tokens(pack, trivia)

    body = _IDS_RE.sub(" ", text)
    for c in _CLOCK_RE.findall(body):
        if c not in clocks:
            issues.append(f"clock {c} is not in the fact pack")
        body = body.replace(c, " ")
    n_checked = 0
    for tok in _NUM_RE.findall(body):
        n_checked += 1
        if not _matches(float(tok), tok, nums):
            issues.append(f"number {tok} is not in the fact pack or trivia")
    for word, value in NUMBER_WORDS.items():
        for m in re.finditer(rf"\b{word}\b", body, flags=re.IGNORECASE):
            after = body[m.end():m.end() + 12].lower()
            if after.startswith(" on one") or after.startswith("-on-one") or after.startswith(" of the"):
                continue
            n_checked += 1
            if float(value) not in nums:
                issues.append(f"number word '{word}' ({value}) is not in the fact pack or trivia")

    names_checked = 0
    sentences = re.split(r"(?<=[.!?])\s+", body)
    for s in sentences:
        words = s.split()
        for i, raw in enumerate(words):
            w = raw.strip(_PUNCT)
            if w.endswith("'s") or w.endswith("’s"):
                w = w[:-2]
            if not w or not w[:1].isupper() or not w[:1].isalpha():
                continue
            low = w.lower()
            if low in STOPWORDS or low in names:
                if low in names:
                    names_checked += 1
                continue
            if i == 0:
                # sentence-initial ordinary words are allowed, unless a second capitalised
                # non-stopword follows (that looks like a two-word name)
                nxt = words[1].strip(_PUNCT) if len(words) > 1 else ""
                if not (nxt[:1].isupper() and nxt.lower() not in STOPWORDS and nxt.lower() not in names):
                    continue
            names_checked += 1
            issues.append(f"name '{w}' is not in the fact pack or trivia")
    return CheckResult(passed=not issues, numbers_checked=n_checked, names_checked=names_checked, issues=issues)


def check_lenses(texts: dict[str, str], pack: dict, trivia: list[dict]) -> CheckResult:
    """Check casual, tactical and commentator text together."""
    total_n, total_names, issues = 0, 0, []
    for lens, text in texts.items():
        r = check_text(text or "", pack, trivia)
        total_n += r.numbers_checked
        total_names += r.names_checked
        issues += [f"{lens}: {i}" for i in r.issues]
    return CheckResult(passed=not issues, numbers_checked=total_n, names_checked=total_names, issues=issues)
