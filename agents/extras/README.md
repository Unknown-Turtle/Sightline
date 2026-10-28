# agents/extras

Four add-ons to Sightline's agent layer: match ratings, a claim checker, routine detection and insight translations. Code computes every number; a model (Azure AI Foundry, optional) only phrases text; a checker verifies every number and name in anything a model wrote. With no Foundry configuration everything runs in fallback mode with template phrasing and stays valid.

```bash
pip install fastapi uvicorn pytest            # matchgen itself needs nothing
python -m agents.extras all                   # writes every file below from matchgen/sample/demo_seed587
python -m agents.extras ratings               # viewer/public/data/ratings.json
python -m agents.extras claims-sample         # viewer/public/data/claims.sample.json
python -m agents.extras routines              # viewer/public/data/routines.json
python -m agents.extras translate             # viewer/public/data/insights.{es,fr,pt,ar}.json (needs insights.json)
python -m agents.extras claims --t 4700 --claim "Hollow Vale have lost the momentum" --lens casual
uvicorn agents.extras.api:app --port 8010     # POST /api/claims, GET /api/health
python -m pytest agents/extras/tests -q
```

Options: `--dir` another match folder, `--out` another output folder, `--insights` the insights file to translate, `--langs es,fr`. The API reads `SIGHTLINE_MATCH_DIR`.

Foundry: set `FOUNDRY_ENDPOINT`, `FOUNDRY_DEPLOYMENT`, and `FOUNDRY_API_KEY` (or install `azure-identity` and sign in for `DefaultAzureCredential`). Every receipt reports `mode: live | fallback`.

## Modules

| File | What it does |
| --- | --- |
| `common.py` | Loads a match folder, builds name and formation-slot indexes, replays `matchgen.stats.StatsEngine` to any time `t` |
| `ratings.py` | Deterministic ratings, formula in `RATINGS.md`. Every change lists its events in `reasons` |
| `claims.py` | Claim types, classifier (model with keyword fallback), the statistical tests per type, verdicts, narration |
| `checker.py` | Rejects any number or name in model text that is not in the computed results |
| `llm.py` | Minimal Foundry chat client (standard library only) with `available` and `mode` |
| `api.py` | FastAPI app: `POST /api/claims` |
| `routines.py` | Pattern detection from `events.jsonl` and `match.json` only; evaluation against `routines_truth.jsonl` for the report |
| `translate.py` | Per-item translation of `insights.json` text with the checker rerun on every translation |
| `CONTRACT.md` | The shared file and API shapes |

## Claim checker

1. **Classify.** The claim maps to one of: `momentum_lost`, `momentum_gained`, `dominance`, `pressing_working`, `pressing_failing`, `duel_winning`, `duel_losing`, `player_big_game`, `player_poor_game`, `finishing_unlucky`, `finishing_wasteful`, `defensive_collapse`, `tiredness`, or `out_of_scope`. The model classifier returns ids only; its answer is validated against the roster and falls back to the keyword classifier. Team and player mentions are found deterministically from names and surnames. When no team is named, the subject defaults from the momentum index (the team losing momentum for a "lost" claim, and so on).
2. **Test.** Deterministic code runs that type's tests on two `StatsEngine` replays (at `t` and at `t` minus 10 minutes) so "recently" is the difference of cumulative counters, compared with the match average per 10 minutes and with the opponent. For example momentum: final-third entries, xG rate, territory share, field tilt and the 5-minute momentum index. Duels count tackles, take-ons, aerials and fouls between the two players. Big or poor game uses the rating, key actions and losses against the team average. Tiredness uses sprints, metres and pressures per minute from the tracking frames. Each test records `evidence_for` and `evidence_against` event ids.
3. **Verdict.** `supported` when at least two thirds of the tests pass, `partly` from one third, else `not_supported`.
4. **Narrate and check.** In live mode the model phrases casual and tactical summaries from the test list only (in `lang`); the checker rejects any number or name not in the results, retries once with the issues, then uses the template. The template always passes by construction.

`claims.sample.json` holds 8 precomputed claims from the demo match, including a `not_supported` correction (Arden's defence at 58:20) and an `out_of_scope` one (the referee).

## Routine detection

Possessions that start from a goal kick, keeper distribution, or a regain or second ball in the team's own third are candidates. Their opening completed passes become a chain of formation roles (substitutes inherit the slot of the player they replaced) with team-relative end points. The public playbook in `match.json` is the template: steps match in order, each pass ending within 15 m of the step's zone. Role chains that repeat three or more times from the same trigger without a playbook match are reported as `discovered` patterns. The truth file is only read in `evaluate()`, after detection, and the output never contains truth attempt ids.

Demo match (seed 587): event-level precision 1.0, recall 0.918; attempt-level precision 1.0, recall 0.933 (28 of 30 truth attempts). The misses are two `ARD_R2` attempts whose passes ended outside the zone tolerance.

## Translations

Each item's `text` fields go to the model as one JSON object per language. The checker runs on every translation: no number or name may be added, changed or dropped. A failing translation is retried once with the issues, then the English text is kept with `translated: false`. In fallback mode the files are written with English text and `translated: false` on every item, so the viewer can say so.
