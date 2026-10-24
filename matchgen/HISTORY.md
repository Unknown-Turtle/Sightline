# League history archive

`python -m matchgen history --seed 7 --out out/history` writes a fictional five-season history of a 20-club league so a trivia agent can answer questions like "first time Arden have scored first at home against Hollow Vale since 2021" or "is this a record attendance at Arden Park".

Everything is fictional and deterministic per seed. Scores come from a seeded Poisson-style goal model (club strength and home advantage, calibrated to about 2.8 goals a match and a home / draw / away split near 45 / 25 / 30%), not from the match engine. A pre-generated copy for seed 7 is in `sample/history/`.

Seasons covered: 2021-22 to 2025-26 (380 matches each, double round robin, 38 matchdays). The simulated live match belongs to 2026-27. Arden Athletic (`ARD`) and Hollow Vale (`HVL`) use the same ids, names and current squads as the match world, so player ids in `events.jsonl` join directly to `player_careers`.

Every table is written twice: `<table>.csv` and `<table>.jsonl` (one JSON object per row, same columns). `matches.jsonl` holds the full match records and `manifest.json` the seed and row counts.

## clubs

One row per club.

| Column | Meaning |
| --- | --- |
| `id` | Three-letter club id (`ARD`, `HVL`, ...) |
| `name`, `short_name` | Club names |
| `city`, `stadium` | Fictional home city and ground |
| `founded` | Year |
| `capacity` | Stadium capacity, the ceiling for every home attendance |
| `strength` | Base rating (about 62 to 82) that drives the goal model; each season adds a seeded drift |

## results

One row per match, in date order.

| Column | Meaning |
| --- | --- |
| `match_id` | `h_<season start>_<matchday>_<home>_<away>` |
| `season` | `2023-24` |
| `season_start` | 2023 |
| `matchday` | 1 to 38 |
| `date` | ISO date. Matchdays are weekly Saturdays from the second Saturday of August with two-week breaks after matchdays 4, 8 and 12; each matchday has one Friday and three Sunday fixtures |
| `home_id`, `away_id` | Club ids |
| `home_goals`, `away_goals` | Full-time score |
| `ht_home_goals`, `ht_away_goals` | Half-time score (goals up to and including minute 45) |
| `first_scorer_side` | `home`, `away` or `none` |
| `attendance` | Always at or below the home club's capacity; higher against strong opponents and in the Arden against Hollow Vale fixture |
| `home_red_cards`, `away_red_cards` | Counts |
| `goal_minutes` | `12:ARD_09;55:HVL_07` summary of the goals |

`matches.jsonl` adds `goals` (`minute`, `side`, `team_id`, `scorer_id`, `assist_id` or null, `score_after`), `red_cards` (`side`, `team_id`, `player_id`, `minute`) and `lineups` (the 14 players used by each club).

## standings

Final table per season.

| Column | Meaning |
| --- | --- |
| `season`, `position`, `club_id` | |
| `played`, `won`, `drawn`, `lost`, `gf`, `ga`, `gd`, `points` | Three points for a win. Ties broken by goal difference, then goals for, then club id |

## head_to_head

One row per club pair over all five seasons (190 rows). `club_a` sorts before `club_b` in the clubs list order.

| Column | Meaning |
| --- | --- |
| `club_a`, `club_b` | |
| `played`, `a_wins`, `draws`, `b_wins`, `a_goals`, `b_goals` | Totals over all meetings, home and away |
| `last_meeting_date`, `last_meeting` | Most recent fixture, as `HOME h-a AWAY` |

## club_records

Eight rows per club.

| `record` | `value` | `detail` |
| --- | --- | --- |
| `biggest_win` | Winning margin | Date and score line |
| `biggest_defeat` | Losing margin | Date and score line |
| `longest_winning_streak` | Consecutive league wins | |
| `longest_unbeaten_run` | Consecutive league matches without defeat | |
| `record_scorer` | League goals for the club over the five seasons | `player_id name` |
| `record_home_attendance` | | Date and score line |
| `most_points_in_a_season` | Points | Season |
| `highest_finish` | Position | Season |

## player_careers

One row per player per season at a club.

| Column | Meaning |
| --- | --- |
| `player_id` | Current Arden and Hollow Vale players keep their match ids (`ARD_09`); generated players are `<club>_H<nn>` |
| `name`, `position` | |
| `season`, `club_id` | |
| `age` | Age at the start of that season |
| `apps` | Matches in the club's 14-player match-day squad |
| `goals`, `assists` | From the goal records; a goal has an assister 82% of the time |
| `current_squad` | `true` for the players in the live match's squads |

Career continuity: each current player gets a debut season from their age (17 to 20 years old) and a season in which they joined their current club; 70% of them spent the earlier seasons at another club in the league, so some career logs show a transfer. Generated squads have two or three players replaced each season.

## scoring_timeline

One row per goal.

| Column | Meaning |
| --- | --- |
| `match_id`, `season`, `date`, `matchday`, `home_id`, `away_id` | |
| `minute` | 1 to 96 (44% first half, 52% second half, 4% in second-half stoppage time) |
| `side` | `home` or `away` |
| `team_id`, `scorer_id`, `assist_id` | |
| `score_after` | `home-away` after the goal |

## milestones_upcoming

Current players close to a round-number career total over the five recorded seasons.

| Column | Meaning |
| --- | --- |
| `player_id`, `name`, `club_id` | |
| `metric` | `apps` (multiples of 50, within 5), `goals` or `assists` (multiples of 10, within 3) |
| `current`, `milestone`, `remaining` | |

## Reconciliation

`tests/test_history.py` checks that standings reconcile with results, head to head reconciles with results, career goal and assist totals reconcile with the goal records, and that two builds with the same seed are identical.
