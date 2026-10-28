"""Claim checker: a pundit-style claim is classified into a testable type, deterministic code runs that
type's statistical tests over StatsEngine snapshots and events up to time t, and a narrator phrases the
verdict per lens. The checker rejects any number or name in the narration that is not in the test results.

Pipeline: classify (model with keyword fallback) -> run_tests (code) -> verdict (code) -> narrate (model or
template) -> check (code, retry once, then template).
"""
from __future__ import annotations

import json
import re
import time
from functools import lru_cache
from pathlib import Path

from .checker import allowed_number_set, check_text, numbers_in
from .common import Match, VIEWER_DATA, rel_x, write_json
from .llm import LLM
from .ratings import compute_ratings, rating_at

CLAIM_TYPES = [
    "momentum_lost", "momentum_gained", "dominance", "pressing_working", "pressing_failing",
    "duel_winning", "duel_losing", "player_big_game", "player_poor_game",
    "finishing_unlucky", "finishing_wasteful", "defensive_collapse", "tiredness", "out_of_scope",
]
WINDOW_S = 600.0        # "recently" means the last 10 minutes of match time
COLLAPSE_S = 900.0      # defensive collapse looks at the last 15 minutes
TYPE_LABEL = {
    "momentum_lost": "lost momentum", "momentum_gained": "gained momentum", "dominance": "are in control",
    "pressing_working": "press is working", "pressing_failing": "press is failing",
    "duel_winning": "is winning the duel", "duel_losing": "is losing the duel",
    "player_big_game": "is having a big game", "player_poor_game": "is having a poor game",
    "finishing_unlucky": "have been unlucky in front of goal", "finishing_wasteful": "have been wasteful in front of goal",
    "defensive_collapse": "defence has collapsed", "tiredness": "are tiring",
}

# ------------------------------------------------------------------ classification
KEYWORDS: list[tuple[str, list[str]]] = [
    ("tiredness", ["tired", "tiring", "legs have gone", "fatigue", "running on empty", "leggy", "exhausted"]),
    ("defensive_collapse", ["collapse", "collapsed", "fallen apart", "falling apart", "defence has gone", "defense has gone", "shambles", "all over the place at the back"]),
    ("finishing_unlucky", ["unlucky", "deserved a goal", "deserve more", "should be ahead", "keeper has kept them", "no luck"]),
    ("finishing_wasteful", ["wasteful", "profligate", "should have scored", "missed chances", "wasted", "squandered", "should have buried"]),
    ("pressing_failing", ["press is not working", "press isnt working", "press not working", "press failing", "press has stopped", "playing through the press", "press is failing", "pressing is failing", "press has gone"]),
    ("pressing_working", ["press is working", "press working", "press works", "pressing works", "pressing well", "pressing is working", "press has worked", "winning it high", "winning the ball high", "pressing them"]),
    ("momentum_lost", ["lost momentum", "momentum has gone", "momentum gone", "no momentum", "momentum is gone", "lost their way", "run out of steam", "gone flat", "momentum has gone", "lost control", "lost their grip", "taken their foot off"]),
    ("momentum_gained", ["momentum now", "momentum is with", "gained momentum", "got the momentum", "on top now", "in the ascendancy", "wind in their sails", "turned the tide", "coming back", "growing into"]),
    ("duel_losing", ["losing the duel", "losing his battle", "losing the battle", "being beaten by", "getting the better of him", "is in his pocket", "can't handle", "struggling against", "struggling with"]),
    ("duel_winning", ["winning the duel", "winning his battle", "winning the battle", "got the better of", "getting the better of", "in his pocket", "beating", "handling", "dealing with"]),
    ("player_poor_game", ["poor game", "nightmare", "struggling", "anonymous", "shocker", "stinker", "terrible", "off the pace", "not at the races", "poor night", "bad game"]),
    ("player_big_game", ["big game", "huge game", "superb", "man of the match", "outstanding", "brilliant", "immense", "running the game", "running the show", "best player", "great game", "excellent"]),
    ("dominance", ["dominating", "dominant", "in control", "controlling", "bossing", "running this", "on top", "dominance", "all over them", "comfortable"]),
]


def find_entities(match: Match, claim: str) -> dict:
    """Deterministic team and player mentions in the claim text."""
    low = claim.lower()
    teams = []
    for tid, name in match.team_names.items():
        words = [name.lower()] + [w for w in name.lower().split() if len(w) > 3] + [tid.lower()]
        if any(re.search(r"\b" + re.escape(w) + r"\b", low) for w in words):
            teams.append(tid)
    players = []
    for pid, p in match.players.items():
        full, sur = p["name"].lower(), p["name"].split(" ")[-1].lower()
        if re.search(r"\b" + re.escape(full) + r"\b", low) or re.search(r"\b" + re.escape(sur) + r"\b", low) or pid.lower() in low:
            if pid not in players:
                players.append(pid)
    # keep mention order
    players.sort(key=lambda pid: min(low.find(match.players[pid]["name"].split(" ")[-1].lower()) % 10_000, low.find(pid.lower()) % 10_000))
    return {"teams": teams, "players": players}


FILLER = re.compile(r"\b(all|any|finally|really|completely|totally|absolutely|clearly|just|now|their|the|his|a|an|of|this|that|tonight|today|so|very|quite|simply)\b")


def _norm_claim(text: str) -> str:
    return " " + re.sub(r"\s+", " ", FILLER.sub(" ", text.lower().replace("'s ", " ").replace("'", ""))).strip() + " "


def classify_keywords(match: Match, claim: str) -> dict:
    low = _norm_claim(claim)
    ents = find_entities(match, claim)
    ctype = "out_of_scope"
    for name, words in KEYWORDS:
        if any(_norm_claim(w).strip() and _norm_claim(w) in low for w in words):
            ctype = name
            break
    if ctype in ("duel_winning", "duel_losing") and len(ents["players"]) < 1:
        ctype = "out_of_scope" if not ents["teams"] else ctype
    if ctype == "dominance" and ents["players"] and not ents["teams"]:
        ctype = "player_big_game"
    if ctype in ("player_big_game", "player_poor_game") and not ents["players"]:
        ctype = "dominance" if ctype == "player_big_game" else "momentum_lost"
    return {"type": ctype, "teams": ents["teams"], "players": ents["players"], "via": "keywords"}


CLASSIFY_SYSTEM = """You classify football pundit claims about one match into exactly one testable claim type.
Types: momentum_lost, momentum_gained, dominance, pressing_working, pressing_failing, duel_winning, duel_losing,
player_big_game, player_poor_game, finishing_unlucky, finishing_wasteful, defensive_collapse, tiredness, out_of_scope.
Use out_of_scope for anything not about this match's play (referees, transfers, the league table, predictions, opinions on fans).
Answer with JSON only: {"type": "...", "teams": ["team id"], "players": ["player id"]} using only the ids given."""


def classify(match: Match, claim: str, llm: LLM | None = None) -> dict:
    kw = classify_keywords(match, claim)
    if llm is None or not llm.available:
        return kw
    roster = {tid: {"name": match.team_name(tid), "players": {pid: match.name(pid) for pid, team in match.team_of.items() if team == tid}} for tid in match.teams}
    try:
        data, _ = llm.chat_json(CLASSIFY_SYSTEM, json.dumps({"claim": claim, "teams": roster}), max_tokens=120, temperature=0.0)
    except Exception:
        data = None
    if not data or data.get("type") not in CLAIM_TYPES:
        return kw
    teams = [t for t in (data.get("teams") or []) if t in match.teams] or kw["teams"]
    players = [p for p in (data.get("players") or []) if p in match.players] or kw["players"]
    return {"type": data["type"], "teams": teams, "players": players, "via": "model"}


# ------------------------------------------------------------------ tests
def _test(name, value, passes, for_ids=(), against_ids=(), **nums):
    return {"name": name, "value": value, "passes": bool(passes), "evidence_for": list(for_ids)[:6],
            "evidence_against": list(against_ids)[:6], "numbers": {k: v for k, v in nums.items()}}


def _per10(v: float, t: float) -> float:
    return v / max(t, 60.0) * 600.0


def _share(a, b):
    return a / (a + b) if (a + b) > 0 else 0.5


def _r(x, d=1):
    return round(float(x), d)


@lru_cache(maxsize=8)
def _ratings_for(match_id: str, match_dir: str):
    return compute_ratings(Match(match_dir, frames=False))


class Context:
    """Engine snapshots at t and at t minus the window, plus the window's events."""

    def __init__(self, match: Match, t: float, window: float = WINDOW_S):
        self.m = match
        self.t = min(t, match.duration)
        self.t0 = max(0.0, self.t - window)
        self.window = self.t - self.t0
        self.now = match.engine_at(self.t)
        self.then = match.engine_at(self.t0)
        self.snap = self.now.snapshot(at=self.t)
        self.evs = match.between(self.t0, self.t)
        self.all = match.upto(self.t)
        self.ratings = _ratings_for(match.match_id, str(match.dir))

    def team_delta(self, team: str, key: str) -> float:
        return self.now.t[team][key] - self.then.t[team][key]

    def player_delta(self, pid: str, key: str) -> float:
        a = self.now.p.get(pid, {}).get(key, 0.0)
        b = self.then.p.get(pid, {}).get(key, 0.0)
        return a - b

    def ids(self, pred, team=None, player=None, n=6, window=True):
        src = self.evs if window else self.all
        out = [e["event_id"] for e in src if (team is None or e["team_id"] == team) and (player is None or e["player_id"] == player) and pred(e)]
        return out[-n:]


def _default_team(ctx: Context, ctype: str, teams: list[str]) -> str:
    if teams:
        return teams[0]
    m = ctx.m
    mom = {t: ctx.snap["teams"][t]["last_5_min"]["momentum"] for t in m.teams}
    if ctype in ("momentum_lost", "tiredness", "defensive_collapse", "pressing_failing", "finishing_wasteful", "finishing_unlucky"):
        if ctype == "defensive_collapse":
            goals = [e for e in ctx.all if e["type"] == "goal"]
            return m.other(goals[-1]["team_id"]) if goals else m.home
        return min(m.teams, key=lambda t: mom[t])
    return max(m.teams, key=lambda t: mom[t])


def tests_momentum(ctx: Context, team: str, lost: bool) -> list[dict]:
    m, t = ctx.m, ctx.t
    opp = m.other(team)
    now, then = ctx.now.t[team], ctx.then.t[team]
    out = []
    # 1 final-third entries, last 10 vs match average per 10 min
    recent = ctx.team_delta(team, "final_third_entries")
    avg = _per10(now["final_third_entries"], t)
    out.append(_test("final-third entries, last 10 min vs match average", f"{int(recent)} vs {_r(avg)} per 10 min",
                     (recent < 0.75 * avg) if lost else (recent > 1.25 * avg),
                     ctx.ids(lambda e: e["type"] == "pass" and e["outcome"] == "complete" and e["extra"].get("into_final_third"), team=opp if lost else team),
                     ctx.ids(lambda e: e["type"] == "pass" and e["outcome"] == "complete" and e["extra"].get("into_final_third"), team=team if lost else opp),
                     recent=int(recent), average=_r(avg)))
    # 2 xG rate
    rx, ax = ctx.team_delta(team, "xg"), _per10(now["xg"], t)
    out.append(_test("xG, last 10 min vs match average", f"{_r(rx, 2)} vs {_r(ax, 2)} per 10 min",
                     (rx < 0.75 * ax) if lost else (rx > 1.25 * ax),
                     ctx.ids(lambda e: e["type"] == "shot", team=opp if lost else team),
                     ctx.ids(lambda e: e["type"] == "shot", team=team if lost else opp), recent=_r(rx, 2), average=_r(ax, 2)))
    # 3 territory share last 10 vs opponent
    terr = _share(ctx.team_delta(team, "opp_half_touches"), ctx.team_delta(opp, "opp_half_touches"))
    out.append(_test("territory, last 10 min (share of touches in the opponent half)", f"{int(round(terr * 100))}% vs {int(round((1 - terr) * 100))}% for {m.team_name(opp)}",
                     (terr < 0.45) if lost else (terr > 0.55), [], [], share=int(round(terr * 100))))
    # 4 field tilt last 10 vs match
    tilt_now = _share(ctx.team_delta(team, "final_third_touches"), ctx.team_delta(opp, "final_third_touches"))
    tilt_match = _share(now["final_third_touches"], ctx.now.t[opp]["final_third_touches"])
    out.append(_test("field tilt, last 10 min vs match", f"{int(round(tilt_now * 100))}% vs {int(round(tilt_match * 100))}%",
                     (tilt_now < tilt_match - 0.05) if lost else (tilt_now > tilt_match + 0.05), [], [],
                     recent=int(round(tilt_now * 100)), match=int(round(tilt_match * 100))))
    # 5 momentum index last 5 min
    mom = ctx.snap["teams"][team]["last_5_min"]["momentum"]
    out.append(_test("momentum index, last 5 min (0 to 100)", f"{mom}", (mom < 45) if lost else (mom > 55), [], [], momentum=mom))
    return out


def tests_dominance(ctx: Context, team: str) -> list[dict]:
    m = ctx.m
    opp = m.other(team)
    poss = _share(ctx.team_delta(team, "possession_time_s"), ctx.team_delta(opp, "possession_time_s"))
    out = [_test("possession, last 10 min", f"{int(round(poss * 100))}% vs {int(round((1 - poss) * 100))}%", poss > 0.55, [], [], share=int(round(poss * 100)))]
    tilt = _share(ctx.team_delta(team, "final_third_touches"), ctx.team_delta(opp, "final_third_touches"))
    out.append(_test("field tilt, last 10 min", f"{int(round(tilt * 100))}%", tilt > 0.55, [], [], tilt=int(round(tilt * 100))))
    s1, s2 = int(ctx.team_delta(team, "shots")), int(ctx.team_delta(opp, "shots"))
    out.append(_test("shots, last 10 min vs opponent", f"{s1} vs {s2}", s1 > s2,
                     ctx.ids(lambda e: e["type"] == "shot", team=team), ctx.ids(lambda e: e["type"] == "shot", team=opp), team=s1, opponent=s2))
    x1, x2 = ctx.team_delta(team, "xg"), ctx.team_delta(opp, "xg")
    out.append(_test("xG, last 10 min vs opponent", f"{_r(x1, 2)} vs {_r(x2, 2)}", x1 > x2, [], [], team=_r(x1, 2), opponent=_r(x2, 2)))
    ctrl = ctx.snap["teams"][team]["last_5_min"]["control"]
    out.append(_test("control index, last 5 min (0 to 100)", f"{ctrl}", ctrl > 60, [], [], control=ctrl))
    return out


def tests_pressing(ctx: Context, team: str, working: bool) -> list[dict]:
    m, t = ctx.m, ctx.t
    opp = m.other(team)
    now = ctx.now.t[team]
    pa, da = ctx.team_delta(team, "ppda_passes_allowed"), ctx.team_delta(team, "ppda_defensive_actions")
    ppda_recent = pa / da if da else 99.0
    ppda_match = now["ppda_passes_allowed"] / now["ppda_defensive_actions"] if now["ppda_defensive_actions"] else 99.0
    out = [_test("PPDA, last 10 min vs match (lower is a stronger press)", f"{_r(ppda_recent)} vs {_r(ppda_match)}",
                 (ppda_recent < 0.85 * ppda_match) if working else (ppda_recent > 1.15 * ppda_match), [], [], recent=_r(ppda_recent), match=_r(ppda_match))]
    ht, ha = ctx.team_delta(team, "high_turnovers"), _per10(now["high_turnovers"], t)
    regain = lambda e: e["type"] in ("tackle", "interception", "ball_recovery") and (e["outcome"] in ("won", None)) and rel_x(e["start"]["x"], e["attack_dir"]) >= 65
    out.append(_test("high turnovers, last 10 min vs match average", f"{int(ht)} vs {_r(ha)} per 10 min",
                     (ht >= max(1, ha)) if working else (ht < 0.75 * ha), ctx.ids(regain, team=team) if working else [], [] if working else ctx.ids(regain, team=team),
                     recent=int(ht), average=_r(ha)))
    cp, ca = ctx.team_delta(team, "counter_press_regains"), _per10(now["counter_press_regains"], t)
    out.append(_test("counter-press regains, last 10 min vs match average", f"{int(cp)} vs {_r(ca)} per 10 min",
                     (cp >= max(1, ca)) if working else (cp < 0.75 * ca), [], [], recent=int(cp), average=_r(ca)))
    op, oc = ctx.team_delta(opp, "passes"), ctx.team_delta(opp, "passes_completed")
    acc_recent = oc / op if op else 0.0
    on = ctx.now.t[opp]
    acc_match = on["passes_completed"] / on["passes"] if on["passes"] else 0.0
    out.append(_test(f"{m.team_name(opp)} pass accuracy, last 10 min vs match", f"{int(round(acc_recent * 100))}% vs {int(round(acc_match * 100))}%",
                     (acc_recent < acc_match - 0.03) if working else (acc_recent > acc_match + 0.03),
                     ctx.ids(lambda e: e["type"] == "pass" and e["outcome"] != "complete", team=opp) if working else ctx.ids(lambda e: e["type"] == "pass" and e["outcome"] == "complete" and e["extra"].get("progressive"), team=opp),
                     [], recent=int(round(acc_recent * 100)), match=int(round(acc_match * 100))))
    pr, pavg = ctx.team_delta(team, "pressures"), _per10(now["pressures"], t)
    out.append(_test("pressures, last 10 min vs match average", f"{int(pr)} vs {_r(pavg)} per 10 min",
                     (pr >= 0.9 * pavg) if working else (pr < 0.75 * pavg), [], [], recent=int(pr), average=_r(pavg)))
    return out


def duel_events(ctx: Context, a: str, b: str) -> tuple[list[dict], list[dict]]:
    """Events up to t where a beat b (wins) and where b beat a (losses)."""
    wins, losses = [], []
    for e in ctx.all:
        x = e.get("extra") or {}
        pid, oppo = e.get("player_id"), x.get("opponent_id")
        pair = {pid, oppo}
        if pair != {a, b}:
            if e["type"] == "foul" and {pid, x.get("fouled_player_id")} == {a, b}:
                (wins if x.get("fouled_player_id") == a else losses).append(e)
            continue
        if e["type"] == "tackle":
            winner = pid if e["outcome"] == "won" else oppo
        elif e["type"] == "take_on":
            winner = pid if e["outcome"] == "success" else oppo
        elif e["type"] == "aerial_duel":
            winner = pid
        else:
            continue
        (wins if winner == a else losses).append(e)
    return wins, losses


def _opponent_for_duel(ctx: Context, a: str) -> str | None:
    counts: dict[str, int] = {}
    for e in ctx.all:
        x = e.get("extra") or {}
        if e["type"] in ("tackle", "take_on", "aerial_duel") and x.get("opponent_id"):
            if e["player_id"] == a:
                counts[x["opponent_id"]] = counts.get(x["opponent_id"], 0) + 1
            elif x["opponent_id"] == a:
                counts[e["player_id"]] = counts.get(e["player_id"], 0) + 1
    return max(counts, key=lambda k: (counts[k], k)) if counts else None


def tests_duel(ctx: Context, a: str, b: str, winning: bool) -> list[dict]:
    m = ctx.m
    wins, losses = duel_events(ctx, a, b)
    w_ids, l_ids = [e["event_id"] for e in wins], [e["event_id"] for e in losses]
    out = [_test(f"duels won, {m.surname(a)} vs {m.surname(b)}", f"{len(wins)} vs {len(losses)}",
                 (len(wins) > len(losses)) if winning else (len(wins) < len(losses)), w_ids if winning else l_ids, l_ids if winning else w_ids, a=len(wins), b=len(losses))]
    for kind, label in (("tackle", "tackles"), ("take_on", "take-ons"), ("aerial_duel", "aerial duels")):
        kw = [e for e in wins if e["type"] == kind]
        kl = [e for e in losses if e["type"] == kind]
        if kw or kl:
            out.append(_test(f"{label} between them won", f"{len(kw)} vs {len(kl)}", (len(kw) > len(kl)) if winning else (len(kw) < len(kl)),
                             [e["event_id"] for e in (kw if winning else kl)], [e["event_id"] for e in (kl if winning else kw)], a=len(kw), b=len(kl)))
    fouls = [e for e in wins + losses if e["type"] == "foul"]
    if fouls:
        fa = sum(1 for e in fouls if e["extra"].get("fouled_player_id") == a)
        out.append(_test(f"fouls won by {m.surname(a)} vs by {m.surname(b)}", f"{fa} vs {len(fouls) - fa}", (fa > len(fouls) - fa) if winning else (fa < len(fouls) - fa),
                         [], [], a=fa, b=len(fouls) - fa))
    return out


KEY_ACTIONS = lambda e: (e["type"] == "shot" and e["outcome"] == "goal") or (e["type"] == "tackle" and e["outcome"] == "won") or \
    e["type"] in ("interception", "block", "clearance") or (e["type"] == "take_on" and e["outcome"] == "success") or \
    (e["type"] == "pass" and e["extra"].get("key_pass"))
LOSSES = lambda e: (e["type"] == "pass" and e["outcome"] != "complete") or (e["type"] == "carry" and e["outcome"] == "dispossessed") or \
    (e["type"] == "take_on" and e["outcome"] == "fail") or e["type"] in ("dribbled_past", "foul")


def tests_player_game(ctx: Context, pid: str, big: bool) -> list[dict]:
    m = ctx.m
    team = m.team_of[pid]
    entry = rating_at(ctx.ratings, pid, ctx.t)
    rating = entry["rating"] if entry else 6.0
    team_ratings = {p: (rating_at(ctx.ratings, p, ctx.t) or {}).get("rating") for p, tm in m.team_of.items() if tm == team}
    team_ratings = {p: r for p, r in team_ratings.items() if r is not None}
    rank = 1 + sum(1 for r in team_ratings.values() if r > rating)
    rank_low = 1 + sum(1 for r in team_ratings.values() if r < rating)
    out = [_test(f"match rating for {m.surname(pid)} (team rank of {len(team_ratings)})", f"{rating} (rank {rank})",
                 (rating >= 7.0 and rank <= 3) if big else (rating <= 5.6 and rank_low <= 3), [], [], rating=rating, rank=rank, rank_low=rank_low)]
    ps = ctx.now.p.get(pid, {})
    contrib = int(ps.get("goals", 0) + ps.get("assists", 0) + ps.get("key_passes", 0) + ps.get("tackles_won", 0) + ps.get("interceptions", 0) + ps.get("blocks", 0) + ps.get("take_ons_won", 0))
    avg = sum(int(q.get("goals", 0) + q.get("assists", 0) + q.get("key_passes", 0) + q.get("tackles_won", 0) + q.get("interceptions", 0) + q.get("blocks", 0) + q.get("take_ons_won", 0))
              for p, q in ctx.now.p.items() if m.team_of.get(p) == team) / max(1, len([p for p in ctx.now.p if m.team_of.get(p) == team]))
    out.append(_test("key actions (goals, assists, key passes, tackles won, interceptions, blocks, take-ons won) vs team average", f"{contrib} vs {_r(avg)}",
                     (contrib >= 1.5 * avg and contrib >= 4) if big else (contrib <= 0.6 * avg), ctx.ids(KEY_ACTIONS, player=pid, window=False) if big else [],
                     [] if big else ctx.ids(KEY_ACTIONS, player=pid, window=False), player=contrib, team_average=_r(avg)))
    losses = int(ps.get("dispossessed", 0) + ps.get("dribbled_past", 0) + ps.get("fouls_committed", 0) + (ps.get("passes", 0) - ps.get("passes_completed", 0)) + (ps.get("take_ons", 0) - ps.get("take_ons_won", 0)))
    lavg = sum(int(q.get("dispossessed", 0) + q.get("dribbled_past", 0) + q.get("fouls_committed", 0) + (q.get("passes", 0) - q.get("passes_completed", 0)) + (q.get("take_ons", 0) - q.get("take_ons_won", 0)))
               for p, q in ctx.now.p.items() if m.team_of.get(p) == team) / max(1, len([p for p in ctx.now.p if m.team_of.get(p) == team]))
    out.append(_test("possession losses (passes lost, dispossessed, beaten, fouls) vs team average", f"{losses} vs {_r(lavg)}",
                     (losses <= lavg) if big else (losses >= 1.3 * lavg), [] if big else ctx.ids(LOSSES, player=pid, window=False),
                     ctx.ids(LOSSES, player=pid, window=False) if big else [], player=losses, team_average=_r(lavg)))
    ga = int(ps.get("goals", 0) + ps.get("assists", 0))
    out.append(_test("goals and assists", f"{int(ps.get('goals', 0))} goals, {int(ps.get('assists', 0))} assists", (ga >= 1) if big else (ga == 0),
                     ctx.ids(lambda e: e["type"] == "shot" and e["outcome"] == "goal", player=pid, window=False), [], goals=int(ps.get("goals", 0)), assists=int(ps.get("assists", 0))))
    return out


def tests_finishing(ctx: Context, team: str | None, pid: str | None, unlucky: bool) -> list[dict]:
    m = ctx.m
    if pid:
        s = ctx.now.p.get(pid, {})
        who = m.surname(pid)
        shots = [e for e in ctx.all if e["type"] == "shot" and e["player_id"] == pid]
    else:
        s = ctx.now.t[team]
        who = m.team_name(team)
        shots = [e for e in ctx.all if e["type"] == "shot" and e["team_id"] == team]
    goals, xg = int(s.get("goals", 0)), float(s.get("xg", 0.0))
    on_t, n = int(s.get("shots_on_target", 0)), int(s.get("shots", 0))
    bc = [e for e in shots if e["extra"].get("xg", 0) >= 0.35]
    bc_missed = [e for e in bc if e["outcome"] != "goal"]
    saved = [e for e in shots if e["outcome"] == "saved"]
    misses = [e for e in shots if e["outcome"] == "off_target"]
    gid = [e["event_id"] for e in shots if e["outcome"] == "goal"]
    out = [_test(f"goals vs xG for {who}", f"{goals} from {_r(xg, 2)} xG ({n} shots)", goals < xg - 0.4, [e["event_id"] for e in (saved if unlucky else misses)], gid, goals=goals, xg=_r(xg, 2), shots=n)]
    out.append(_test("big chances missed (xG 0.35 or more)", f"{len(bc_missed)} of {len(bc)}", (len(bc_missed) == 0 or len(bc_missed) < len(bc) / 2) if unlucky else len(bc_missed) >= 1,
                     [] if unlucky else [e["event_id"] for e in bc_missed], [e["event_id"] for e in bc_missed] if unlucky else [], missed=len(bc_missed), total=len(bc)))
    share = on_t / n if n else 0.0
    out.append(_test("shots on target share", f"{on_t} of {n} ({int(round(share * 100))}%)", (share >= 0.4) if unlucky else (share < 0.4),
                     [e["event_id"] for e in (saved if unlucky else misses)], [], on_target=on_t, shots=n, share=int(round(share * 100))))
    big_saves = [e for e in saved if e["extra"].get("xg", 0) >= 0.2]
    out.append(_test("saves forced from shots worth 0.2 xG or more", f"{len(big_saves)}", (len(big_saves) >= 1) if unlucky else (len(big_saves) == 0),
                     [e["event_id"] for e in big_saves] if unlucky else [], [] if unlucky else [e["event_id"] for e in big_saves], saves=len(big_saves)))
    return out


def tests_collapse(ctx: Context, team: str) -> list[dict]:
    m, t = ctx.m, ctx.t
    opp = m.other(team)
    t0 = max(0.0, t - COLLAPSE_S)
    recent = m.between(t0, t)
    conceded = [e for e in recent if e["type"] == "goal" and e["team_id"] == opp]
    out = [_test("goals conceded, last 15 min", f"{len(conceded)}", len(conceded) >= 2, [e["event_id"] for e in conceded], [], conceded=len(conceded))]
    rx, ax = ctx.team_delta(opp, "xg"), _per10(ctx.now.t[opp]["xg"], t)
    out.append(_test("xG conceded, last 10 min vs match average", f"{_r(rx, 2)} vs {_r(ax, 2)} per 10 min", rx > 1.5 * ax and rx > 0.3,
                     ctx.ids(lambda e: e["type"] == "shot", team=opp), [], recent=_r(rx, 2), average=_r(ax, 2)))
    be, ba = ctx.team_delta(opp, "box_entries"), _per10(ctx.now.t[opp]["box_entries"], t)
    out.append(_test("box entries conceded, last 10 min vs match average", f"{int(be)} vs {_r(ba)} per 10 min", be > 1.5 * ba and be >= 3,
                     ctx.ids(lambda e: e["type"] == "pass" and e["outcome"] == "complete" and e["extra"].get("into_box"), team=opp), [], recent=int(be), average=_r(ba)))
    errors = []
    for pid, entries in ctx.ratings["players"].items():
        if m.team_of.get(pid) != team:
            continue
        for en in entries:
            if t0 < en["t"] <= t + 60:
                errors += [r["event_id"] for r in en["reasons"] if r["label"].startswith("Error leading") and t0 < m.by_id[r["event_id"]]["elapsed"] <= t]
    out.append(_test("errors leading to shots, last 15 min", f"{len(errors)}", len(errors) >= 1, errors, [], errors=len(errors)))
    da = ctx.team_delta(team, "tackles") + ctx.team_delta(team, "interceptions") + ctx.team_delta(team, "clearances") + ctx.team_delta(team, "blocks")
    n = ctx.now.t[team]
    davg = _per10(n["tackles"] + n["interceptions"] + n["clearances"] + n["blocks"], t)
    out.append(_test("defensive actions, last 10 min vs match average", f"{int(da)} vs {_r(davg)} per 10 min", da > 1.3 * davg, [], [], recent=int(da), average=_r(davg)))
    return out


def tests_tiredness(ctx: Context, team: str | None, pid: str | None) -> list[dict]:
    m, t = ctx.m, ctx.t
    has_frames = bool(m.frames)
    if pid:
        who = m.surname(pid)
        d = lambda k: ctx.player_delta(pid, k)
        tot = lambda k: ctx.now.p.get(pid, {}).get(k, 0.0)
        mins = ctx.now.p.get(pid, {}).get("minutes", t / 60) or (t / 60)
    else:
        who = m.team_name(team)
        d = lambda k: ctx.team_delta(team, k)
        tot = lambda k: ctx.now.t[team][k]
        mins = t / 60
    win_min = ctx.window / 60
    out = []
    if has_frames:
        sr, sa = d("sprints") / win_min, tot("sprints") / max(mins, 1)
        out.append(_test(f"sprints per minute for {who}, last 10 min vs match", f"{_r(sr, 2)} vs {_r(sa, 2)}", sr < 0.75 * sa, [], [], recent=_r(sr, 2), match=_r(sa, 2)))
        dr, dav = d("distance_m") / win_min, tot("distance_m") / max(mins, 1)
        out.append(_test(f"metres per minute for {who}, last 10 min vs match", f"{int(dr)} vs {int(dav)}", dr < 0.9 * dav, [], [], recent=int(dr), match=int(dav)))
        if pid:
            hr, ha = d("high_intensity_distance_m") / win_min, tot("high_intensity_distance_m") / max(mins, 1)
            out.append(_test("high-intensity metres per minute, last 10 min vs match", f"{int(hr)} vs {int(ha)}", hr < 0.75 * ha, [], [], recent=int(hr), match=int(ha)))
    pr, pa = d("pressures") / win_min, tot("pressures") / max(mins, 1)
    out.append(_test(f"pressures per minute for {who}, last 10 min vs match", f"{_r(pr, 2)} vs {_r(pa, 2)}", pr < 0.75 * pa, [], [], recent=_r(pr, 2), match=_r(pa, 2)))
    if not pid:
        opp = m.other(team)
        terr = _share(ctx.team_delta(team, "opp_half_touches"), ctx.team_delta(opp, "opp_half_touches"))
        out.append(_test("territory, last 10 min", f"{int(round(terr * 100))}%", terr < 0.45, [], [], share=int(round(terr * 100))))
        ta = d("tackles") + d("interceptions")
        tav = _per10(tot("tackles") + tot("interceptions"), t)
        out.append(_test("tackles and interceptions, last 10 min vs match average", f"{int(ta)} vs {_r(tav)} per 10 min", ta < 0.75 * tav, [], [], recent=int(ta), average=_r(tav)))
    return out


# ------------------------------------------------------------------ orchestration
def run_tests(match: Match, cls: dict, t: float) -> tuple[list[dict], dict]:
    """Returns (tests, subjects) where subjects holds the resolved team and player ids."""
    ctx = Context(match, t)
    ctype = cls["type"]
    teams, players = list(cls.get("teams") or []), list(cls.get("players") or [])
    subj: dict = {"type": ctype}
    if ctype == "out_of_scope":
        return [], subj
    if ctype in ("momentum_lost", "momentum_gained", "dominance", "pressing_working", "pressing_failing", "defensive_collapse"):
        if not teams and players:
            teams = [match.team_of[players[0]]]
        team = _default_team(ctx, ctype, teams)
        subj["team"] = team
        if ctype.startswith("momentum"):
            return tests_momentum(ctx, team, ctype == "momentum_lost"), subj
        if ctype == "dominance":
            return tests_dominance(ctx, team), subj
        if ctype.startswith("pressing"):
            return tests_pressing(ctx, team, ctype == "pressing_working"), subj
        return tests_collapse(ctx, team), subj
    if ctype in ("duel_winning", "duel_losing"):
        if not players:
            return [], {"type": "out_of_scope", "reason": "no player named"}
        a = players[0]
        b = players[1] if len(players) > 1 and match.team_of[players[1]] != match.team_of[a] else _opponent_for_duel(ctx, a)
        if not b:
            return [], {"type": "out_of_scope", "reason": "no duel found"}
        subj.update(team=match.team_of[a], player=a, opponent=b)
        return tests_duel(ctx, a, b, ctype == "duel_winning"), subj
    if ctype in ("player_big_game", "player_poor_game"):
        if not players:
            return [], {"type": "out_of_scope", "reason": "no player named"}
        subj.update(team=match.team_of[players[0]], player=players[0])
        return tests_player_game(ctx, players[0], ctype == "player_big_game"), subj
    if ctype in ("finishing_unlucky", "finishing_wasteful"):
        pid = players[0] if players else None
        team = match.team_of[pid] if pid else _default_team(ctx, ctype, teams)
        subj.update(team=team, **({"player": pid} if pid else {}))
        return tests_finishing(ctx, None if pid else team, pid, ctype == "finishing_unlucky"), subj
    if ctype == "tiredness":
        pid = players[0] if players else None
        team = match.team_of[pid] if pid else _default_team(ctx, ctype, teams)
        subj.update(team=team, **({"player": pid} if pid else {}))
        return tests_tiredness(ctx, None if pid else team, pid), subj
    return [], {"type": "out_of_scope"}


def verdict_for(tests: list[dict]) -> str:
    if not tests:
        return "out_of_scope"
    n = sum(1 for x in tests if x["passes"])
    frac = n / len(tests)
    return "supported" if frac >= 0.66 else "partly" if frac >= 0.34 else "not_supported"


def _subject_phrase(match: Match, subj: dict) -> str:
    if subj.get("player"):
        s = match.surname(subj["player"])
        if subj.get("opponent"):
            s += f" against {match.surname(subj['opponent'])}"
        return s
    return match.team_name(subj["team"])


VERDICT_WORDS = {"supported": "the numbers back that up", "partly": "that is only partly true", "not_supported": "the numbers say otherwise"}


def narrate_template(match: Match, claim: str, subj: dict, tests: list[dict], verdict: str) -> dict:
    if verdict == "out_of_scope":
        return {"casual": "That one is outside what the match data can test. Try a claim about momentum, control, pressing, a duel, a player's game, finishing, the defence or tiredness.",
                "tactical": "Out of scope: the claim does not map to a testable claim type over the match events."}
    who = _subject_phrase(match, subj)
    label = TYPE_LABEL[subj["type"]]
    passed = [x for x in tests if x["passes"]]
    failed = [x for x in tests if not x["passes"]]
    n, k = len(tests), len(passed)
    lead = passed[0] if verdict != "not_supported" and passed else (failed[0] if failed else tests[0])
    casual = f"{who} {label}? {VERDICT_WORDS[verdict].capitalize()}: {k} of {n} checks agree. Key one: {lead['name']}, {lead['value']}."
    parts = [f"{x['name']}: {x['value']} ({'passes' if x['passes'] else 'fails'})" for x in tests]
    tactical = f"{verdict.replace('_', ' ').capitalize()} ({k}/{n}). " + "; ".join(parts) + "."
    return {"casual": casual, "tactical": tactical}


NARRATE_SYSTEM = """You are Sightline's narrator for a second-screen football app. You phrase a verdict on a pundit claim.
Rules: use ONLY the numbers and names given in the tests; never invent, round differently, or add any other number or name.
Write in {lang}. Return JSON only: {{"casual": "one or two plain sentences, at most one number", "tactical": "two sentences with the key numbers"}}."""


def narrate(match: Match, llm: LLM, claim: str, subj: dict, tests: list[dict], verdict: str, lens: str, lang: str) -> tuple[dict, dict, dict]:
    """Returns (summary, check, receipt)."""
    template = narrate_template(match, claim, subj, tests, verdict)
    allowed_nums = allowed_number_set([x["value"] for x in tests] + [v for x in tests for v in x["numbers"].values()] +
                                      [len(tests), sum(1 for x in tests if x["passes"]), 5, 10, 15, 100, 0.35, 0.2] + list(match.score_at(subj.get("t", 0) or 0).values()))
    allowed_names = {match.team_name(t) for t in match.teams}
    for key in ("player", "opponent"):
        if subj.get(key):
            allowed_names.update({match.name(subj[key]), match.surname(subj[key])})
    for t in match.teams:
        allowed_names.update(w for w in match.team_name(t).split(" ") if len(w) > 3)
    vocab = match.all_names()
    receipt = {"model": llm.model, "latency_ms": 0, "mode": llm.mode, "tokens_in": 0, "tokens_out": 0}
    check = {"passed": True, "numbers_checked": numbers_in(template["casual"]) + numbers_in(template["tactical"]), "retries": 0, "issues": []}
    if not llm.available or verdict == "out_of_scope":
        return template, check, receipt
    payload = {"claim": claim, "subject": _subject_phrase(match, subj), "verdict": verdict, "tests": [{"name": x["name"], "value": x["value"], "passes": x["passes"]} for x in tests]}
    issues: list[str] = []
    for attempt in range(2):
        user = json.dumps(payload, ensure_ascii=False)
        if issues:
            user += "\nYour previous answer was rejected by the checker: " + "; ".join(issues) + ". Use only the given numbers and names."
        try:
            data, res = llm.chat_json(NARRATE_SYSTEM.format(lang=lang), user, max_tokens=300)
        except Exception as exc:  # transport error: template
            receipt["error"] = str(exc)[:200]
            break
        receipt["latency_ms"] += res["latency_ms"]
        receipt["tokens_in"] += res["tokens_in"]
        receipt["tokens_out"] += res["tokens_out"]
        if not data or not isinstance(data.get("casual"), str) or not isinstance(data.get("tactical"), str):
            issues = ["response was not the JSON shape requested"]
            check["retries"] = attempt + 1
            continue
        issues = check_text(data["casual"], allowed_nums, allowed_names, vocab) + check_text(data["tactical"], allowed_nums, allowed_names, vocab)
        if not issues:
            check.update(passed=True, numbers_checked=numbers_in(data["casual"]) + numbers_in(data["tactical"]), retries=attempt, issues=[])
            return {"casual": data["casual"], "tactical": data["tactical"]}, check, receipt
        check["retries"] = attempt + 1
    check.update(issues=issues, fallback="template phrasing after checker rejections")
    return template, check, receipt


def check_claim(match: Match, claim: str, t: float, lens: str = "tactical", lang: str = "en", llm: LLM | None = None) -> dict:
    t0 = time.time()
    llm = llm or LLM()
    cls = classify(match, claim, llm)
    tests, subj = run_tests(match, cls, t)
    subj["t"] = t
    verdict = verdict_for(tests)
    summary, check, receipt = narrate(match, llm, claim, subj, tests, verdict, lens, lang)
    receipt["latency_ms"] = max(receipt["latency_ms"], int((time.time() - t0) * 1000))
    receipt["classifier"] = cls["via"]
    ev_for = sorted({i for x in tests for i in x["evidence_for"]})
    ev_against = sorted({i for x in tests for i in x["evidence_against"]})
    return {"claim": claim, "match_id": match.match_id, "t": t, "clock": match.clock_at(t), "lens": lens, "lang": lang,
            "claim_type": subj.get("type", cls["type"]), "subject": {k: v for k, v in subj.items() if k in ("team", "player", "opponent")},
            "verdict": verdict, "summary": summary,
            "tests": [{"name": x["name"], "value": x["value"], "passes": x["passes"]} for x in tests],
            "evidence_for": ev_for, "evidence_against": ev_against, "check": check, "receipt": receipt}


SAMPLE_CLAIMS = [
    (1900.0, "Arden have lost all momentum since the goal"),
    (3700.0, "Arden's defence has completely collapsed"),
    (4700.0, "Hollow Vale have lost the momentum now"),
    (4700.0, "Arden's press is finally working"),
    (5000.0, "{HVL_09} has {ARD_08} in his pocket"),
    (5400.0, "{ARD_05} is having a huge game"),
    (5500.0, "Hollow Vale look tired"),
    (5946.0, "The referee has been shocking tonight"),
]


def write_sample(match: Match, out: Path = VIEWER_DATA / "claims.sample.json") -> dict:
    llm = LLM()
    items = []
    for t, text in SAMPLE_CLAIMS:
        claim = text.format(**{pid: match.surname(pid) for pid in match.players})
        items.append(check_claim(match, claim, t, "tactical", "en", llm))
    data = {"match_id": match.match_id, "mode": llm.mode, "model": llm.model, "claims": items}
    write_json(out, data)
    return data
