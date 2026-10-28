# Contract additions (Agent D)

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

## Extra fields this implementation adds

Everything above is present. These fields are additions a renderer may ignore:

- `ratings.json`: top level `match_id`, `weights`, `start`, `clamp`, `ramp_minutes`, `damp`; each entry also has `minutes`.
- `routines.json`: top level `match_id`, `method`, `zone_tolerance_m` and a match-wide `evaluation` (`precision`, `recall`, `attempt_precision`, `attempt_recall`); each pattern has `trigger`, `source` (`playbook` or `discovered`), `steps`, `completed`; each attempt has `clock`, `possession_id`, `steps_matched`, `steps_total`.
- `insights.<lang>.json`: top level `lang`, `translated`, `translation_mode`, `translation_model`, `note` (fallback only); each item has `translated` and `translation_check`.
- `claims.sample.json`: `{ "match_id", "mode", "model", "claims": [response, ...] }` where every response is the API shape plus `match_id`, `t`, `clock`, `lens`, `lang`, `claim_type`, `subject`, and `check.issues`.
- Claim response `receipt` also carries `tokens_in`, `tokens_out`, `classifier` (`model` or `keywords`).
