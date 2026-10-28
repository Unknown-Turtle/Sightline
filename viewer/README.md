# Sightline viewer

A match centre styled like a feature inside a modern football app: a 3D replay of a matchgen match with AI insights, receipts and swipeable evidence. Three.js, TypeScript, Vite. All clubs, players and crests are fictional.

- **App shell:** split-colour match header with score and live clock, lens pills (Casual, Tactical, Commentator), a `#personal-bar` strip for personalisation, shortcut cards, and underline tabs: **Live** (`#panel-live`), **Moments** (`#panel-moments`), **Stats** (`#panel-stats`), **Ratings** (`#panel-ratings`), **Claims** (`#panel-claims`), **Patterns** (`#panel-patterns`). The last three are placeholders that other panels mount into
- **Stage:** floodlit pitch, stylised players moving with the tracking data (smoothed between frames), procedural animation clips triggered by events. Broadcast and Tactical cameras
- **Lenses:** Casual shows names, sprint speeds and plain-language points. Tactical adds pass trails, a pressure ring on the carrier, the back line, xG on shots and the numbers in the wording. Commentator shows the on-air line for each insight, its trivia with the source, and a "Coming up" list of the score-state lines still to come. Overlays in Commentator match Casual
- **Rail ("What's happening"):** points detected from events up to the live time (defensive anchor, winning the duel, finishing against xG). When `data/insights.json` has an item for the same `point_id` at or before the live time, its text for the lens replaces the template. Momentum, score-state and recap insights appear as their own items
- **Receipts:** under each insight, "Checked: N numbers, R retries, model, latency". "Full receipt" opens the agents involved, tokens, mode (live or fallback) and any checker issues. When `check.passed` is false the card shows the template text and says the AI version was rejected, so the checker is visible
- **Moments:** every item opens an evidence reel of the exact events for and against it (from `evidence_for` and `evidence_against` for insights). Select a card to watch that moment, after which the view returns to the live match
- **Stats:** comparison rows from the latest stats snapshot (home left, label centred, away right, team-coloured bars marking the leader), updating with the clock
- **Recap:** at half time and full time a `recap` insight shows as a dismissable panel over the stage
- **Timeline:** momentum strip from the stats snapshots (home above the line, away below) with goal markers

## Run it

```bash
cd viewer
npm install
npm run dev          # http://localhost:5173
npm run build        # type check and bundle to dist/
```

The demo match is already packed in `public/data/`. To use another match:

```bash
cd ../matchgen
python -m matchgen generate --seed 587 --script demo --hz 5 --out out/demo5
python -m matchgen snapshots --dir out/demo5 --every 30 --out out/demo5/snapshots.jsonl
cd ../viewer
python tools/pack_match.py ../matchgen/out/demo5 public/data
```

`--hz 5` gives smooth movement. 1 Hz works but players glide. Add `--js` to the pack command to also write `tracking.js`, a base64 copy for hosts that cannot serve binary files. The pack now includes a per-snapshot stats block used by the Stats tab.

## Insights

`public/data/insights.json` is written by the agent layer; the contract is in `INSIGHTS.md`. If it is missing or invalid the viewer loads `public/data/insights.sample.json`, a hand-written fixture at real event times of the demo match (five items plus two score states, one of them deliberately failing the checker). If both are missing the app runs on its templated points exactly as before.

## Look and feel

Dark aubergine background, purple cards with large rounded corners, white and muted lavender text, Outfit from Google Fonts, pill buttons and underline tabs. The design tokens live in `src/styles.css` (`--paper`, `--panel`, `--ink`, `--muted`, `--line`, `--accent` and friends) and every panel should read those rather than fixed colours. Dark is primary; `<html data-theme="light">` switches to the pale lavender variant through the same tokens. Mobile first: phone width has no horizontal scroll, focus is visible, and reduced motion is respected.

## Files

```
index.html          the match-centre shell (header, pills, personal bar, tabs, panels)
src/styles.css      design tokens and layout
src/data.ts         loading, Catmull-Rom sampling of tracking, match clock
src/stage.ts        Three.js scene, figures, animation clips, cameras, overlay anchors
src/points.ts       point detectors and evidence (templated wording per lens)
src/insights.ts     insights.json loading, validation, selection and receipt text
src/main.ts         app state, playback, tabs, rail, receipts, recap, stats, evidence reel, replays
tools/pack_match.py match folder to compact viewer data (int16 tracking, trimmed events, snapshot stats)
INSIGHTS.md         the shared insight contract
```

## Known gaps

- Ratings, Claims and Patterns tabs are placeholders until their panels mount
- "Coming up" in the Commentator lens lists score-state insights with a later time than the live clock; in a true live feed it would hold the commentator's prepared lines instead
- Animation clips are procedural and simple by design
