# Sightline live pipeline

The real-time path: a matchgen replay goes in, contract live messages (`live/CONTRACT.md`) come out to the viewer. The same `live/pipeline.py` runs on a laptop with no Azure and inside the Azure Functions app.

```
                      LOCAL (no Azure)
 matchgen sample  -->  python -m live.local  --ws://localhost:8787/ws-->  viewer #live
 (events+frames)       pipeline.py + aiohttp       POST /api/claims

                      AZURE
 python -m matchgen    Event Hubs          Function App (Flex Consumption)        Web PubSub (Free)
 stream --sink     --> match-events    --> match_events: pipeline.py       -->  hub "match"        --> viewer
 eventhub              (partition key      negotiate  GET  /api/negotiate       group = match_id       #live=https://<app>
                        = match_id)        claims     POST /api/claims  <------------------------------ (claim checker)
                                           system identity: Event Hubs Data Receiver, Web PubSub Service Owner,
                                           Azure AI User on the Foundry account, Storage roles for the host
```

## What the pipeline does

`Pipeline(meta).feed(kind, data)` takes matchgen stream messages in match-time order and returns live messages:

- **snapshot** from `matchgen.stats.StatsEngine`, run incrementally on every event and frame: at kick-off, every 30 s of match time, at half time and full time. A local client that joins mid-match gets the latest snapshot plus every insight, rating and event so far.
- **event**, sent instantly: goals, cards, big chances (shots with xG 0.35 or more) and `period_end`, plus `match_start` and `match_end` control events.
- **insight** and **rating**, item by item as in `insights.json` and `ratings.json`. If `agents.live.LiveDetector(meta)` imports (Agent A), its `ingest_event(event) -> [items]` runs on every event. Otherwise a stub releases the precomputed items in `viewer/public/data/insights.json` once match time passes each `t`. Ratings work the same way with `agents.extras.ratings.LiveRatings(meta)` or `ratings.json`. A rating message adds `"player": "<player_id>"` to the series entry. A missing file just means that kind is not sent.
- **claims**: `POST /api/claims` calls Agent D's `agents.extras.api` (the first of `check_claim`, `handle_claim`, `claims`, `handle` or `check`; sync or async, taking the body as one dict or as keyword arguments). Without it, the endpoint answers from `claims.sample.json` by exact claim text, or returns `out_of_scope`.

## Run it locally

```bash
pip install -r live/requirements.txt          # aiohttp
python -m live.local --match matchgen/sample/demo_seed587 --speed 30
# options: --start-minute 55, --loop, --port 8787, --snapshot-every 30, --data <folder with insights.json ...>
cd viewer && npm run dev                      # open http://localhost:5173/#live
```

Endpoints: `ws://localhost:8787/ws` (also `/`), `GET /api/negotiate`, `POST /api/claims` and `GET /api/health`.

Tests: `pip install pytest azure-functions azure-identity azure-messaging-webpubsubservice`, then `python -m pytest live/tests`. The tests cover a snapshot within a second at high speed, message shapes against the contract, insights and ratings unchanged item by item, claims, and the Functions trigger publishing to the match group (with a fake Web PubSub client).

## Run it on Azure

```bash
./live/deploy.sh <resource-group> [foundry-account-name]
```

This one script:

1. deploys `live/infra/live.bicep`: Event Hubs Basic with hub `match-events`, Web PubSub Free, a Flex Consumption Function App (Python 3.11) with a system-assigned identity and its role assignments, and a storage account with shared keys disabled.
2. stages `live/functions/` with `live/`, `matchgen/`, `agents/` (if present), the match's `match.json` and the viewer data files (`python live/functions/stage.py`), then publishes with `func` or, if `func` is missing, with a zip deploy.
3. prints the viewer URL and starts the replay: `python -m matchgen stream --sink eventhub`.

Set `SKIP_INFRA=1`, `SKIP_PUBLISH=1` or `SKIP_REPLAY=1` to rerun only part of it. `SPEED` and `MATCH` set the replay speed and match folder. The Function App uses only its managed identity (`EventHubConnection__fullyQualifiedNamespace`, `DefaultAzureCredential` for Web PubSub, `AzureWebJobsStorage__accountName`). The one key in the flow is the replay's Event Hubs connection string: `matchgen stream` only accepts a connection string, so the script reads it at run time and never stores it.

**Scaling and state.** Each match's pipeline state is in memory on the instance that owns the partition. matchgen uses `match_id` as the partition key, so a match stays on one partition, and Event Hubs hands each partition to one consumer at a time, in order. Many matches can therefore scale out across instances while each match keeps its order. If a partition moves to another instance mid-match, the new owner starts a fresh pipeline and cumulative stats restart from that point. The production fix is to checkpoint engine state on each snapshot (Table storage or Cosmos DB) and restore it on first sight. Basic tier allows one consumer group, which is enough here.

## How the viewer connects

`viewer/src/live.ts` turns on when the URL hash contains `live`:

| URL | Connects to |
| --- | --- |
| `#live` | `ws://localhost:8787/ws` |
| `#live=ws://host:8787/ws` | that WebSocket |
| `#live=https://<app>.azurewebsites.net` | `GET <app>/api/negotiate?match_id=...`, then the Web PubSub client URL it returns (already joined to the match group) |

The client reconnects with backoff and negotiates again on each reconnect. It exposes `onSnapshot`, `onInsight`, `onRating`, `onEvent`, `onConnection`, a `connected` flag, and `apiBase` (where to `POST /api/claims`). Adding it to `viewer/src/main.ts` takes three lines (Agent B owns that file):

```ts
import { startLive } from './live';
const live = startLive(meta.match_id);   // null unless the URL has #live
live?.onSnapshot(s => { /* update score, momentum strip */ }).onInsight(i => { /* add point card */ }).onEvent(e => { /* goal or card toast */ });
```

## Files

```
live/pipeline.py        Pipeline: StatsEngine + detectors or stubs -> contract messages
live/claims.py          /api/claims glue: agents.extras.api or the precomputed fallback
live/local.py           python -m live.local: replay + aiohttp WebSocket and HTTP on :8787
live/functions/         Azure Functions app (function_app.py, host.json, stage.py)
live/infra/live.bicep   Event Hubs, Web PubSub, Flex Consumption Function App, role assignments
live/deploy.sh          deploy, publish, replay
live/tests/             pytest
live/CONTRACT.md        the shared contract, plus how live messages are filled
viewer/src/live.ts      browser client
```

## Known gaps

- `az bicep build` was not run while this was written (no Azure CLI in the build environment), so run `az bicep build -f live/infra/live.bicep` before the first deploy.
- The Azure path has not been deployed end to end; the trigger, negotiate and publish code is tested against a fake Web PubSub client.
- Without `agents/` or the precomputed `insights.json` and `ratings.json`, only snapshots and events are sent.
- The local server sends catch-up history to late joiners; the Azure path does not (a late joiner waits for the next snapshot, at most 30 s of match time).
