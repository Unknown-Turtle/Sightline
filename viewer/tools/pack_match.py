"""Pack a matchgen match folder into compact files the viewer loads fast.

Usage:
    python tools/pack_match.py <match_dir> <out_dir> [--js]

Writes:
    meta.json      teams, players, context, periods, momentum strip
    events.json    every event, trimmed to the fields the viewer uses
    tracking.bin   int16 frames: [ball x, y, z, then x, y per squad player]
    tracking.js    (with --js) the same bytes as base64, for hosts that cannot serve binary

Coordinates are stored as round(value * SCALE). Players not on the pitch in a
frame are stored as ABSENT. Standard library only.
"""
from __future__ import annotations

import array
import base64
import json
import os
import sys

SCALE = 300
ABSENT = -32768
DEFAULT_COLOURS = {"ARD": "#C8102E", "HVL": "#1D4E89"}
KEEP_EXTRA = {
    "xg", "distance_m", "shot_speed_kmh", "assist_event_id", "assist_type", "defenders_in_lane",
    "one_on_one", "first_time", "counter", "xg_factors", "receiver_id", "length_m", "height",
    "progressive", "difficulty", "direction", "key_pass", "assist", "opponent_id", "fouled_player_id",
    "in_box", "player_in", "player_out", "restart", "target_player_id", "placement",
}


def q(v: float) -> int:
    return max(-32767, min(32767, round(v * SCALE)))


def main() -> None:
    if len(sys.argv) < 3:
        raise SystemExit(__doc__)
    src, out = sys.argv[1], sys.argv[2]
    want_js = "--js" in sys.argv
    os.makedirs(out, exist_ok=True)

    with open(os.path.join(src, "match.json")) as f:
        meta = json.load(f)
    with open(os.path.join(src, "events.jsonl")) as f:
        events = [json.loads(line) for line in f if line.strip()]

    players = meta["players"]
    order = [p["id"] for p in players]
    slot = {pid: i for i, pid in enumerate(order)}

    # tracking
    buf = array.array("h")
    n = 0
    hz = meta.get("tracking_hz", 1.0)
    t0 = None
    with open(os.path.join(src, "tracking.jsonl")) as f:
        for line in f:
            if not line.strip():
                continue
            fr = json.loads(line)
            if t0 is None:
                t0 = fr["elapsed"]
            row = [ABSENT] * (3 + 2 * len(order))
            bx, by, bz = fr["ball"]
            row[0], row[1], row[2] = q(bx), q(by), q(bz)
            for pid, x, y, _kmh in fr["players"]:
                i = slot[pid]
                row[3 + 2 * i] = q(x)
                row[4 + 2 * i] = q(y)
            buf.extend(row)
            n += 1
    if sys.byteorder != "little":
        buf.byteswap()
    raw = buf.tobytes()
    with open(os.path.join(out, "tracking.bin"), "wb") as f:
        f.write(raw)
    if want_js:
        with open(os.path.join(out, "tracking.js"), "w") as f:
            f.write("window.__SIGHTLINE_TRACKING_B64=\"")
            f.write(base64.b64encode(raw).decode("ascii"))
            f.write("\";\n")

    # momentum strip from snapshots (optional)
    momentum = []
    snap_path = os.path.join(src, "snapshots.jsonl")
    if os.path.exists(snap_path):
        with open(snap_path) as f:
            for line in f:
                s = json.loads(line)
                teams = s["teams"]
                momentum.append({
                    "t": s["elapsed"],
                    "m": {tid: teams[tid]["last_5_min"]["momentum"] for tid in teams},
                    "xg": {tid: round(teams[tid]["xg"], 2) for tid in teams},
                })

    # events, trimmed
    out_events = []
    for e in events:
        out_events.append({
            "id": e["event_id"], "t": e["elapsed"], "clock": e["clock"], "min": e["minute"],
            "p": e["period"], "type": e["type"], "out": e["outcome"], "team": e["team_id"],
            "pl": e["player_id"], "s": [e["start"]["x"], e["start"]["y"]] if e.get("start") else None,
            "e": [e["end"]["x"], e["end"]["y"]] if e.get("end") else None, "dir": e["attack_dir"],
            "poss": e["possession_id"], "seq": e["sequence_index"], "pat": e["play_pattern"],
            "up": e["under_pressure"], "bp": e.get("body_part"), "rel": e["related_event_id"], "q": e["qualifiers"],
            "score": e.get("score"),
            "x": {k: v for k, v in (e.get("extra") or {}).items() if k in KEEP_EXTRA},
        })
    with open(os.path.join(out, "events.json"), "w") as f:
        json.dump(out_events, f, separators=(",", ":"))

    periods = [{"p": 1, "start": 0.0}]
    for e in events:
        if e["type"] == "period_end" and e["period"] == 1:
            periods[0]["end"] = e["elapsed"]
        if e["type"] == "period_end" and e["period"] == 2:
            periods.append({"p": 2, "end": e["elapsed"]})
    second_start = next((e["elapsed"] for e in events if e["period"] == 2), None)
    if len(periods) > 1 and second_start is not None:
        periods[1]["start"] = second_start

    teams = []
    for lu in meta["lineups"]:
        teams.append({
            "id": lu["team_id"], "name": lu["name"], "formation": lu["formation"],
            "colour": DEFAULT_COLOURS.get(lu["team_id"], "#888888"),
            "xi": [s["player_id"] for s in lu["starting_xi"]], "bench": lu["bench"],
        })
    out_meta = {
        "match_id": meta["match_id"], "competition": meta["competition"], "venue": meta["venue"],
        "home": meta["home_team_id"], "away": meta["away_team_id"], "final_score": meta["final_score"],
        "context": {k: meta.get(k) for k in ("referee", "weather", "attendance", "kickoff_local", "matchday", "stakes")},
        "attack_direction": meta["attack_direction"], "teams": teams,
        "players": [{"id": p["id"], "name": p["name"], "number": p["number"], "pos": p["position"],
                     "team": p["id"].split("_")[0]} for p in players],
        "tracking": {"order": order, "frames": n, "hz": hz, "t0": t0, "scale": SCALE, "absent": ABSENT,
                     "stride": 3 + 2 * len(order)},
        "periods": periods, "momentum": momentum,
    }
    with open(os.path.join(out, "meta.json"), "w") as f:
        json.dump(out_meta, f, separators=(",", ":"))
    print(json.dumps({"frames": n, "hz": hz, "bytes": len(raw), "events": len(out_events),
                      "momentum_points": len(momentum)}))


if __name__ == "__main__":
    main()
