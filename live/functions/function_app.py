"""Sightline live pipeline on Azure Functions (Python v2 programming model).

  match_events   Event Hubs trigger on `match-events`: feeds each match's Pipeline and publishes
                 every contract message to Web PubSub (hub `match`, group = match_id)
  negotiate      GET /api/negotiate?match_id=...: a Web PubSub client access URL that joins the group
  claims         POST /api/claims: claim check (agents.extras.api, else the precomputed fallback)

Identity: Event Hubs via EventHubConnection__fullyQualifiedNamespace and Web PubSub via
DefaultAzureCredential, both the Function App's system-assigned managed identity. No keys.

State: one Pipeline per match_id, in memory. matchgen partitions by match_id, so a match lives on
one partition, and Event Hubs gives each partition to one instance at a time, in order. That keeps
state correct while the app scales out across matches. If a partition moves to another instance
mid-match (scale event or restart), the new owner starts a fresh Pipeline from that point: stats
restart from zero until the next replay. For production, checkpoint the engine state to a store
(Table or Cosmos DB) on each snapshot and restore it on first sight of a match.

The deploy script stages this folder with `live/`, `matchgen/` and the data files next to it
(see live/deploy.sh), so the same pipeline code runs here and in `python -m live.local`.
"""
from __future__ import annotations

import json
import logging
import os

import azure.functions as func

HERE = os.path.dirname(os.path.abspath(__file__))
os.environ.setdefault("SIGHTLINE_DATA_DIR", os.path.join(HERE, "data"))

from live import claims  # noqa: E402
from live.pipeline import DEFAULT_DATA_DIR, Pipeline  # noqa: E402

HUB = os.environ.get("WEBPUBSUB_HUB", "match")
EVENT_HUB = os.environ.get("EVENTHUB_NAME", "match-events")
DEFAULT_MATCH = os.environ.get("DEFAULT_MATCH_ID", "m_seed587")

app = func.FunctionApp(http_auth_level=func.AuthLevel.ANONYMOUS)

_pipelines: dict[str, Pipeline] = {}
_client = None


def wps():
    global _client
    if _client is None:
        from azure.identity import DefaultAzureCredential
        from azure.messaging.webpubsubservice import WebPubSubServiceClient
        _client = WebPubSubServiceClient(endpoint=os.environ["WEBPUBSUB_ENDPOINT"], hub=HUB,
                                         credential=DefaultAzureCredential())
    return _client


def load_meta(match_id: str) -> dict:
    """match.json for a match, bundled at data/matches/<match_id>/match.json by deploy.sh."""
    path = os.path.join(DEFAULT_DATA_DIR, "matches", match_id, "match.json")
    with open(path) as f:
        return json.load(f)


def pipeline_for(match_id: str, restart: bool = False) -> Pipeline:
    if restart or match_id not in _pipelines:
        _pipelines[match_id] = Pipeline(load_meta(match_id))
    return _pipelines[match_id]


def publish(messages: list[dict]) -> None:
    client = wps()
    for m in messages:
        client.send_to_group(m["match_id"], json.dumps(m, separators=(",", ":")),
                             content_type="application/json")


@app.function_name("match_events")
@app.event_hub_message_trigger(arg_name="batch", event_hub_name=EVENT_HUB,
                               connection="EventHubConnection", cardinality="many",
                               consumer_group="$Default")
def match_events(batch: list[func.EventHubEvent]) -> None:
    out: list[dict] = []
    for ev in batch:
        try:
            m = json.loads(ev.get_body().decode("utf-8"))
            kind, data = m["kind"], m.get("data") or {}
            match_id = data.get("match_id")
            if not match_id:
                continue
            p = pipeline_for(match_id, restart=(kind == "match_start"))
            out.extend(p.feed(kind, data))
            if kind == "match_end":
                _pipelines.pop(match_id, None)
        except FileNotFoundError as exc:
            logging.warning("no match.json bundled for this match: %s", exc)
        except Exception:
            logging.exception("live: bad message skipped")
    if out:
        publish(out)


@app.route(route="negotiate", methods=["GET"])
def negotiate(req: func.HttpRequest) -> func.HttpResponse:
    match_id = req.params.get("match_id") or DEFAULT_MATCH
    token = wps().get_client_access_token(groups=[match_id], minutes_to_expire=60)
    return func.HttpResponse(json.dumps({"url": token["url"], "match_id": match_id}),
                             mimetype="application/json")


@app.route(route="claims", methods=["POST"])
async def claims_api(req: func.HttpRequest) -> func.HttpResponse:
    try:
        body = req.get_json()
    except ValueError:
        return func.HttpResponse(json.dumps({"error": "expected a JSON body"}), status_code=400,
                                 mimetype="application/json")
    result = await claims.check(body, DEFAULT_DATA_DIR)
    return func.HttpResponse(json.dumps(result), mimetype="application/json")
