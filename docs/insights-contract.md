# Sightline shared contract

<!-- Copied verbatim from prompts/agent-C.md. All six agents build against this. -->


All six agents follow this so their outputs line up.

### `insights.json`

All three prompts use this file format. Agent A produces it, Agent B renders it, Agent C documents it.

```json
{
  "match_id": "m_seed587",
  "generated_at": "2026-10-28T04:30:00Z",
  "mode": "live | fallback",
  "model": "deployment name or null",
  "items": [
    {
      "id": "i_0001",
      "t": 4356.0,
      "clock": "72:36",
      "kind": "anchor | duel | finishing | momentum | score_state | recap",
      "point_id": "anchor-ARD_05",
      "team": "ARD",
      "subject": "ARD_05",
      "text": {
        "casual": "one or two plain sentences",
        "tactical": "one or two sentences with the numbers",
        "commentator": "one line of context or trivia a commentator could say on air"
      },
      "evidence_for": ["e_000123"],
      "evidence_against": ["e_000456"],
      "trivia": [{ "text": "...", "source": "head_to_head.csv", "row": "ARD,HVL" }],
      "check": { "passed": true, "numbers_checked": 4, "retries": 0, "issues": [] },
      "receipt": { "model": "...", "latency_ms": 1840, "tokens_in": 1200, "tokens_out": 140, "agents": ["analyst", "narrator", "checker", "trivia"] }
    }
  ]
}
```

`t` is match `elapsed` seconds (the same clock as events and tracking). An item is visible in the app once playback passes `t`, and stays until a newer item with the same `point_id` replaces it. `recap` items are written at half time and full time.

### Contract additions

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

### Deployment environment variables

Written by `infra/deploy.sh` (Agent C) and read by the agent layer and the live pipeline.

| Variable | Meaning |
| --- | --- |
| `FOUNDRY_ENDPOINT` | AI Services account endpoint, for example `https://sightline-ai-xxxx.cognitiveservices.azure.com/` (OpenAI compatible routes live under it) |
| `FOUNDRY_PROJECT_ENDPOINT` | Foundry project endpoint, `https://<account>.services.ai.azure.com/api/projects/<project>` |
| `FOUNDRY_DEPLOYMENT` | Model deployment name, for example `gpt-4.1-mini` |
| `FOUNDRY_API_KEY` | Optional. Key auth fallback. Without it, code should use `DefaultAzureCredential` (the owner's `az login`, or the managed identity in Azure) |
| `AZURE_CLIENT_ID` | Client id of the user-assigned managed identity, set on hosted compute only |
| `APPLICATIONINSIGHTS_CONNECTION_STRING` | Telemetry for hosted compute |

When no Foundry variables are set, agents write `"mode": "fallback"` and `"model": null`.

### Live module interface (`live/infra/live.bicep`, Agent E)

`infra/deploy.sh` deploys this file as a second deployment into the same resource group after `infra/main.bicep`, and passes only the parameters the file declares, from this list:

| Parameter | Value |
| --- | --- |
| `location` | Resource group location (`uksouth`) |
| `namePrefix` | `sightline` |
| `identityId` | Resource id of the user-assigned managed identity |
| `identityClientId` | Client id of that identity |
| `identityPrincipalId` | Principal id of that identity |
| `storageAccountName` | Storage account name |
| `appInsightsConnectionString` | Application Insights connection string |
| `logAnalyticsWorkspaceId` | Log Analytics workspace resource id |
| `foundryEndpoint` | As `FOUNDRY_ENDPOINT` |
| `foundryDeployment` | As `FOUNDRY_DEPLOYMENT` |
| `staticWebAppName` | Static Web App resource name |

Outputs named `webPubSubEndpoint`, `functionAppUrl` or `claimsApiUrl`, if present, are printed at the end of the deploy.
