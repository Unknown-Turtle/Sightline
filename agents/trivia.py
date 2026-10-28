"""Trivia agent: deterministic lookups in the history archive.

Every fact carries `source` (the CSV table) and `row` (a key into it). Nothing is invented:
if a lookup returns nothing, the agent returns nothing. Numbers in these facts are allowed
by the checker because they come straight from the archive rows.
"""
from __future__ import annotations

from .data import History, Match


def _h2h(hist: History, a: str, b: str) -> dict | None:
    for r in hist.rows("head_to_head"):
        if {r["club_a"], r["club_b"]} == {a, b}:
            return r
    return None


def _club(hist: History, cid: str) -> dict | None:
    for r in hist.rows("clubs"):
        if r["id"] == cid:
            return r
    return None


def _fact(text: str, source: str, row: str) -> dict:
    return {"text": text, "source": source, "row": row}


_MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September",
           "October", "November", "December"]


def _nice_date(iso: str) -> str:
    """'2026-05-10' to '10 May 2026' (the day and year stay as numbers the checker allows)."""
    try:
        y, mo, d = iso.split("-")
        return f"{int(d)} {_MONTHS[int(mo) - 1]} {y}"
    except (ValueError, IndexError):
        return iso


def _expand_ids(hist: History, text: str) -> str:
    """Replace club ids in an archive string ('HVL 1-1 ARD') with club names."""
    out = []
    for tok in text.split(" "):
        c = _club(hist, tok) if tok.isupper() and len(tok) == 3 else None
        out.append(c["name"] if c else tok)
    return " ".join(out)


def _nice_detail(hist: History, detail: str) -> str:
    """'2021-11-28 ARD 5-0 MCR' to 'Arden Athletic 5-0 Mallow City on 28 November 2021'."""
    parts = detail.split(" ", 1)
    if len(parts) == 2 and len(parts[0]) == 10 and parts[0][4] == "-":
        return f"{_expand_ids(hist, parts[1])} on {_nice_date(parts[0])}"
    return _expand_ids(hist, detail)


def head_to_head_facts(hist: History, m: Match) -> list[dict]:
    r = _h2h(hist, m.home, m.away)
    if not r:
        return []
    a_name, b_name = m.team_name(r["club_a"]), m.team_name(r["club_b"])
    facts = [_fact(
        f"{a_name} and {b_name} have met {r['played']} times in the last five seasons: "
        f"{r['a_wins']} {a_name} wins, {r['draws']} draws and {r['b_wins']} {b_name} wins.",
        "head_to_head.csv", f"{r['club_a']},{r['club_b']}")]
    if r.get("last_meeting"):
        facts.append(_fact(f"The last meeting finished {_expand_ids(hist, r['last_meeting'])} on {_nice_date(r['last_meeting_date'])}.",
                           "head_to_head.csv", f"{r['club_a']},{r['club_b']}"))
    return facts


def home_record_facts(hist: History, m: Match) -> list[dict]:
    rows = [r for r in hist.rows("results") if r["home_id"] == m.home and r["away_id"] == m.away]
    if not rows:
        return []
    wins = sum(1 for r in rows if int(r["home_goals"]) > int(r["away_goals"]))
    draws = sum(1 for r in rows if int(r["home_goals"]) == int(r["away_goals"]))
    losses = len(rows) - wins - draws
    return [_fact(
        f"At home to {m.team_name(m.away)} over the last five seasons, {m.team_name(m.home)} have won {wins}, "
        f"drawn {draws} and lost {losses} of {len(rows)} matches.",
        "results.csv", ";".join(r["match_id"] for r in rows))]


def comeback_facts(hist: History, m: Match, team: str, deficit: int) -> list[dict]:
    """How often the club has taken a point from a match it trailed by `deficit` at half time."""
    rows = hist.rows("results")
    trailed, recovered = 0, 0
    for r in rows:
        side = "home" if r["home_id"] == team else "away" if r["away_id"] == team else None
        if not side:
            continue
        ht_for = int(r["ht_home_goals"] if side == "home" else r["ht_away_goals"])
        ht_ag = int(r["ht_away_goals"] if side == "home" else r["ht_home_goals"])
        if ht_ag - ht_for >= deficit:
            trailed += 1
            ft_for = int(r["home_goals"] if side == "home" else r["away_goals"])
            ft_ag = int(r["away_goals"] if side == "home" else r["home_goals"])
            if ft_for >= ft_ag:
                recovered += 1
    if not trailed:
        return []
    return [_fact(
        f"In the last five seasons {m.team_name(team)} trailed by {deficit} or more at half time {trailed} times "
        f"and avoided defeat in {recovered} of them.",
        "results.csv", f"{team},ht_deficit>={deficit}")]


def scorer_facts(hist: History, m: Match, pid: str, opponent: str) -> list[dict]:
    rows = [r for r in hist.rows("scoring_timeline") if r["scorer_id"] == pid
            and (r["home_id"] == opponent or r["away_id"] == opponent)]
    if not rows:
        return []
    n = len(rows)
    return [_fact(
        f"{m.player_name(pid)} had scored {n} league goal{'s' if n != 1 else ''} against {m.team_name(opponent)} "
        f"in the five recorded seasons before today.",
        "scoring_timeline.csv", ";".join(r["match_id"] for r in rows))]


def milestone_facts(hist: History, m: Match, pid: str) -> list[dict]:
    facts = []
    for r in hist.rows("milestones_upcoming"):
        if r["player_id"] == pid:
            facts.append(_fact(
                f"{r['name']} is {r['remaining']} {r['metric']} away from {r['milestone']} career league {r['metric']}, "
                f"standing on {r['current']}.",
                "milestones_upcoming.csv", f"{pid},{r['metric']}"))
    return facts


def career_facts(hist: History, m: Match, pid: str) -> list[dict]:
    rows = [r for r in hist.rows("player_careers") if r["player_id"] == pid]
    if not rows:
        return []
    apps = sum(int(r["apps"]) for r in rows)
    goals = sum(int(r["goals"]) for r in rows)
    assists = sum(int(r["assists"]) for r in rows)
    clubs = []
    for r in rows:
        if r["club_id"] not in clubs:
            clubs.append(r["club_id"])
    text = f"{m.player_name(pid)} has {apps} league appearances, {goals} goals and {assists} assists over the five recorded seasons"
    if len(clubs) > 1:
        text += f", having joined {m.team_name(m.team_of(pid))} from {_club_name(hist, clubs[-2])}"
    return [_fact(text + ".", "player_careers.csv", f"{pid},{rows[0]['season']}..{rows[-1]['season']}")]


def _club_name(hist: History, cid: str) -> str:
    c = _club(hist, cid)
    return c["name"] if c else cid


def record_facts(hist: History, m: Match, team: str, records: tuple[str, ...]) -> list[dict]:
    facts = []
    for r in hist.rows("club_records"):
        if r["club_id"] == team and r["record"] in records:
            label = r["record"].replace("_", " ")
            detail = _nice_detail(hist, r["detail"]) if r["detail"] else ""
            facts.append(_fact(f"{m.team_name(team)}'s {label} over the last five seasons is {r['value']}"
                               + (f" ({detail})." if detail else "."),
                               "club_records.csv", f"{team},{r['record']}"))
    return facts


def attendance_facts(hist: History, m: Match) -> list[dict]:
    att = m.meta.get("attendance")
    for r in hist.rows("club_records"):
        if r["club_id"] == m.home and r["record"] == "record_home_attendance" and att:
            if int(att) >= int(r["value"]):
                return [_fact(f"Today's attendance of {att} equals the record crowd at {m.meta.get('venue', 'this ground')}.",
                              "club_records.csv", f"{m.home},record_home_attendance")]
            return [_fact(f"Today's crowd is {att}. The record at {m.meta.get('venue', 'this ground')} is {r['value']}, "
                          f"set at {_nice_detail(hist, r['detail'])}.",
                          "club_records.csv", f"{m.home},record_home_attendance")]
    return []


def trivia_for(hist: History | None, m: Match, pack: dict, max_facts: int = 3) -> list[dict]:
    """Facts relevant to a fact pack and the current score state. Returns [] when nothing applies."""
    if hist is None:
        return []
    kind = pack["kind"]
    facts: list[dict] = []
    if kind in ("anchor", "duel") and pack.get("subject"):
        facts += milestone_facts(hist, m, pack["subject"])
        facts += career_facts(hist, m, pack["subject"])
    elif kind == "finishing":
        facts += record_facts(hist, m, pack["team"], ("record_scorer",))
        facts += head_to_head_facts(hist, m)[:1]
    elif kind == "momentum":
        facts += record_facts(hist, m, pack["team"], ("longest_unbeaten_run",))
        facts += head_to_head_facts(hist, m)[1:2]
    elif kind == "score_state":
        if pack.get("comeback"):
            facts += comeback_facts(hist, m, pack["comeback"], pack["numbers"].get("comeback_from_goals_down", 1))
        for ev in pack["evidence_for"][-1:] + pack["evidence_against"][-1:]:
            pid = _pid_for_name(m, ev["player"])
            if pid:
                opp = m.away if m.team_of(pid) == m.home else m.home
                facts += scorer_facts(hist, m, pid, opp)
                facts += milestone_facts(hist, m, pid)
        facts += head_to_head_facts(hist, m)
        facts += home_record_facts(hist, m)
    elif kind == "recap":
        facts += head_to_head_facts(hist, m)
        facts += attendance_facts(hist, m)
    seen, out = set(), []
    for f in facts:
        key = (f["source"], f["row"], f["text"])
        if key not in seen:
            seen.add(key)
            out.append(f)
    return out[:max_facts]


def _pid_for_name(m: Match, name: str) -> str | None:
    for p in m.meta.get("players", []):
        if p["name"] == name:
            return p["id"]
    return None
