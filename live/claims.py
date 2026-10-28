"""POST /api/claims glue. Uses Agent D's agents.extras.api when it imports, otherwise answers
from the precomputed viewer/public/data/claims.sample.json, otherwise returns out_of_scope.

The handler is looked up by name (check_claim, handle_claim, claims, handle, check). It may take
the request body as one dict or as keyword arguments, and may be sync or async."""
from __future__ import annotations

import asyncio
import inspect
import json
import os

from .pipeline import DEFAULT_DATA_DIR

_CANDIDATES = ("handle_claim", "check_claim", "handle", "check")
_FIELDS = ("match_id", "t", "claim", "lens", "lang")


def _agent_handler():
    try:
        from agents.extras import api  # type: ignore
    except Exception:
        return None
    for name in _CANDIDATES:
        fn = getattr(api, name, None)
        if callable(fn):
            return fn
    return None


def _call(fn, body: dict):
    try:
        if len(inspect.signature(fn).parameters) == 1:
            return fn(body)
    except (TypeError, ValueError):
        pass
    return fn(**{k: body.get(k) for k in _FIELDS})


def fallback(body: dict, data_dir: str = DEFAULT_DATA_DIR) -> dict:
    """Exact claim text match in claims.sample.json (closest t wins), else out_of_scope."""
    try:
        with open(os.path.join(data_dir, "claims.sample.json")) as f:
            doc = json.load(f)
    except (OSError, ValueError):
        doc = []
    items = doc if isinstance(doc, list) else doc.get("claims") or doc.get("items") or []
    text = (body.get("claim") or "").strip().lower()
    t = float(body.get("t") or 0.0)
    matches = []
    for it in items:
        resp = it.get("response", it)
        claim = (it.get("claim") or resp.get("claim") or "").strip().lower()
        if claim == text:
            matches.append((abs(float(it.get("t", t)) - t), resp))
    if matches:
        return min(matches, key=lambda m: m[0])[1]
    return {
        "claim": body.get("claim", ""), "verdict": "out_of_scope",
        "summary": {"casual": "The claim checker is not available for this claim yet.",
                    "tactical": "No claim checker backend and no precomputed verdict for this claim."},
        "tests": [], "evidence_for": [], "evidence_against": [],
        "check": {"passed": True, "numbers_checked": 0, "retries": 0},
        "receipt": {"model": None, "latency_ms": 0, "mode": "fallback"},
    }


async def check(body: dict, data_dir: str = DEFAULT_DATA_DIR) -> dict:
    fn = _agent_handler()
    if fn is not None:
        try:
            if inspect.iscoroutinefunction(fn):
                return await _call(fn, body)
            return await asyncio.to_thread(_call, fn, body)
        except Exception as exc:
            print(f"live: agents.extras.api failed, using fallback: {exc}")
    return fallback(body, data_dir)
