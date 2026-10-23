# Data schema (v0.1.0)

All data is synthetic. Clubs, players and matches are fictional. Definitions here are our own; event types follow the spirit of the open SPADL action format, extended for pressure, tracking and match context.

## Coordinates

- Pitch is 105 m × 68 m. `x` runs 0 to 105 along the length, `y` runs 0 to 68 across.
- Coordinates are **absolute**: the same point on the grass has the same `(x, y)` all match.
- Every event carries `attack_dir`: `+1` means the acting team attacks towards `x = 105`, `-1` towards `x = 0`. Teams swap at half time. `match.json` also lists directions per period.
- To get a team-relative view (own goal at 0): if `attack_dir == -1`, use `(105 - x, 68 - y)`.

## Files

| File | Contents |
| --- | --- |
| `match.json` | Metadata: teams, lineups, formations, styles, player profiles, final score, stoppage time, attack directions, tracking rate |
| `events.jsonl` | One on-ball or match event per line, in time order |
| `tracking.jsonl` | One frame per line: ball and every player on the pitch |

## Event fields

| Field | Type | Notes |
| --- | --- | --- |
| `event_id` | string | `e_000412`. Unique within a match |
| `match_id` | string | |
| `elapsed` | float | Seconds since kick-off, monotonic, includes stoppage time. Use this to sync with tracking |
| `period` | int | 1 or 2 |
| `clock` | string | Broadcast clock, `63:12.4` or `45+2:10.0` |
| `minute` | int | Match minute |
| `team_id`, `player_id` | string | The acting team and player (`player_id` null for some match events) |
| `type` | string | See event types |
| `outcome` | string or null | Type-specific |
| `start`, `end` | `{x, y}` | Absolute metres. `end` null where not meaningful |
| `attack_dir` | int | Acting team's direction, see above |
| `body_part` | string or null | `right_foot`, `left_foot`, `head`, `hands` |
| `possession_id` | int | Increments on every change of possession |
| `possession_team_id` | string | Team in possession when the event happened (defensive events belong to the other team) |
| `sequence_index` | int | Step within the possession, for chain replays |
| `play_pattern` | string | How the possession started: `kickoff`, `regain`, `second_ball`, `throw_in`, `goal_kick`, `corner`, `free_kick`, `penalty`, `keeper` |
| `under_pressure` | bool | An opponent was within 4 m when the action started |
| `pressure_player_id` | string or null | That opponent |
| `related_event_id` | string or null | Links shot to goal, pass to interception, tackle to foul, foul to card |
| `qualifiers` | list | e.g. `cross`, `through_ball`, `switch`, `long_ball`, `throw_in`, `corner`, `penalty`, `set_piece` |
| `extra` | object | Type-specific detail, below |

## Event types

| Type | Outcomes | `extra` |
| --- | --- | --- |
| `pass` | `complete`, `incomplete`, `out`, `offside` | `length_m`, `height` (`ground`, `low`, `high`), `receiver_id`, `ball_speed_kmh` |
| `carry` | `complete`, `dispossessed` | `length_m` |
| `take_on` | `success`, `fail` | `opponent_id` |
| `dribbled_past` | | Defender beaten by a take-on |
| `shot` | `goal`, `saved`, `off_target`, `blocked` | `xg`, `shot_speed_kmh`, `distance_m`, `placement {y, z}` (goal mouth, metres from centre and height), `assist_event_id` |
| `goal` | | `score` after the goal |
| `pressure` | | `target_player_id`, `distance_m` |
| `tackle` | `won`, `lost` | `opponent_id` |
| `interception` | `won` | Pass cut out in flight |
| `ball_recovery` | `won` or null | Loose or overhit ball picked up |
| `clearance` | | |
| `block` | | Shot blocked |
| `aerial_duel` | `won` | `opponent_id` |
| `goalkeeper` | `save`, `claim` | |
| `foul` | | `fouled_player_id`, `in_box` |
| `card` | `yellow`, `second_yellow`, `red` | |
| `offside` | | |
| `ball_out` | | `restart` |
| `substitution` | | `player_out`, `player_in` |
| `period_end` | | `period` |

## Tracking frames

```json
{"match_id": "m_seed20", "elapsed": 3792.0, "period": 2, "clock": "63:12.0",
 "ball": [61.3, 40.2, 0.0],
 "players": [["ARD_07", 58.12, 39.80, 27.4], ["HVL_05", 60.01, 41.22, 18.9]]}
```

- `ball`: `[x, y, z]`, `z` = height in metres
- `players`: `[player_id, x, y, speed_kmh]` for everyone on the pitch
- Rate set by `--hz` (default 1 frame per second; 5 gives smoother replays)
- Sprint threshold used in our metrics: 25.2 km/h

## xG

Our own logistic model on shot distance and the angle of the goal mouth, adjusted for headers, pressure, fast breaks and defenders in the shooting lane (`matchgen/xg.py`). Penalties are 0.76. Calibrated so a typical match lands near 2.8 goals, 13 shots and 1.5 xG per team.
