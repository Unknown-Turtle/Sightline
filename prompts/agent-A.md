# Sightline agent A: the agent layer

**Model:** Fable 5. The hardest reasoning: grounding, the checker loop, unfamiliar Foundry SDKs.
**Branch:** `agent-a`. **Hard stop: 05:15 UK time.** The hackathon deadline is 06:59 UK time on 28 Oct, so working beats complete: commit after every numbered item, never leave the build broken, and stop at 05:15 with a short report even if items remain.

## Context

Sightline is a hackathon entry for the Microsoft and Premier League "Inside the Game" challenge: AI that turns synthetic football match events into explainable, personalised match intelligence. It is a second-screen layer for the Premier League app with three lenses (Casual, Tactical, Commentator). Repo: `github.com/Unknown-Turtle/sightlinedev`. Already built: `matchgen/` (synthetic match engine with events, tracking, a stats engine and a five-season fictional league history; read its README, SCHEMA and HISTORY docs) and `viewer/` (a Vite, TypeScript and Three.js 3D replay with live points and evidence reels; read its README). Five other agents work in parallel on other folders. Stay inside the folders this prompt gives you. Do not use em dashes in any text, docs or comments.

## Your task

You are building the AI agent layer for Sightline, a hackathon entry for the Microsoft and Premier League "Inside the Game" challenge. Read `matchgen/README.md`, `matchgen/SCHEMA.md`, `matchgen/HISTORY.md`, `viewer/src/points.ts` and `viewer/README.md` first. You own the `agents/` folder only. Do not edit any other folder. You have about two hours. Commit working increments every 30 minutes on your branch.

**Goal:** a Python package `agents/` that reads a generated match (`matchgen/sample/demo_seed587/`) and the history archive (`matchgen/sample/history/`), and writes `insights.json` in the exact format in the shared contract (paste the contract into `agents/CONTRACT.md`). It must be multi-agent, grounded and checkable, and it must always produce output, even with no AI credentials.

**Rule one: the model never produces a number.** Code computes every number and selects every piece of evidence. Models only phrase, and a checker verifies the phrasing.

**Pipeline, run at each checkpoint** (every 5 minutes of match time, plus immediately after each goal, red card and half time):
1. **Analyst (deterministic Python, not an LLM):** port the three detectors in `viewer/src/points.ts` (anchor, duel, finishing) to Python, and add two more: `momentum` (a team's `last_5_min.momentum` from the stats snapshots stays above 60 for two consecutive snapshots, with evidence = its final-third entries and shots in that window) and `score_state` (who leads, any comeback, with the goals as evidence). Use `matchgen.stats.StatsEngine` for numbers. Output a fact pack per point: every number, every evidence event id, and short descriptions of the evidence events.
2. **Trivia agent (deterministic lookup plus an optional LLM phrase):** query the history CSVs (head to head, club records, milestones upcoming, scoring timeline) for facts relevant to the point and the current score state. Return facts with `source` and `row`. Never invent a fact; if a lookup returns nothing, return nothing.
3. **Narrator (LLM):** given the fact pack and trivia, write `casual`, `tactical` and `commentator` text. Casual: no jargon, no abbreviations. Tactical: include the numbers. Commentator: one on-air line, using trivia if there is any. The system prompt must forbid any number that is not in the fact pack.
4. **Checker (deterministic first, LLM second):** extract every number and every player or club name from the narrator's text and confirm each appears in the fact pack or the trivia. On failure, send the issues back to the narrator (at most two retries), then fall back to a template. Record `check` and `receipt` as in the contract.
5. **Recap agent:** at half time and full time, write a three to five sentence recap per lens from the score state, the xG timeline and the strongest points.

**Models and frameworks:** use Microsoft Foundry through the official Python SDK. Prefer the Microsoft Agent Framework (`pip install agent-framework --pre`) for the orchestration if it installs and works within 20 minutes of trying; otherwise use the `openai` package's Azure client against the Foundry project endpoint and orchestrate in plain Python, and say so in the README. Read config from environment variables: `FOUNDRY_ENDPOINT`, `FOUNDRY_DEPLOYMENT`, and either `FOUNDRY_API_KEY` or `DefaultAzureCredential` (prefer managed identity in Azure, CLI login locally). If none are set, run in `fallback` mode: the same pipeline with template phrasing, so the output is still complete and valid. Add OpenTelemetry tracing around each agent step if the framework gives it cheaply.

**Limits, per checkpoint:** 3 LLM calls at most per point, a 20-second timeout per call, temperature 0.3, and 400 output tokens.

**Command line:** `python -m agents build --match matchgen/sample/demo_seed587 --history matchgen/sample/history --out viewer/public/data/insights.json`. Writing into `viewer/public/data/` is the one exception to the folder rule: that single file only.

**Deliver:** the package, `agents/README.md` (architecture, a diagram of the four agents and their handoffs, the "numbers come from code" rule, how to run live and fallback), tests for the checker (it must reject a narrator line containing a made-up number or a made-up name), and a committed `viewer/public/data/insights.json` generated in fallback mode. If live credentials are available in your environment, also generate a live version. Finish with a short report: what works, live or fallback, and what you would do next.

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
