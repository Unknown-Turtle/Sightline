# Sightline agent layer

The AI layer of Sightline: it reads a generated match and the league history archive and writes
`insights.json`, the file the viewer renders as live, explainable, per-lens match intelligence.
It is multi-agent, grounded and checkable, and it always produces output, even with no AI credentials.

```bash
# from the repo root
pip install -r agents/requirements.txt
python -m agents build --match matchgen/sample/demo_seed587 --history matchgen/sample/history --out viewer/public/data/insights.json
python -m pytest agents/tests -q
```

The output format is the shared contract in `CONTRACT.md`.

## Rule one: numbers come from code

The model never produces a number. Deterministic Python computes every number, selects every
piece of evidence and looks up every trivia fact. Models only phrase, and a checker verifies the
phrasing before anything is written. Concretely:

- The **analyst** builds a fact pack per point: every number it is allowed to mention, every evidence
  event id with a short description, and the player and club names it may use.
- The **narrator** is told, in its system prompt, that it must not write any number or name that is not
  in the fact pack or the trivia. That is a request, not a guarantee, so:
- The **checker** extracts every numeric token (integers, decimals, percentages, scorelines, clocks and
  the number words one to twelve) and every capitalised name from the narrator's text and confirms each
  one against the fact pack and trivia. A failure sends the issues back to the narrator for at most two
  retries, then the template text is used. The template is checked too, so a template bug cannot leak a
  number either. During development the checker caught exactly that: a template said "the last five
  minutes" while the window length was not in the fact pack, so it was rejected until the analyst put
  `window_minutes` there.

Every item records `check` (passed, numbers checked, retries, issues) and `receipt` (model, latency,
tokens, the agents that touched it, live or fallback, and whether the text came from the model or the
template), so the viewer can show its working.

## Architecture

```
                 match.json + events.jsonl                 history/*.csv
                          |                                     |
          checkpoints: every 5 min, each goal, red card, half time, full time
                          |                                     |
                          v                                     v
     +--------------------------------+          +----------------------------+
     |  1. ANALYST  (deterministic)   |          |  2. TRIVIA (deterministic) |
     |  StatsEngine snapshot          |  pack    |  head to head, home record |
     |  anchor, duel, finishing,      |--------->|  scorer vs opponent,       |
     |  momentum, score_state         |          |  milestones, careers,      |
     |  -> fact pack per point        |          |  club records, comebacks   |
     +--------------------------------+          |  -> facts with source+row  |
                          |                      +----------------------------+
                          |  fact pack + trivia                 |
                          v                                     |
     +--------------------------------+ <----------------------+
     |  3. NARRATOR  (LLM, or template)|
     |  casual / tactical / commentator|
     |  system prompt forbids any      |
     |  number not in the fact pack    |
     +--------------------------------+
                          |  draft text
                          v
     +--------------------------------+   issues (max 2 retries)
     |  4. CHECKER  (deterministic)   |------------------------> back to 3
     |  every number, clock and name  |
     |  must be in pack or trivia     |   still failing -> template text
     +--------------------------------+
                          |  text + check + receipt
                          v
                    insights.json item

     5. RECAP (half time and full time): score state + xG timeline + strongest points
        -> the same narrator and checker, kind = "recap"
```

Files:

| File | Role |
| --- | --- |
| `analyst.py` | The five detectors and fact packs. `anchor`, `duel` and `finishing` are ports of `viewer/src/points.ts`; `momentum` and `score_state` are new |
| `trivia.py` | History lookups. Every fact has `source` (CSV table) and `row` (a key into it). A lookup that finds nothing returns nothing |
| `narrator.py` | System prompt, the live call loop with retries, and the fallback templates |
| `checker.py` | Number and name extraction and verification |
| `recap.py` | Half time and full time recap packs and templates |
| `pipeline.py` | Checkpoints, orchestration, OpenTelemetry spans, item assembly |
| `llm.py` | Foundry client through the official `openai` Azure client, config and limits |
| `data.py` | Match folder and history loading |
| `tests/` | Checker tests (made-up numbers and names must be rejected) and an end-to-end fallback build |

## Detectors

| Kind | Fires when | Evidence for / against |
| --- | --- | --- |
| `anchor` | A player has 6 or more defensive actions (tackles won, interceptions, clearances, blocks, loose balls won) and 3 more than any teammate | those actions / tackles lost, beaten by a dribble, fouls |
| `duel` | A player has 4 or more take-ons with 60% or more won (top two players) | successful take-ons / failed ones |
| `finishing` | A team's goals differ from its xG by 0.8 or more over 3 or more shots | goals or missed chances with xG 0.15 or more |
| `momentum` | A team's `last_5_min.momentum` from the stats snapshot (sampled every minute) is above 60 for two consecutive samples | completed passes into the final third and shots in the last 5 minutes |
| `score_state` | Always; re-emitted when the score changes | the leader's goals / the other goals, and a comeback flag when a team that was behind is level or ahead |

A point is re-emitted at a later checkpoint only when its numbers change (momentum only after ten
minutes or when the shots in the window change), so the file stays readable. An item is visible in the
app once playback passes `t` and stays until a newer item with the same `point_id` replaces it.

## Live and fallback modes

Configuration is read from environment variables:

| Variable | Meaning |
| --- | --- |
| `FOUNDRY_ENDPOINT` | The Azure OpenAI or Foundry project endpoint, for example `https://<resource>.openai.azure.com/` |
| `FOUNDRY_DEPLOYMENT` | The chat model deployment name |
| `FOUNDRY_API_KEY` | Optional. Without it `DefaultAzureCredential` is used: managed identity in Azure, `az login` locally |

```bash
export FOUNDRY_ENDPOINT=https://my-resource.openai.azure.com/
export FOUNDRY_DEPLOYMENT=gpt-4o
export FOUNDRY_API_KEY=...        # or az login
python -m agents build --match matchgen/sample/demo_seed587 --history matchgen/sample/history --out viewer/public/data/insights.json
```

**Live:** the narrator calls the deployment, at most 3 calls per point (one draft and two retries),
20 second timeout per call, temperature 0.3, 400 output tokens, JSON replies. `mode` is `live` and
`model` is the deployment name. An item whose text still fails after the retries, or whose call fails
or times out, gets the template text and says so in its receipt (`source: "template"`), so a live
build is never incomplete.

**Fallback:** with no endpoint or deployment set, or with `--fallback`, the same pipeline runs with
template phrasing. Every number, evidence id, trivia fact, check and receipt is identical; only the
wording is fixed. `mode` is `fallback` and `model` is `null`. The committed
`viewer/public/data/insights.json` was generated this way.

**Framework:** orchestration is plain Python over the official `openai` package's `AzureOpenAI`
client, not the Microsoft Agent Framework. The hackathon environment had no Foundry credentials, so
the 20 minute trial the brief allows could not have been verified against a real endpoint; the plain
client keeps the dependency surface small and is straightforward to swap. OpenTelemetry spans wrap
each checkpoint and each agent step (`sightline.agents` tracer); they are no-ops until an OTel SDK and
exporter are configured.

## Checkpoints

Every 5 minutes of match time, plus immediately after each goal, red card and half time, plus full
time. At each checkpoint the analyst runs over the events so far and a fresh `StatsEngine` snapshot
(`matchgen.stats`), then the trivia, narrator and checker run per emitted point. Half time and full
time add a recap item (three to five sentences per lens).

## Testing

```bash
python -m pytest agents/tests -q
```

`tests/test_checker.py` proves the checker rejects a made-up number, decimal, percentage, number word,
clock, player name (mid-sentence and sentence-initial) and club, and accepts text that only uses the
fact pack and trivia. `tests/test_build.py` runs the whole pipeline in fallback mode on the sample match
and asserts the contract shape, that every item passes the checker, time order, both recaps, the demo
story (the Tremblay anchor and the 3-2 comeback) and that casual text has no jargon.

## Known limits

- The name check treats a single capitalised word at the start of a sentence as ordinary English unless
  a second capitalised word follows it, so a one-word invented surname at the very start of a sentence
  can pass. The system prompt also forbids it, and the trivia and fact pack supply every name a narrator
  needs, so the live path has no reason to produce one.
- Trivia is template phrased from archive rows in both modes; the brief allows an LLM phrase and the
  narrator is free to reword a fact, but the fact itself is never generated.
