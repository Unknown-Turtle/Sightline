"""Replay a generated match in real time (or faster) as a live feed.

Events and tracking frames are merged in match-time order and released with
real waiting between them, scaled by `speed` (speed 30 = 90 minutes in ~3).

Sinks:
  stdout    one JSON message per line, for piping or local testing
  eventhub  Azure Event Hubs (pip install azure-eventhub); reads
            EVENTHUB_CONNECTION_STRING and EVENTHUB_NAME from the environment

Every message is wrapped as {"kind": "event" | "frame" | "match_start" | "match_end", "data": {...}}.
"""
from __future__ import annotations

import heapq
import json
import os
import sys
import time
from typing import Iterator


def merged(events: list[dict], frames: list[dict], include_frames: bool = True) -> Iterator[tuple[float, str, dict]]:
    ev_iter = ((e["elapsed"], 1, "event", e) for e in events)
    if not include_frames:
        for t, _, k, d in ev_iter:
            yield t, k, d
        return
    fr_iter = ((f["elapsed"], 0, "frame", f) for f in frames)
    for t, _, k, d in heapq.merge(fr_iter, ev_iter, key=lambda x: (x[0], x[1])):
        yield t, k, d


class StdoutSink:
    def send(self, batch: list[dict]) -> None:
        try:
            for m in batch:
                sys.stdout.write(json.dumps(m, separators=(",", ":")) + "\n")
            sys.stdout.flush()
        except BrokenPipeError:  # reader went away (e.g. piped into head)
            os._exit(0)

    def close(self) -> None:
        pass


class EventHubSink:
    def __init__(self, partition_key: str):
        try:
            from azure.eventhub import EventData, EventHubProducerClient
        except ImportError as exc:  # pragma: no cover
            raise SystemExit("Install the Event Hubs client first: pip install azure-eventhub") from exc
        conn = os.environ.get("EVENTHUB_CONNECTION_STRING")
        name = os.environ.get("EVENTHUB_NAME")
        if not conn or not name:
            raise SystemExit("Set EVENTHUB_CONNECTION_STRING and EVENTHUB_NAME")
        self._EventData = EventData
        self.client = EventHubProducerClient.from_connection_string(conn, eventhub_name=name)
        self.partition_key = partition_key

    def send(self, batch: list[dict]) -> None:
        eb = self.client.create_batch(partition_key=self.partition_key)
        for m in batch:
            data = self._EventData(json.dumps(m, separators=(",", ":")))
            data.properties = {"kind": m["kind"]}
            try:
                eb.add(data)
            except ValueError:  # batch full
                self.client.send_batch(eb)
                eb = self.client.create_batch(partition_key=self.partition_key)
                eb.add(data)
        if len(eb):
            self.client.send_batch(eb)

    def close(self) -> None:
        self.client.close()


def replay(meta: dict, events: list[dict], frames: list[dict], speed: float = 30.0,
           sink=None, include_frames: bool = True, start_minute: float = 0.0,
           tick: float = 0.25) -> None:
    """Send messages at match pace / speed. Messages due in the same tick are batched."""
    sink = sink or StdoutSink()
    start_elapsed = start_minute * 60.0
    sink.send([{"kind": "match_start", "data": {k: meta[k] for k in (
        "match_id", "home_team_id", "away_team_id", "competition", "venue", "attack_direction", "tracking_hz")}}])
    wall0 = time.monotonic()
    batch: list[dict] = []
    batch_due = None
    for t, kind, data in merged(events, frames, include_frames):
        if t < start_elapsed:
            continue
        due = (t - start_elapsed) / speed
        if batch_due is not None and due - batch_due > tick:
            _wait_until(wall0 + batch_due)
            sink.send(batch)
            batch = []
            batch_due = None
        if batch_due is None:
            batch_due = due
        batch.append({"kind": kind, "data": data})
    if batch:
        _wait_until(wall0 + (batch_due or 0))
        sink.send(batch)
    sink.send([{"kind": "match_end", "data": {"match_id": meta["match_id"], "final_score": meta["final_score"]}}])
    sink.close()


def _wait_until(wall: float) -> None:
    delay = wall - time.monotonic()
    if delay > 0:
        time.sleep(delay)
