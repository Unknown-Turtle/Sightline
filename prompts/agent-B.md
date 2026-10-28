# Sightline agent B: insights and the app shell in the viewer

**Model:** Opus 5.5. UI work against an existing codebase with a clear spec.
**Branch:** `agent-b`. **Hard stop: 05:15 UK time.** The hackathon deadline is 06:59 UK time on 28 Oct, so working beats complete: commit after every numbered item, never leave the build broken, and stop at 05:15 with a short report even if items remain.

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

You are extending the Sightline viewer, a Vite, TypeScript and Three.js app in `viewer/`. Read `viewer/README.md` and every file in `viewer/src/` first. You own the `viewer/` folder only, except that you must not edit `viewer/public/data/insights.json` (another agent writes it). You have about two hours. Commit working increments every 30 minutes on your branch. Keep `npm run build` passing at every commit.

**Goal:** restyle the viewer as a match centre inside the Premier League app (see "Look and feel" below), build the shared app shell, make the app show AI insights with receipts, and add a third lens.

0. **First, within 30 minutes: the restyle and the app shell.** Replace the design tokens in `styles.css` with the Premier League app look (keep the token names other code already uses, such as `--paper`, `--panel`, `--ink`, `--muted`, `--line`, `--accent`, so other work picks up the new look automatically). Build the match header, lens pills, `#personal-bar`, and the tabs with the panel ids listed below, moving the existing stage, controls, timeline and rail into `#panel-live` and the reel into `#panel-moments`. Fill `#panel-stats` with comparison rows from the latest snapshot (`matchgen` snapshots: copy `sample/demo_seed587/snapshots.jsonl` stats into the packed data via `tools/pack_match.py` if needed). Leave `#panel-ratings`, `#panel-claims` and `#panel-patterns` empty with a short placeholder; another agent fills them. Commit this before anything else.

1. **Load `data/insights.json`** if it exists (the format is the shared contract: paste it into `viewer/INSIGHTS.md`). If it is missing or invalid, the app must work exactly as it does now. Write a small fixture `viewer/public/data/insights.sample.json` with 4 or 5 hand-written items at real event times from the demo match, and use it only when `insights.json` is absent.
2. **Rail points use insight text when available.** For each point shown at the live time, use the newest insight with the same `point_id` and `t` at or before the live time, and show `text[lens]`. Fall back to the current templates otherwise. Insights of kind `momentum`, `score_state` and `recap` appear as their own rail items.
3. **Receipts.** Under each insight show a compact receipt line: "Checked: 4 numbers, 0 retries" plus the model and latency. A disclosure opens the full receipt: agents involved, tokens and mode (live or fallback). When `check.passed` is false, show the template text and say the AI version was rejected. This is a feature: it shows the checker works.
4. **Commentator lens.** Add `Commentator` to the lens control. In this lens the rail shows `text.commentator`, each item's trivia with its source (for example "From head-to-head records"), and a small "Coming up" list built from insights of kind `score_state`. Overlays in this lens match Casual.
5. **Recap.** At half time and full time, when a `recap` insight exists, show it as a dismissable panel over the stage.
6. **Evidence reels** keep working for every insight: build For and Against from `evidence_for` and `evidence_against` event ids.
7. Keep the token names from step 0, both themes, phone width with no horizontal scroll, keyboard focus, and reduced motion.

**Deliver:** the changes, an updated `viewer/README.md`, and a final short report with a screenshot or a description of each lens.

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
