# Sightline agent D: claim checker, ratings, patterns and translations

**Model:** Fable 5. Claim classification, statistical tests per claim type and pattern detection need careful reasoning.
**Branch:** `agent-d`. **Hard stop: 05:15 UK time.** The hackathon deadline is 06:59 UK time on 28 Oct, so working beats complete: commit after every numbered item, never leave the build broken, and stop at 05:15 with a short report even if items remain.

## Context

Sightline is a hackathon entry for the Microsoft and Premier League "Inside the Game" challenge: AI that turns synthetic football match events into explainable, personalised match intelligence. It is a second-screen layer for the Premier League app with three lenses (Casual, Tactical, Commentator). Repo: `github.com/Unknown-Turtle/sightlinedev`. Already built: `matchgen/` (synthetic match engine with events, tracking, a stats engine and a five-season fictional league history; read its README, SCHEMA and HISTORY docs) and `viewer/` (a Vite, TypeScript and Three.js 3D replay with live points and evidence reels; read its README). Five other agents work in parallel on other folders. Stay inside the folders this prompt gives you. Do not use em dashes in any text, docs or comments.

## Your task

You are adding four features to Sightline's agent layer, a hackathon entry for the Microsoft and Premier League "Inside the Game" challenge. Another agent is building the core in `agents/` at the same time: do not edit anything in `agents/` outside `agents/extras/`, and import from the core only through its public functions if they exist, otherwise reimplement what you need inside `agents/extras/`. Read `matchgen/README.md`, `matchgen/SCHEMA.md`, `matchgen/HISTORY.md` and `viewer/src/points.ts`, and paste the contract additions above into `agents/extras/CONTRACT.md`. Foundry config comes from `FOUNDRY_ENDPOINT`, `FOUNDRY_DEPLOYMENT`, and `FOUNDRY_API_KEY` or `DefaultAzureCredential`; with none set, everything runs in fallback mode with template phrasing and stays valid. **Code computes every number; models only phrase; a checker verifies every number and name.** You have about two hours. Commit after each numbered item.

1. **Match ratings** (`python -m agents.extras ratings ...`, writes `viewer/public/data/ratings.json`): a transparent, deterministic rating from 0 to 10 for every player, recomputed every 60 s of match time. Start at 6.0, add and subtract small documented weights per event type and outcome (goals, assists, key passes, xG and xA, progressive passes, take-ons, tackles, interceptions, clearances, blocks, recoveries, saves and goals prevented for keepers; minus for losses, dispossessions, fouls, cards, errors leading to shots), scale by minutes played, clamp to 3.0 to 10.0. Every change records the events that caused it in `reasons`. Document the formula in `agents/extras/RATINGS.md`. Test: totals reconcile with the event log.
2. **Claim checker** (`agents/extras/claims.py` plus a FastAPI app `agents/extras/api.py` exposing `POST /api/claims`): a user types a pundit-style claim. (a) An LLM classifier maps it to one of a fixed set of testable claim types: momentum lost or gained, dominance or control, pressing working or failing, a player winning or losing a duel, a player having a big or poor game, unlucky or wasteful finishing, defensive collapse, tiredness; or `out_of_scope` (with a deterministic keyword fallback when no model is set). (b) Deterministic code runs that type's tests from `matchgen.stats.StatsEngine` snapshots and events up to time `t` (for example momentum: final-third entries, xG rate, territory, field tilt in the last 10 minutes against the team's match average and against the opponent) and collects evidence for and against. (c) The narrator phrases the verdict per lens; the checker rejects any number or name not in the test results. Return the response in the contract. Write `viewer/public/data/claims.sample.json` with 6 to 8 example claims at moments in the demo match where the answer is interesting, including at least one `not_supported` correction and one `out_of_scope`. Tests: a made-up number in the narrator text is rejected, and an off-topic question returns `out_of_scope`.
3. **Routine detection** (writes `viewer/public/data/routines.json`): find repeated pass sequences by the same team and roles starting from the same restart or regain type, using only `events.jsonl` and `match.json` (the playbooks in `match.json` are public and may be used as templates). Group attempts, count shots that came from them, and evaluate precision and recall against `routines_truth.jsonl` for the report only. Never read the truth file in the detection path.
4. **Translations** (writes `viewer/public/data/insights.<lang>.json` for `es`, `fr`, `pt`, `ar`): translate each insight's `text` fields with the model, keep every number and name unchanged, and run the checker on each translation. In fallback mode, write the files with the English text and `"translated": false` so the viewer can say so.

Finish with `agents/extras/README.md` and a short report: what works, live or fallback, routine detection precision and recall, and anything left undone.

## Shared contract

All six agents follow this so their outputs line up.

### `insights.json`

All three prompts use this file format. Agent A produces it, Agent B renders it, Agent C documents it.

```json
{
  "match_id": "m_seed587",
  "generated_at": "2026-10-28T04:30:00Z",
  "mode": "live | fallback",
  "model": "deployment name or null",
  "items": [
    {
      "id": "i_0001",
      "t": 4356.0,
      "clock": "72:36",
      "kind": "anchor | duel | finishing | momentum | score_state | recap",
      "point_id": "anchor-ARD_05",
      "team": "ARD",
      "subject": "ARD_05",
      "text": {
        "casual": "one or two plain sentences",
        "tactical": "one or two sentences with the numbers",
        "commentator": "one line of context or trivia a commentator could say on air"
      },
      "evidence_for": ["e_000123"],
      "evidence_against": ["e_000456"],
      "trivia": [{ "text": "...", "source": "head_to_head.csv", "row": "ARD,HVL" }],
      "check": { "passed": true, "numbers_checked": 4, "retries": 0, "issues": [] },
      "receipt": { "model": "...", "latency_ms": 1840, "tokens_in": 1200, "tokens_out": 140, "agents": ["analyst", "narrator", "checker", "trivia"] }
    }
  ]
}
```

`t` is match `elapsed` seconds (the same clock as events and tracking). An item is visible in the app once playback passes `t`, and stays until a newer item with the same `point_id` replaces it. `recap` items are written at half time and full time.

### Contract additions

Agent D produces these files, Agent F renders them, Agent E serves them live, Agent C documents them.

**`viewer/public/data/ratings.json`**: match ratings over time, 0 to 10, deterministic.
```json
{ "every_s": 60, "formula": "short description", "players": {
  "ARD_05": [{ "t": 600.0, "rating": 6.4, "delta": 0.2, "reasons": [{ "event_id": "e_000201", "label": "Interception in own box", "effect": 0.2 }] }] } }
```

**`viewer/public/data/routines.json`**: rehearsed patterns detected from events only (never from `routines_truth.jsonl`).
```json
{ "patterns": [{ "id": "p1", "team": "ARD", "label": "Keeper to pivot to striker drop-off", "attempts": [{ "t": 1210.4, "event_ids": ["e_000402"], "outcome": "shot | lost | completed" }],
  "shots_from": 2, "evaluation": { "precision": 0.9, "recall": 0.8, "against": "routines_truth.jsonl" } }] }
```

**`viewer/public/data/insights.<lang>.json`**: the same shape as `insights.json` with all `text` fields translated (`es`, `fr`, `pt`, `ar` at minimum). Numbers and names unchanged; the checker runs again on each translation.

**`viewer/public/data/claims.sample.json`**: precomputed verdicts for 6 to 8 example claims at fixed times, so the claim checker works with no backend.

**Claim check API** (served by Agent D's code, hosted by Agent E): `POST /api/claims` with `{ "match_id", "t", "claim", "lens", "lang" }`. Response:
```json
{ "claim": "they've lost the momentum", "verdict": "supported | partly | not_supported | out_of_scope",
  "summary": { "casual": "...", "tactical": "..." }, "tests": [{ "name": "final-third entries, last 10 min vs match", "value": "4 vs 9.5 per 10 min", "passes": true }],
  "evidence_for": ["e_..."], "evidence_against": ["e_..."], "check": { "passed": true, "numbers_checked": 5, "retries": 0 }, "receipt": { "model": "...", "latency_ms": 2100, "mode": "live | fallback" } }
```

**Live messages** (Web PubSub, Agent E): `{ "kind": "snapshot" | "insight" | "rating" | "event", "data": {...} }`, where `insight` and `rating` match the files above item by item.
