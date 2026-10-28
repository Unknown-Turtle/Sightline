# Sightline agent prompts

Run each file in its own Claude Code session on its own branch (`agent-a` to `agent-f`). Hard stop 05:15 UK time.

| Agent | Owns | Model |
| --- | --- | --- |
| A, agent layer | `agents/` | Fable 5 |
| B, viewer insights and app shell (Premier League app look) | `viewer/` existing files | Opus 5.5 |
| C, Azure, deployment and docs | `infra/`, `docs/`, root `README.md` | Opus 5.5 |
| D, claim checker, ratings, patterns, translations | `agents/extras/` | Fable 5 |
| E, live pipeline | `live/`, `viewer/src/live.ts` | Opus 5.5 |
| F, personalisation and new panels | new files in `viewer/src/` | Opus 5.5 |

Start B before F if you can: F mounts into the app shell B builds in its first 30 minutes.
