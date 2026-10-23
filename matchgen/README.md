# matchgen

Synthetic football match generator. It simulates a full 90 minutes and produces **event data and tracking data together**, so every pass starts where the ball really is, receivers are picked from players' actual positions, and "under pressure" is measured from real distances.

All clubs, players and matches are fictional. No real match data is used.

## Quick start

Python 3.10+, no dependencies for generating.

```bash
# simulate the demo match (Arden Athletic 2-1 Hollow Vale, comeback in the 86th and 93rd minute)
python -m matchgen generate --seed 89 --script demo --out out/demo

# team stats for that match
python -m matchgen summary --dir out/demo

# replay it as a live feed, 90 minutes in about 3
python -m matchgen stream --dir out/demo --speed 30

# events only, starting from the 55th minute
python -m matchgen stream --dir out/demo --speed 10 --no-frames --start-minute 55
```

A pre-generated copy of the demo match is in `sample/demo_seed89/`.

## Streaming to Azure Event Hubs

```bash
pip install azure-eventhub
export EVENTHUB_CONNECTION_STRING="Endpoint=sb://..."
export EVENTHUB_NAME="match-events"
python -m matchgen stream --dir out/demo --speed 30 --sink eventhub
```

Messages are `{"kind": "event" | "frame" | "match_start" | "match_end", "data": {...}}`, partitioned by `match_id`, with `kind` also set as an Event Hubs property so consumers can filter.

## Storylines

A script biases the simulation so a demo match has drama on cue. It never forces a goal; it shifts momentum, control and pressing for a team over a window of minutes, boosts standout players, or schedules a red card.

```json
{
  "segments": [
    {"from": 55, "to": 75, "team": "HVL", "momentum": 0.45, "press": 0.5},
    {"from": 75, "to": 95, "team": "ARD", "momentum": 0.5, "control": 0.2}
  ],
  "standouts": [{"player": "ARD_05", "boost": 12}],
  "red_cards": [{"minute": 68, "team": "HVL", "player": "HVL_05"}]
}
```

```bash
python -m matchgen generate --seed 1 --script examples/demo_script.json --out out/m1
```

In testing over 14 seeds, a 20-minute Hollow Vale surge roughly doubled their shots in that window and cut Arden's xG sharply.

Teams also have a hidden momentum random walk, so matches swing on their own without a script.

## Editing the world

```bash
python -m matchgen world --out world.json      # export clubs, squads, attributes, styles
# rename clubs, change formations (4-3-3, 3-4-2-1, 4-2-3-1), tweak attributes
python -m matchgen generate --world world.json --seed 3 --out out/custom
```

## Realism check

Averages over 40 simulated matches, against typical top-flight values:

| Per team per match | matchgen | Typical |
| --- | --- | --- |
| Goals (match total) | 2.8 | 2.7 to 3.3 |
| Shots | 12.9 | 12 to 14 |
| xG | 1.6 | 1.3 to 1.6 |
| xG per shot | 0.13 | 0.10 to 0.12 |
| Passes | 560 | 450 to 600 |
| Pass accuracy | 84% | 80 to 86% |
| Tackles | 21 | 15 to 20 |
| Fouls | 10 | 10 to 12 |
| Yellow cards | 1.6 to 2.3 | about 2 |
| Throw-ins (match) | about 31 | about 40 |
| Sprints (> 25.2 km/h) | about 280 | 200 to 300 |
| Top speed | 31 to 32 km/h | 32 to 35 km/h |
| Distance per outfield player | 9.6 km | 10 to 11.5 km |

Run it yourself: `python -m pytest tests` checks the invariants (determinism, clock, score matches goals, coordinates on the pitch, red cards remove players, event locations match the tracking ball).

## How it works

- **Engine** (`matchgen/engine.py`): a possession state machine. Each action on the ball (pass, carry, take-on, cross, shot, clearance) is chosen from zone, pressure, player attributes, team style and momentum, then played out in a 5 Hz physics step.
- **Movement**: players hold a formation shape that shifts with the ball, chase it when nearest, mark attackers goal-side near their own box, and move with limited speed and acceleration based on pace and fatigue.
- **Set pieces**: kick-offs, throw-ins, goal kicks, corners, free kicks (direct shots or crosses), penalties, keeper distribution.
- **Discipline and rotation**: fouls, yellows, second yellows, reds, offsides, and 3 to 5 substitutions from minute 56.
- **xG** (`matchgen/xg.py`): our own transparent model; see `SCHEMA.md`.

## Layout

```
matchgen/
  world.py     fictional clubs, squads, formations
  engine.py    simulation
  xg.py        expected goals
  script.py    storylines
  stream.py    live replay to stdout or Event Hubs
  summary.py   team stats for calibration
  io.py        read and write match folders
tests/         invariant tests
sample/        pre-generated demo match
SCHEMA.md      every field explained
```

## Known gaps

- Tracking is 1 Hz by default (`--hz 5` for smoother replays, at five times the file size)
- Throw-ins and distance covered run slightly low
- No goalkeeper sweeping, no offside line modelling beyond through balls
- No history archive yet (needed for commentator trivia)
