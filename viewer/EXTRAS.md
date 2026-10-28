# Sightline extras contract

Copied from the agent prompts so the viewer folder carries the contract the extras (agent F) render against. Agent D produces these files, agent F renders them, agent E serves them live, agent C documents them.

## App shell ids (agent B builds, agent F mounts)

A match-centre page: the split-colour match header with score and live clock, the lens switch as pills (Casual, Tactical, Commentator), then underline tabs: **Live** (`#panel-live`), **Moments** (`#panel-moments`: evidence reels), **Stats** (`#panel-stats`), **Ratings** (`#panel-ratings`), **Claims** (`#panel-claims`), **Patterns** (`#panel-patterns`). A settings strip `#personal-bar` sits under the header. If any of these ids is missing, the extras create a plain card with that id at the end of `#app`.

## Look and feel

Match the current Premier League app look through the shared tokens in `src/styles.css` only: dark aubergine background, lighter purple cards with large rounded corners, white primary and muted lavender secondary text, pill buttons, underline tabs, comparison rows with a team-coloured bar. No real trademarks: fictional clubs and players from `matchgen` only, a free Google font, simple shield crests. Dark is primary with a pale lavender light variant through the same custom properties. Mobile first: no horizontal scroll at phone width, visible keyboard focus, reduced motion respected.

## Files

**`public/data/ratings.json`**: match ratings over time, 0 to 10, deterministic.
```json
{ "every_s": 60, "formula": "short description", "players": {
  "ARD_05": [{ "t": 600.0, "rating": 6.4, "delta": 0.2, "reasons": [{ "event_id": "e_000201", "label": "Interception in own box", "effect": 0.2 }] }] } }
```

**`public/data/routines.json`**: rehearsed patterns detected from events only (never from `routines_truth.jsonl`).
```json
{ "patterns": [{ "id": "p1", "team": "ARD", "label": "Keeper to pivot to striker drop-off", "attempts": [{ "t": 1210.4, "event_ids": ["e_000402"], "outcome": "shot | lost | completed" }],
  "shots_from": 2, "evaluation": { "precision": 0.9, "recall": 0.8, "against": "routines_truth.jsonl" } }] }
```

**`public/data/insights.<lang>.json`**: the same shape as `insights.json` with all `text` fields translated (`es`, `fr`, `pt`, `ar` at minimum). Numbers and names unchanged; the checker runs again on each translation.

**`public/data/claims.sample.json`**: precomputed verdicts for 6 to 8 example claims at fixed times, so the claim checker works with no backend. The viewer reads `{ "examples": [ <claim response> + "t" ] }`.

## Claim check API

Served by agent D's code, hosted by agent E. `POST /api/claims` with `{ "match_id", "t", "claim", "lens", "lang" }`. Response:
```json
{ "claim": "they've lost the momentum", "verdict": "supported | partly | not_supported | out_of_scope",
  "summary": { "casual": "...", "tactical": "..." }, "tests": [{ "name": "final-third entries, last 10 min vs match", "value": "4 vs 9.5 per 10 min", "passes": true }],
  "evidence_for": ["e_..."], "evidence_against": ["e_..."], "check": { "passed": true, "numbers_checked": 5, "retries": 0 }, "receipt": { "model": "...", "latency_ms": 2100, "mode": "live | fallback" } }
```

## Live messages

Web PubSub (agent E): `{ "kind": "snapshot" | "insight" | "rating" | "event", "data": {...} }`, where `insight` and `rating` match the files above item by item (`rating` adds `"player": "<player_id>"`).

## Fallback order

Every extras file is optional. The viewer tries `<name>.json`, then `<name>.sample.json`, then shows a short "not available yet" note. The fixtures here: `claims.sample.json` (seven verdicts at 72:36 computed from `events.json`), `ratings.sample.json` and `routines.sample.json` (copies of agent D's outputs for seed 587).
