# Match ratings

`python -m agents.extras ratings` writes `viewer/public/data/ratings.json`: a rating from 0 to 10 for every player who has been on the pitch, recomputed every 60 seconds of match time. The rating is deterministic and fully traceable: every change lists the events that caused it.

## Formula

```
rating(t) = clamp(6.0 + 0.75 x scale(minutes) x sum(effect of every event by the player up to t), 3.0, 10.0)
scale(minutes) = min(1, minutes played / 20)
```

Every player starts at 6.0. Each event adds or subtracts a small weight. The sum is damped by 0.75 (so a full match of volume actions stays inside the scale) and ramped in over the first 20 minutes a player spends on the pitch so a substitute's single early action cannot swing the rating, then clamped to 3.0 to 10.0. Minutes are counted from kick-off or the substitution, to the substitution off, red card or the current time.

## Weights

| Event | Effect |
| --- | --- |
| Goal | +1.0 |
| Assist (passer of the goal) | +0.5 |
| Key pass (passer of any shot) | +0.1, plus +0.6 x xG of the shot as xA |
| Shot | +0.6 x xG of the shot; on target (saved) +0.15; off target -0.05; blocked 0 |
| Big chance missed (xG 0.35 or more, no goal) | -0.3 |
| Progressive pass completed | +0.03 (plus +0.02 into the final third, +0.04 into the box) |
| Cross completed | +0.05 |
| Pass lost | -0.05 |
| Take-on | won +0.1, lost -0.08 |
| Progressive carry (10 m or more towards goal) | +0.04 |
| Dispossessed | -0.1 |
| Beaten by a dribble | -0.1 |
| Tackle | won +0.12, lost -0.08 |
| Interception | +0.12 |
| Clearance | +0.08 |
| Shot blocked | +0.2 |
| Loose ball recovered | +0.03 |
| Aerial duel won | +0.08 |
| Foul conceded | -0.08 |
| Cards | yellow -0.3, second yellow -0.5, red -1.0 |
| Offside | -0.03 |
| Error leading to a shot or goal | -0.4 (a pass, carry or take-on lost in own third followed by an opponent shot within 10 s) |
| Keeper save | +0.3 plus the xG of the shot (goals prevented) |
| Keeper claim | +0.05 |
| Keeper goal conceded | -0.2 |

## File shape

```json
{ "every_s": 60, "formula": "...", "weights": {...},
  "players": { "ARD_05": [{ "t": 600.0, "rating": 6.4, "delta": 0.2, "minutes": 10.0,
    "reasons": [{ "event_id": "e_000201", "label": "Interception in own box", "effect": 0.2 }] }] } }
```

`delta` is the change since the previous tick. `reasons` are the events in that minute; `effect` is the raw weight before damping and the minutes ramp. Summing `effect` over all ticks for a player reproduces the same total as walking the event log, which `tests/test_ratings.py` checks.
