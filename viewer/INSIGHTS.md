# `data/insights.json`: the shared insight contract

Agent A produces `viewer/public/data/insights.json`, the viewer renders it, Agent C documents it. If the file is missing or invalid the viewer runs exactly as before on its templated points, using `data/insights.sample.json` (a hand-written fixture) only when `insights.json` is absent.

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

- `t` is match `elapsed` seconds, the same clock as events and tracking. An item is visible once playback passes `t` and stays until a newer item with the same `point_id` replaces it.
- `point_id` matches the viewer's point ids (`anchor-<player>`, `duel-<player>`, `finishing-<team>`) for `anchor`, `duel` and `finishing` kinds, so the insight text replaces the template on that rail card. `momentum`, `score_state` and `recap` items appear as their own rail items.
- `recap` items are written at half time and full time and are shown as a dismissable panel over the stage.
- `evidence_for` and `evidence_against` are event ids from `events.jsonl`; the viewer builds the For and Against reels from them.
- When `check.passed` is false the viewer shows the template text and says the AI version was rejected, with the issues in the receipt.

## How the viewer renders it

| Lens | Rail text | Extras |
| --- | --- | --- |
| Casual | `text.casual` | receipt line |
| Tactical | `text.tactical` | receipt line |
| Commentator | `text.commentator` | each item's trivia with its source, and a "Coming up" list from `score_state` items |

Receipt line: "Checked: N numbers, R retries, model, latency". The disclosure lists the agents involved, tokens in and out, and the mode (live or fallback) from the file header.
