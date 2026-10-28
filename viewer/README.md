# Sightline viewer

A 3D replay of a matchgen match with live points and swipeable evidence. Three.js, TypeScript, Vite.

- **Stage:** floodlit pitch, stylised players moving with the tracking data (smoothed between frames), simple procedural animation (run cycle plus kick, header, slide tackle, keeper dive and celebration clips triggered by events)
- **Cameras:** Broadcast follows the ball from the stand. Tactical looks down on the whole pitch with team discs
- **Lenses:** Casual shows names, sprint speeds and plain-language points. Tactical adds pass trails, a pressure ring on the carrier, the defending team's back line, xG on shots and more detailed wording
- **Timeline:** momentum strip from the stats snapshots (home above the line, away below) with goal markers
- **What's happening:** points detected from events up to the current minute (defensive anchor, winning the duel, finishing against xG). Each point opens an evidence reel of the exact events for and against it. Select a card to watch that moment, after which the view returns to the live match

## Run it

```bash
cd viewer
npm install
npm run dev          # http://localhost:5173
```

The demo match is already packed in `public/data/`. To use another match:

```bash
cd ../matchgen
python -m matchgen generate --seed 587 --script demo --hz 5 --out out/demo5
python -m matchgen snapshots --dir out/demo5 --every 30 --out out/demo5/snapshots.jsonl
cd ../viewer
python tools/pack_match.py ../matchgen/out/demo5 public/data
```

`--hz 5` gives smooth movement. 1 Hz works but players glide. Add `--js` to the pack command to also write `tracking.js`, a base64 copy for hosts that cannot serve binary files.

## Files

```
src/data.ts     loading, Catmull-Rom sampling of tracking, match clock
src/stage.ts    Three.js scene, figures, animation clips, cameras, overlays anchors
src/points.ts   point detectors and evidence (the code agents will later phrase and check)
src/main.ts     app state, playback, live points, evidence reel, replays
tools/pack_match.py   match folder to compact viewer data (int16 tracking, trimmed events)
```

## Known gaps

- Points are templated text. The agent layer will phrase them per lens and check each claim
- No commentator lens yet (needs the history archive wired in)
- Animation clips are procedural and simple by design
