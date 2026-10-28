# Sightline agent C: Azure, deployment and docs

**Model:** Opus 5.5. Infrastructure as code and documentation from a clear spec.
**Branch:** `agent-c`. **Hard stop: 05:15 UK time.** The hackathon deadline is 06:59 UK time on 28 Oct, so working beats complete: commit after every numbered item, never leave the build broken, and stop at 05:15 with a short report even if items remain.

## Context

Sightline is a hackathon entry for the Microsoft and Premier League "Inside the Game" challenge: AI that turns synthetic football match events into explainable, personalised match intelligence. It is a second-screen layer for the Premier League app with three lenses (Casual, Tactical, Commentator). Repo: `github.com/Unknown-Turtle/sightlinedev`. Already built: `matchgen/` (synthetic match engine with events, tracking, a stats engine and a five-season fictional league history; read its README, SCHEMA and HISTORY docs) and `viewer/` (a Vite, TypeScript and Three.js 3D replay with live points and evidence reels; read its README). Five other agents work in parallel on other folders. Stay inside the folders this prompt gives you. Do not use em dashes in any text, docs or comments.

## Look and feel: match the current Premier League app

The owner wants Sightline to look like a feature inside today's official Premier League app. He shared two screenshots of the app (a match page on the Stats tab, and the Latest home feed). **They are not exhaustive: research the current app yourself** before styling (search for recent screenshots and app store listings of the Premier League app's Match Centre, Live, Stats, Lineups and "PL Companion" screens) and match what you find.

What the screenshots show:
- Very dark aubergine background (roughly #1E0526 to #2A0A31), slightly lighter purple cards (roughly #3A0E44) with large rounded corners (about 24 px), white primary text and muted lavender secondary text
- Bold, rounded geometric sans headings; large confident type for scores and section titles ("Season so far")
- A match header split diagonally into the two team colours with a subtle stripe pattern, team badge and name on each side, and a dark rounded block in the middle for the score or kick-off time
- Pill-shaped outlined buttons (white outline, white text), underline tabs (Preview, Squads, Stats, Table, Match Info) with a white underline on the active tab
- Meta lines in muted lavender (competition, matchweek, date, venue, referee)
- Circular story tiles with a purple-to-pink gradient ring, a row of shortcut cards above a bottom tab bar (Latest, Fantasy, Season, Explore, More), and an AI entry called "PL Companion"
- Comparison rows: home value left, label centred, away value right, with a team-coloured bar marking the leader

Rules:
- **No real trademarks** in the app or the demo video (the submission rules ban them): no Premier League lion or wordmark, no club crests, no broadcaster or Microsoft or Copilot logos, and not the league's own typeface. Use a free geometric sans from Google Fonts with similar character (Outfit or Lexend, for example) and simple fictional crests (a shield in team colours with the club initials). Use the fictional clubs and players from `matchgen` only.
- Dark is the primary look. Keep a light variant (pale lavender) through the same CSS custom properties, following the existing token approach in `viewer/src/styles.css`.
- Mobile first. Phone width with no horizontal scroll, visible keyboard focus, reduced motion respected.

**Shared app shell (B builds it, F mounts into it).** A match-centre page: the split-colour match header with score and live clock, the lens switch as pills (Casual, Tactical, Commentator), then underline tabs: **Live** (`#panel-live`: 3D stage, controls, timeline, points rail; stage and rail side by side on desktop), **Moments** (`#panel-moments`: evidence reels), **Stats** (`#panel-stats`: snapshot comparison rows in the style above), **Ratings** (`#panel-ratings`), **Claims** (`#panel-claims`), **Patterns** (`#panel-patterns`). A settings strip `#personal-bar` sits under the header. A Sightline entry styled like the shortcut cards and story tiles can sit above the tabs.

## Your task

You are preparing the Azure deployment and the submission docs for Sightline, a hackathon entry for the Microsoft and Premier League "Inside the Game" challenge. Read `matchgen/README.md`, `viewer/README.md` and the shared contract (paste it into `docs/insights-contract.md`). You own `infra/`, `docs/` and the root `README.md` only. You have about two hours. Commit every 30 minutes on your branch. You do not have Azure credentials: everything you write is run later by the owner on his Mac, where `az login` already works against his own free-trial subscription. Keep it to one or two commands for him.

1. **Bicep in `infra/`**, with `infra/deploy.sh`, for a resource group in `uksouth` with Foundry in `swedencentral`:
   - Azure Static Web App (Free) hosting the built viewer
   - Microsoft Foundry: an AI Services account with project management enabled, a project, and one model deployment. Make the model name, version and SKU parameters with sensible defaults, and print a clear message if the deployment fails for quota so the owner can switch models
   - Storage account (for match and history data), Log Analytics plus Application Insights
   - A user-assigned managed identity with role assignments for Foundry (Azure AI User or Cognitive Services OpenAI User) and Storage Blob Data Reader
   - Event Hubs (Basic) and an Azure Functions app (Flex Consumption, Python) **only as optional modules behind a parameter `liveStreaming` defaulting to false**, so the default deploy stays cheap and fast
   - Outputs: the Static Web App URL, the Foundry endpoint and deployment name
   `deploy.sh` must: check `az account show`, create the group, deploy, build the viewer (`cd viewer && npm ci && npm run build`), upload `viewer/dist` to the Static Web App (using the SWA CLI via `npx @azure/static-web-apps-cli deploy` with the deployment token from `az staticwebapp secrets list`), and print the export lines for `FOUNDRY_ENDPOINT` and `FOUNDRY_DEPLOYMENT` so the agents can run live. Include `live/infra/live.bicep` (written by another agent in `live/`) as the module behind a `liveStreaming` parameter that defaults to true, and skip it with a clear message if the file does not exist yet. Validate the Bicep with `az bicep build` if the CLI is available, otherwise `npx` a Bicep linter or review it carefully.
2. **Root `README.md`** for judges, readable in one scroll:
   - One-line pitch, then three short paragraphs: the problem (pundit takes based on vibes), what Sightline does (a second-screen layer on the Premier League app with Casual, Tactical and Commentator lenses, live points with evidence for and against, replays), and why it is trustworthy (code computes every number, agents only phrase, a checker verifies, receipts on every insight)
   - An architecture diagram in Mermaid: matchgen (synthetic events and tracking) to stats engine to analyst, trivia, narrator and checker agents on Foundry, to `insights.json` and the viewer, with the optional live path (Event Hubs, Functions) dotted
   - Which Microsoft technologies are used and where
   - How to run locally (three commands) and how to deploy (one command)
   - Data: everything is synthetic and fictional; credit the SPADL format idea and say no real data is used
   - Honest status: what is live, what is fallback, and a short roadmap
   - Leave a placeholder line for the demo video link and the live URL
3. **`docs/pitch.md`**: the elevator pitch for the submission form (what was built, which Microsoft and Azure technologies, what it does, what problem it solves), under 200 words. Also **`docs/video-script.md`**: a shot-by-shot script for a demo video under 2 minutes, opening on the product working within the first 5 seconds, with no music and no real club names or logos. The app is styled like the Premier League app (dark aubergine, rounded purple cards, split-colour match header), so the script should frame Sightline as a new feature inside it.

Do not use em dashes anywhere. Finish with a short report and the exact commands the owner must run.

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
