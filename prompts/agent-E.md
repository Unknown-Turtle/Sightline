# Sightline agent E: live pipeline

**Model:** Opus 5.5. Well-trodden integration work (WebSockets, Functions, Web PubSub). Switch to Fable only if it stalls on Azure SDK details.
**Branch:** `agent-e`. **Hard stop: 05:15 UK time.** The hackathon deadline is 06:59 UK time on 28 Oct, so working beats complete: commit after every numbered item, never leave the build broken, and stop at 05:15 with a short report even if items remain.

## Context

Sightline is a hackathon entry for the Microsoft and Premier League "Inside the Game" challenge: AI that turns synthetic football match events into explainable, personalised match intelligence. It is a second-screen layer for the Premier League app with three lenses (Casual, Tactical, Commentator). Repo: `github.com/Unknown-Turtle/sightlinedev`. Already built: `matchgen/` (synthetic match engine with events, tracking, a stats engine and a five-season fictional league history; read its README, SCHEMA and HISTORY docs) and `viewer/` (a Vite, TypeScript and Three.js 3D replay with live points and evidence reels; read its README). Five other agents work in parallel on other folders. Stay inside the folders this prompt gives you. Do not use em dashes in any text, docs or comments.

## Your task

You are building the real-time path for Sightline, a hackathon entry for the Microsoft and Premier League "Inside the Game" challenge. Read `matchgen/README.md` (especially `stream` and the stats engine) and `viewer/README.md`, and paste the contract additions above into `live/CONTRACT.md`. You own `live/` and the single new file `viewer/src/live.ts`. Do not edit any other file. You do not have Azure credentials: the owner deploys from his Mac later with `az` already logged in, so everything must be runnable with one or two commands, and it must also run fully on a laptop with no Azure at all. Prefer managed identity (`DefaultAzureCredential`) over connection strings everywhere. You have about two hours. Commit after each numbered item.

1. **Local live mode first, no Azure:** `python -m live.local --match matchgen/sample/demo_seed587 --speed 30` replays the match with `matchgen.stream`, runs `matchgen.stats.StatsEngine` incrementally, runs the point detectors (import from `agents/` if available, otherwise call a stub that reads precomputed `viewer/public/data/insights.json` items as their time passes), and serves a WebSocket on `localhost:8787` that broadcasts the live messages in the contract (snapshot every 30 s, insights and ratings as they occur, goals, cards and big chances instantly). Also serve `POST /api/claims` by importing `agents.extras.api` if present.
2. **`viewer/src/live.ts`:** a small client that connects when the page URL has `#live` (to `ws://localhost:8787` or to a Web PubSub client URL fetched from `/api/negotiate`) and exposes `onSnapshot`, `onInsight`, `onRating`, `onEvent` callbacks plus `connected` state. Document in `live/README.md` the three lines `viewer/src/main.ts` needs to call it; do not edit `main.ts` yourself.
3. **Azure Functions app in `live/functions/`** (Python, v2 programming model): an Event Hubs trigger on the `match-events` hub that feeds the same pipeline and publishes each message to Azure Web PubSub (hub `match`, group per `match_id`), a `negotiate` HTTP function returning a client access URL, and the claims endpoint. Use managed identity for Event Hubs and Web PubSub. Keep state per match in memory with a note on scaling (single partition per match keeps order).
4. **Bicep module `live/infra/live.bicep`** (Event Hubs Basic namespace and hub, Web PubSub Free, Function App on Flex Consumption with a system identity and role assignments: Event Hubs Data Receiver, Web PubSub Service Owner, Azure AI User on the Foundry account passed as a parameter) and `live/deploy.sh` that deploys it into an existing resource group, publishes the functions, and starts the replay into Event Hubs with `python -m matchgen stream --sink eventhub`. Validate with `az bicep build` if available.
5. **Tests:** the local server sends a snapshot within a second of starting at high speed, and message shapes match the contract.

Finish with `live/README.md` (diagram, local run, Azure run, how the viewer connects) and a short report.

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
