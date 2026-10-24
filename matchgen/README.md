# matchgen

Synthetic football match generator (v0.2.0). It simulates a full 90 minutes and produces **event data and tracking data together**, so every pass starts where the ball really is, receivers are picked from players' actual positions, and "under pressure" is measured from real distances. It also ships an incremental stats engine (snapshots at any moment, the same code a live pipeline runs) and a fictional five-season league history for commentator trivia.

All clubs, players, matches and history are fictional. No real match data is used.

## Quick start

Python 3.10+, no dependencies for generating.

```bash
# simulate the demo match: Arden Athletic 3-2 Hollow Vale. Hollow Vale lead 2-0 (30', 59'),
# Arden pull back to 2-2 (73', 77') and a substitute wins it in the 91st minute
python -m matchgen generate --seed 587 --script demo --out out/demo

# full-time team stats for that match
python -m matchgen summary --dir out/demo

# the stats snapshot at any moment of the match
python -m matchgen snapshot --dir out/demo --at 14:00        # also --at 14, --at 45+2:00, --at 90+3:00

# a snapshot every 30 seconds of match time (plus half time and full time) as JSONL
python -m matchgen snapshots --dir out/demo --every 30 --out out/demo/snapshots.jsonl

# replay it as a live feed, 90 minutes in about 3, with a snapshot message every 30 s
python -m matchgen stream --dir out/demo --speed 30 --snapshots 30

# events only, starting from the 55th minute
python -m matchgen stream --dir out/demo --speed 10 --no-frames --start-minute 55

# five seasons of fictional league history (CSV and JSONL tables, see HISTORY.md)
python -m matchgen history --seed 7 --out out/history
```

Pre-generated copies are in `sample/demo_seed587/` (match, events, 1 Hz tracking, routine ground truth, snapshots every 30 s) and `sample/history/`. In the demo match the boosted centre back `ARD_05` makes 25 defensive actions, twice as many as any other Arden player, and Arden's one big chance that does not go in is saved in the 23rd minute. The seed was found with `python scripts/find_demo_seed.py`, which searches for exactly that story.

## What a match folder contains

| File | Contents |
| --- | --- |
| `match.json` | Teams, lineups, styles, player profiles, final score, referee, weather, attendance, kick-off time, matchday, stakes, the teams' rehearsed-routine playbooks |
| `events.jsonl` | One event per line with score state, possession summaries, pass context (progressive, direction, difficulty), shot context (defenders in lane, keeper position, first time, one on one, counter, xG factors) and assist links |
| `tracking.jsonl` | Ball and every player on the pitch, 1 Hz by default (`--hz 5` for smoother replays) |
| `routines_truth.jsonl` | Which passes were part of a rehearsed routine attempt. Kept out of `events.jsonl` so detection code can be evaluated honestly |
| `snapshots.jsonl` | Optional: stats snapshots at a fixed interval |

Every field is documented in `SCHEMA.md`; the history tables in `HISTORY.md`.

## Streaming to Azure Event Hubs

```bash
pip install azure-eventhub
export EVENTHUB_CONNECTION_STRING="Endpoint=sb://..."
export EVENTHUB_NAME="match-events"
python -m matchgen stream --dir out/demo --speed 30 --sink eventhub --snapshots 30
```

Messages are `{"kind": "event" | "frame" | "snapshot" | "match_start" | "match_end", "data": {...}}`, partitioned by `match_id`, with `kind` also set as an Event Hubs property so consumers can filter.

## Stats engine

`matchgen/stats.py` is a dependency-free library that consumes events and frames in time order and can produce a full snapshot at any moment:

```python
from matchgen.stats import StatsEngine
engine = StatsEngine(meta)            # meta = match.json dict
engine.ingest_event(event)            # any order-preserving stream
engine.ingest_frame(frame)
snap = engine.snapshot()              # JSON-serialisable dict
```

A snapshot carries the clock and score, cumulative team metrics (xG, big chances, progressive passes, final-third and box entries, possession share, field tilt, territory, PPDA, high turnovers, counter-press regains, set pieces, discipline, distance, sprints, pass network ...), a rolling `last_5_min` block with `momentum`, `control` and `chaos` indices from 0 to 100, and cumulative player metrics (touches, passing, key passes, assists, xA, shooting, carries, take-ons, defending, duels, pressures, physical load, keeper saves and goals prevented) with `on_pitch` and `minutes`. The formulas are in the module docstrings and `SCHEMA.md`. `summary.py` delegates to it, so there is one source of truth.

## Storylines

A script biases the simulation so a demo match has drama on cue. It never forces a goal; it shifts momentum, control and pressing for a team over a window of minutes, boosts standout players (attributes and how often they get involved), schedules a red card, or overrides the match context.

```json
{
  "segments": [
    {"from": 55, "to": 75, "team": "HVL", "momentum": 0.45, "press": 0.5},
    {"from": 75, "to": 95, "team": "ARD", "momentum": 0.5, "control": 0.2}
  ],
  "standouts": [{"player": "ARD_05", "boost": 12}],
  "red_cards": [{"minute": 68, "team": "HVL", "player": "HVL_05"}],
  "context": {"weather": "rain", "stakes": "relegation six-pointer"}
}
```

```bash
python -m matchgen generate --seed 1 --script examples/demo_script.json --out out/m1
```

With the demo script, the boosted centre back `ARD_05` averages about 12 to 15 defensive actions a match against about 8 to 9 for the other Arden centre back over 20 seeds (`python scripts/calibrate.py 40 --demo` prints the comparison). Teams also have a hidden momentum random walk, so matches swing on their own without a script.

## Editing the world

```bash
python -m matchgen world --out world.json      # export clubs, squads, attributes, styles, routines
# rename clubs, change formations (4-3-3, 3-4-2-1, 4-2-3-1), tweak attributes, edit routines
python -m matchgen generate --world world.json --seed 3 --out out/custom
```

Style dials per team: `directness`, `press`, `control`, `rehearsed` (how often the team attempts one of its named build-up routines at goal kicks, keeper distribution and own-third regains). The world JSON can also carry `venue_capacity` and a `context` block (referee, weather, attendance, kick-off, matchday, stakes).

## Realism check

Averages over 40 unscripted matches (`python scripts/calibrate.py 40`), against typical top-flight values. The script flags anything outside the target range.

| Per team per match unless noted | matchgen | Target range |
| --- | --- | --- |
| Goals (match total) | 2.85 | 2.5 to 3.2 |
| Shots | 13.7 | 11.5 to 14.5 |
| xG | 1.47 | 1.2 to 1.7 |
| xG per shot | 0.108 | 0.09 to 0.13 |
| Passes | 561 | 450 to 620 |
| Pass accuracy | 82.8% | 80 to 87% |
| Tackles | 19.2 | 15 to 24 |
| Fouls | 9.4 | 9 to 13 |
| Yellow cards | 1.75 | 1.4 to 2.4 |
| Sprints (25.2 km/h and above) | 297 | 200 to 320 |
| Top speed | 31.4 km/h | 30.5 to 34 km/h |
| Penalties (match total) | 0.33 | 0.15 to 0.45 |
| Keeper passes | 25.5 | about 25 to 35 |
| Corners (match total) | 3.7 | about 10 |
| Throw-ins (match total) | 35 | about 40 |
| Big chances | 1.2 | about 1.5 to 2.5 |

Aggregate goals track aggregate xG to within a few percent (blocked shots keep their pre-block xG). Run `python -m pytest tests` for the invariants: determinism, clock, score matches goals, coordinates on the pitch, red cards remove players, event locations match the tracking ball, keeper stays in the box, no walk-in carries, every restart has a `ball_out`, assist links, possession summaries, the stats engine against independent counts, and history reconciliation.

## How it works

- **Engine** (`matchgen/engine.py`): a possession state machine. Each action on the ball (pass, carry, take-on, cross, shot, clearance, rehearsed routine step) is chosen from zone, pressure, player attributes, team style and momentum, then played out in a 5 Hz physics step.
- **Movement**: players hold a formation shape that shifts with the ball, chase it when nearest, mark attackers goal-side near their own box, and move with limited speed and acceleration based on pace and fatigue. The keeper steps out to an unmarked attacker close to goal but never leaves the box.
- **Set pieces**: kick-offs, throw-ins, goal kicks, corners, free kicks (direct shots or crosses), penalties, keeper distribution. Every ball out of play emits a `ball_out` event.
- **Discipline and rotation**: fouls, yellows (scaled by referee strictness), second yellows, reds, offsides, and 3 to 5 substitutions from minute 56.
- **xG** (`matchgen/xg.py`): our own transparent model with named multipliers (header, pressure, counter, lane, keeper) written on every shot; see `SCHEMA.md`.
- **Stats** (`matchgen/stats.py`): incremental, deterministic, standard library only.
- **History** (`matchgen/history.py`): a seeded Poisson-style goal model over five seasons of 380 matches, with career continuity for the current squads.

## Layout

```
matchgen/
  world.py     fictional clubs, squads, formations, routines
  engine.py    simulation
  xg.py        expected goals
  script.py    storylines
  stats.py     incremental stats engine and snapshots
  history.py   fictional league history
  stream.py    live replay to stdout or Event Hubs
  summary.py   full-time team stats (delegates to stats.py)
  io.py        read and write match folders
scripts/
  calibrate.py       realism check over N seeds
  find_demo_seed.py  seed search for the demo story
tests/         invariant tests
sample/        pre-generated demo match and history
SCHEMA.md      every event and match field explained
HISTORY.md     every history table and column explained
```

## Known gaps

- Tracking is 1 Hz by default (`--hz 5` for smoother replays, at five times the file size)
- Corners (about 4 a match against about 10) and throw-ins run low; distance covered is slightly low
- No offside line modelling beyond through balls; no goalkeeper sweeping outside the box
- Possession share is estimated from gaps between events, not from frame-level ball ownership
- History covers league matches only (no cups), and the goal model is independent Poisson per side
