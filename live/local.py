"""Local live mode, no Azure: replay a match folder, run the pipeline, serve it on a WebSocket.

    python -m live.local --match matchgen/sample/demo_seed587 --speed 30

Endpoints on http://localhost:8787:
  GET  /  or /ws        WebSocket: contract live messages as JSON text frames
  GET  /api/negotiate   {"url": "ws://localhost:8787/ws"}, the same shape the Azure function returns
  POST /api/claims      claim check (agents.extras.api if present, else the precomputed fallback)
  GET  /api/health      {"ok": true, "t": <match seconds>, "clients": n}

A client that connects mid-match gets the latest snapshot and every insight, rating and event so far.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import time

from aiohttp import WSMsgType, web

from . import claims
from .pipeline import DEFAULT_DATA_DIR, Pipeline, load_match

CORS = {"Access-Control-Allow-Origin": "*", "Access-Control-Allow-Headers": "Content-Type",
        "Access-Control-Allow-Methods": "GET, POST, OPTIONS"}


class LiveServer:
    def __init__(self, match_dir: str, speed: float = 30.0, start_minute: float = 0.0,
                 snapshot_every: float = 30.0, data_dir: str = DEFAULT_DATA_DIR, loop: bool = False,
                 host: str = "localhost", port: int = 8787):
        self.meta, self.events, self.frames = load_match(match_dir)
        self.speed, self.start_minute, self.every = speed, start_minute, snapshot_every
        self.data_dir, self.loop, self.host, self.port = data_dir, loop, host, port
        self.clients: set[web.WebSocketResponse] = set()
        self.history: list[str] = []
        self.last_snapshot: str | None = None
        self.pipeline: Pipeline | None = None
        self.done = asyncio.Event()

    async def broadcast(self, messages: list[dict]) -> None:
        for m in messages:
            text = json.dumps(m, separators=(",", ":"))
            if m["kind"] == "snapshot":
                self.last_snapshot = text
            else:
                self.history.append(text)
            for ws in list(self.clients):
                try:
                    await ws.send_str(text)
                except Exception:
                    self.clients.discard(ws)

    async def run_replay(self) -> None:
        from matchgen.stream import merged
        while True:
            self.history, self.last_snapshot = [], None
            self.pipeline = p = Pipeline(self.meta, snapshot_every=self.every, data_dir=self.data_dir)
            start = self.start_minute * 60.0
            await self.broadcast(p.start())
            wall0 = time.monotonic()
            for t, kind, data in merged(self.events, self.frames):
                out = p.feed(kind, data)
                if t < start:
                    continue  # fast-forward state without pacing
                delay = wall0 + (t - start) / self.speed - time.monotonic()
                if delay > 0:
                    await asyncio.sleep(delay)
                if out:
                    await self.broadcast(out)
            await self.broadcast(p.feed("match_end", {"final_score": self.meta["final_score"]}))
            self.done.set()
            if not self.loop:
                return
            await asyncio.sleep(5)
            self.done.clear()

    async def ws_handler(self, request: web.Request) -> web.StreamResponse:
        ws = web.WebSocketResponse(heartbeat=20)
        await ws.prepare(request)
        if self.last_snapshot:
            await ws.send_str(self.last_snapshot)
        for text in list(self.history):
            await ws.send_str(text)
        self.clients.add(ws)
        try:
            async for m in ws:  # clients do not need to send anything
                if m.type == WSMsgType.ERROR:
                    break
        finally:
            self.clients.discard(ws)
        return ws

    async def negotiate(self, request: web.Request) -> web.Response:
        return web.json_response({"url": f"ws://{request.host}/ws", "match_id": self.meta["match_id"]},
                                 headers=CORS)

    async def claims(self, request: web.Request) -> web.Response:
        if request.method == "OPTIONS":
            return web.Response(headers=CORS)
        try:
            body = await request.json()
        except Exception:
            return web.json_response({"error": "expected a JSON body"}, status=400, headers=CORS)
        return web.json_response(await claims.check(body, self.data_dir), headers=CORS)

    async def health(self, request: web.Request) -> web.Response:
        t = self.pipeline.t if self.pipeline else 0.0
        return web.json_response({"ok": True, "t": t, "clients": len(self.clients)}, headers=CORS)

    def app(self) -> web.Application:
        app = web.Application()
        app.router.add_get("/", self.ws_handler)
        app.router.add_get("/ws", self.ws_handler)
        app.router.add_get("/api/negotiate", self.negotiate)
        app.router.add_route("*", "/api/claims", self.claims)
        app.router.add_get("/api/health", self.health)

        async def on_start(_app):
            _app["replay"] = asyncio.create_task(self.run_replay())

        async def on_stop(_app):
            _app["replay"].cancel()
            for ws in list(self.clients):
                await ws.close()

        app.on_startup.append(on_start)
        app.on_shutdown.append(on_stop)
        return app


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="python -m live.local", description=__doc__.splitlines()[0])
    ap.add_argument("--match", default="matchgen/sample/demo_seed587", help="matchgen match folder")
    ap.add_argument("--speed", type=float, default=30.0, help="30 = 90 minutes in about 3")
    ap.add_argument("--start-minute", type=float, default=0.0)
    ap.add_argument("--snapshot-every", type=float, default=30.0, help="match seconds")
    ap.add_argument("--data", default=DEFAULT_DATA_DIR, help="folder with insights.json, ratings.json, claims.sample.json")
    ap.add_argument("--host", default="localhost")
    ap.add_argument("--port", type=int, default=8787)
    ap.add_argument("--loop", action="store_true", help="restart the match after full time")
    a = ap.parse_args(argv)
    server = LiveServer(a.match, a.speed, a.start_minute, a.snapshot_every, a.data, a.loop, a.host, a.port)
    print(f"Sightline live: ws://{a.host}:{a.port}/ws  (match {server.meta['match_id']}, speed {a.speed})")
    web.run_app(server.app(), host=a.host, port=a.port, print=None)


if __name__ == "__main__":
    main()
