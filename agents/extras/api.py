"""FastAPI app exposing the claim checker: POST /api/claims {match_id, t, claim, lens, lang}.

Run: uvicorn agents.extras.api:app --port 8010   (set SIGHTLINE_MATCH_DIR to point at another match folder)
"""
from __future__ import annotations

import os

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from .claims import CLAIM_TYPES, check_claim
from .common import DEFAULT_MATCH_DIR, Match
from .llm import LLM

app = FastAPI(title="Sightline claim checker", version="0.1.0")
_matches: dict[str, Match] = {}
_llm = LLM()


def get_match(match_id: str | None) -> Match:
    path = os.environ.get("SIGHTLINE_MATCH_DIR", str(DEFAULT_MATCH_DIR))
    if path not in _matches:
        _matches[path] = Match(path, frames=True)
    m = _matches[path]
    if match_id and match_id != m.match_id:
        raise HTTPException(404, f"unknown match_id {match_id}; this server has {m.match_id}")
    return m


class ClaimRequest(BaseModel):
    match_id: str | None = None
    t: float = Field(..., ge=0, description="match elapsed seconds")
    claim: str = Field(..., min_length=2, max_length=400)
    lens: str = "tactical"
    lang: str = "en"


@app.get("/api/health")
def health():
    return {"ok": True, "mode": _llm.mode, "model": _llm.model, "claim_types": CLAIM_TYPES}


@app.post("/api/claims")
def claims(req: ClaimRequest):
    match = get_match(req.match_id)
    return check_claim(match, req.claim, req.t, req.lens, req.lang, _llm)
