# Data schema (v0.2.0)

All data is synthetic. Clubs, players and matches are fictional. Definitions here are our own; event types follow the spirit of the open SPADL action format, extended for pressure, tracking and match context.

Changes from 0.1.0 are marked **new**.

## Coordinates

- Pitch is 105 m x 68 m. `x` runs 0 to 105 along the length, `y` runs 0 to 68 across.
- Coordinates are **absolute**: the same point on the grass has the same `(x, y)` all match.
- Every event carries `attack_dir`: `+1` means the acting team attacks towards `x = 105`, `-1` towards `x = 0`. Teams swap at half time. `match.json` also lists directions per period.
- To get a team-relative view (own goal at 0): if `attack_dir == -1`, use `(105 - x, 68 - y)`. Definitions below that mention "team-relative x" mean this frame.

## Files

| File | Contents |
| --- | --- |
| `match.json` | Metadata: teams, lineups, formations, styles, player profiles, final score, stoppage time, attack directions, tracking rate, match context |
| `events.jsonl` | One on-ball or match event per line, in time order |
| `tracking.jsonl` | One frame per line: ball and every player on the pitch |
| `snapshots.jsonl` | Optional: stats snapshots at a fixed interval (`python -m matchgen snapshots`), see `matchgen/stats.py` |

## match.json

| Field | Notes |
| --- | --- |
| `schema_version` | `0.2.0` |
| `match_id`, `competition`, `venue`, `home_team_id`, `away_team_id` | |
| `final_score` | `{team_id: goals}` |
| `stoppage_seconds` | Per period |
| `duration_elapsed_s`, `pitch`, `attack_direction`, `tracking_hz` | |
| `lineups` | Per team: formation, style dials, starting XI with formation slots, bench |
| `players` | Full profiles (attributes 1 to 99, age, foot, nationality) for both squads |
| `referee` **new** | `{name, strictness}`. Strictness in 0 to 1 scales the foul-to-card probability by `0.7 + 0.6 x strictness` |
| `weather` **new** | `clear`, `overcast`, `rain`, `wind` or `cold`. Rain lowers every pass's completion probability by 0.015; wind lowers passes over 30 m by 0.04 |
| `attendance` **new** | Integer, always at or below `venue_capacity` |
| `venue_capacity` **new** | Integer, from the world (`venue_capacity`, default 31400) |
| `kickoff_local` **new** | Local kick-off time, `"15:00"` |
| `matchday` **new** | 1 to 38 |
| `stakes` **new** | Free text, for example `"top-four race"` |

The context block is generated from the seed. Any field can be overridden with a `context` object in the world JSON or the script JSON (script wins). Overrides never change the rest of the simulation for that seed.

## Event fields

| Field | Type | Notes |
| --- | --- | --- |
| `event_id` | string | `e_000412`. Unique within a match, sequential |
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
| `possession_id` | int | Increments on every change of possession (and on every restart) |
| `possession_team_id` | string | Team in possession when the event happened (defensive events belong to the other team) |
| `sequence_index` | int | Step within the possession, for chain replays |
| `play_pattern` | string | How the possession started: `kickoff`, `regain`, `second_ball`, `throw_in`, `goal_kick`, `corner`, `free_kick`, `penalty`, `keeper` |
| `under_pressure` | bool | An opponent was within 4 m when the action started |
| `pressure_player_id` | string or null | That opponent |
| `related_event_id` | string or null | Links shot to goal, pass to interception, tackle to foul, foul to card |
| `qualifiers` | list | e.g. `cross`, `through_ball`, `switch`, `long_ball`, `throw_in`, `corner`, `penalty`, `set_piece` |
| `score` **new** | `{home_id: n, away_id: n}` | The score when the event happened. The `goal` event shows the score after the goal; the `shot` with outcome `goal` shows it before |
| `extra` | object | Type-specific detail, below |

## Event types

| Type | Outcomes | `extra` |
| --- | --- | --- |
| `pass` | `complete`, `incomplete`, `out`, `offside` | `length_m`, `height` (`ground`, `low`, `high`), `receiver_id`, `ball_speed_kmh`, plus the pass context below |
| `carry` | `complete`, `dispossessed` | `length_m` |
| `take_on` | `success`, `fail` | `opponent_id` |
| `dribbled_past` | | Defender beaten by a take-on |
| `shot` | `goal`, `saved`, `off_target`, `blocked` | `xg`, `shot_speed_kmh`, `distance_m`, `placement {y, z}` (goal mouth, metres from centre and height, on-target shots only), plus the shot context below |
| `goal` | | `score` after the goal, `assist_event_id` (null if unassisted) |
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
| `ball_out` | | `restart`: `throw_in`, `corner` or `goal_kick`. Emitted every time the ball leaves play; `team_id` is the team that put it out (so a `corner` goes to the other team, as do `throw_in` and `goal_kick`) |
| `substitution` | | `player_out`, `player_in` |
| `period_end` | | `period`, `prev_possession` (the possession running at the whistle) |

### Pass context **new**

On every `pass` (crosses included). All definitions use the team-relative frame and the **intended target** of the pass, so an incomplete pass is described by where it was aimed, while its `end` is where it was cut out or went out of play.

| Field | Definition |
| --- | --- |
| `progressive` | The pass ends at least 25% closer to the centre of the opponent goal than it started, or ends inside the penalty box having started outside it |
| `into_final_third` | Starts at team-relative x below 70 and ends at or beyond 70 |
| `into_box` | Ends inside the penalty box having started outside it |
| `direction` | `forward` when the gain towards goal is at least 40% of the pass length (and at least 2 m), `backward` when the loss is, otherwise `lateral` |
| `difficulty` | 0 to 1: `0.012 x length_m + 0.15 if under pressure + 0.07 per opponent within 5 m of the target (max 3) + 0.15 if line-breaking + 0.08 if the ball is in the air + 0.10 if it ends in the final third`, capped at 1. Line-breaking: forward by more than 5 m with three or more outfield opponents between the start and end x |
| `key_pass` | `true` when a shot followed this pass (see assists). Written when the shot happens, so it is present in `events.jsonl` but not yet known at the moment the pass is streamed |
| `assist` | `true` when that shot was a goal. Same timing note |

### Shot context **new**

On every `shot`.

| Field | Definition |
| --- | --- |
| `xg` | Expected goals, see xG below |
| `xg_factors` | `{base, header, pressure, counter, lane, keeper}`: the location-only value and every multiplier applied to it (`xg = base x the rest`, clamped to 0.005 to 0.95). Direct free kicks add `free_kick`; penalties have base 0.76 and all multipliers 1 |
| `defenders_in_lane` | Outfield opponents between the ball and the goal within 3 m of the line to the goal centre (the count the `lane` factor uses) |
| `gk_position` | `{x, y}` of the opposing keeper when the shot was struck (absolute) |
| `gk_distance_m` | Distance from the ball to that keeper |
| `first_time` | The shooter received a pass less than 1.2 s earlier and had no carry or take-on in between. Always `false` for penalties and direct free kicks |
| `one_on_one` | No outfield defender in the lane and the keeper is the only opponent within 8 m |
| `counter` | The possession began with a regain (`play_pattern == "regain"`) in the team's own half less than 15 s before the shot |
| `assist_event_id`, `assist_type` | Set when the last completed pass in this possession went to the shooter. The shooter's own carries and take-ons after receiving do not break the link; any other on-ball event does. `assist_type` is one of `cutback` (pass from team-relative x at or above 96 travelling backwards into the area between x 84 and 100, within 14 m of the centre line), `cross`, `through_ball`, `set_piece` (first pass of a corner, free kick or throw-in, or any pass tagged `set_piece`) or `pass` |

Assists are written in two places: forwards on the shot (`assist_event_id`, available live) and backwards on the pass (`key_pass`, `assist`), which the engine fills in memory before the files are written. A live consumer should credit key passes and assists from the shot event; the stats engine does exactly that.

### Possession summaries **new**

The first event of every possession (whatever its type) carries `extra.prev_possession` describing the one that just ended:

```json
{"possession_id": 41, "team_id": "HVL", "end_reason": "interception", "duration_s": 12.4, "passes": 3}
```

- `end_reason`: `shot`, `goal`, `tackle`, `interception`, `recovery`, `out_of_play`, `foul`, `offside`, `keeper` (claimed cross or keeper collection), `period_end`
- `duration_s`: from the first to the last on-ball action of the possession (dead-ball waits are not counted)
- `passes`: pass attempts in the possession, crosses included

The `period_end` event carries the summary of the possession running at the whistle, and the second-half kick-off does not repeat it. Possession ids are contiguous, so every possession is summarised exactly once.

## Rehearsed routines **new**

Each team may define 2 or 3 named build-up routines in the world JSON (`routines` on the team) as a short sequence of role-to-role passes with target zones in the team-relative frame:

```json
{"id": "ARD_R1", "name": "keeper to pivot to striker drop-off to runner", "trigger": "goal_kick",
 "steps": [{"from": "GK", "to": "CDM", "zone": [24, 34]}, {"from": "CDM", "to": "ST", "zone": [52, 34]}]}
```

- `trigger`: `goal_kick`, `keeper` (keeper distribution) or `regain_own_third` (a regain or second ball won inside the team's own third). `from` may be `"*"` for whoever has the ball.
- At a trigger the team attempts a matching routine with probability `style.rehearsed`. The receiver of each step runs to its zone; a step is skipped with probability 0.6 when the carrier is under pressure (`broken_pressure`), ends when a pass is not completed (`broken_pass`), when the ball is lost before the next pass (`lost_possession`), or when the wrong player ends up on the ball or a restart interrupts (`abandoned`).
- The definitions (the playbook) are public in `match.json` under each lineup's `routines`.
- Which events belonged to an attempt is written **only** to `routines_truth.jsonl`, never into `events.jsonl`, so detection code can be evaluated honestly:

```json
{"attempt_id": "r_0007", "routine_id": "ARD_R1", "team_id": "ARD", "trigger": "goal_kick", "possession_id": 58,
 "start_elapsed": 1210.4, "end_elapsed": 1221.8, "steps_completed": 3, "steps_total": 3,
 "event_ids": ["e_000402", "e_000404", "e_000405"], "outcome": "completed"}
```

Attempts that ended before any pass was played are not recorded.

## Tracking frames

```json
{"match_id": "m_seed20", "elapsed": 3792.0, "period": 2, "clock": "63:12.0",
 "ball": [61.3, 40.2, 0.0],
 "players": [["ARD_07", 58.12, 39.80, 27.4], ["HVL_05", 60.01, 41.22, 18.9]]}
```

- `ball`: `[x, y, z]`, `z` = height in metres
- `players`: `[player_id, x, y, speed_kmh]` for everyone on the pitch
- Rate set by `--hz` (default 1 frame per second; 5 gives smoother replays)
- Sprint threshold used in our metrics: 25.2 km/h; high intensity 19.8 to 25.2 km/h

## xG

Our own logistic model on shot distance and the angle of the goal mouth (`matchgen/xg.py`), multiplied by named factors: header 0.55, pressure 0.8, counter 1.15, lane 0.72 per defender (max four), keeper 0.4 to 1.0 when the keeper has come out to within 6 m of a shot inside roughly 17 m. Penalties are 0.76; direct free kicks 0.6 x the open-play value capped at 0.12. Every shot carries the breakdown in `xg_factors`. Calibrated so a typical match lands near 2.9 goals, 13.5 shots and 1.45 xG per team, with aggregate goals close to aggregate xG (blocked shots keep their pre-block xG, so unblocked conversion runs above xG).
