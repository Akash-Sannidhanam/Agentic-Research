# Agentic Research

A multi-step research agent that searches the web, reads sources, and drafts a cited brief — with human approval at the decision points.

![demo](docs/demo.gif)

## What it does

- Searches the web with Tavily, then pauses for you to pick which sources are worth reading.
- Fetches and extracts text from the selected URLs.
- Asks Claude to summarize each source, then pauses again so you can review the summaries and steer the draft with free-form feedback.
- Generates a structured research brief with inline citations.
- Streams every step over a WebSocket — phase transitions, tool calls, retries, token usage, and per-step cost.

## Architecture

```mermaid
flowchart LR
    start([Topic]) --> search[Phase 1: search<br/>Tavily]
    search --> cp1{{Checkpoint 1<br/>source_review}}
    cp1 -- approve --> read[Phase 2: read<br/>fetch + extract]
    cp1 -- reject --> failed([failed])
    read --> synth[Phase 3: synthesize<br/>Claude]
    synth --> cp2{{Checkpoint 2<br/>synthesis_review}}
    cp2 -- approve --> draft[Phase 4: draft<br/>Claude]
    cp2 -- reject --> failed
    draft --> done([complete])
```

```mermaid
flowchart LR
    ui[Next.js UI<br/>localhost:3000] <-- WebSocket --> api[FastAPI<br/>localhost:8000]
    api --> tavily[Tavily Search API]
    api --> fetch[httpx + BeautifulSoup]
    api --> claude[Anthropic API<br/>Claude Sonnet 4]
```

## Stack

| Layer      | Tech                                                            |
| ---------- | --------------------------------------------------------------- |
| Backend    | Python 3.13, FastAPI, uvicorn, httpx, BeautifulSoup             |
| Frontend   | Next.js 16, React 19, TypeScript, Tailwind CSS 4, react-markdown |
| Transport  | WebSocket (`/ws/research`)                                      |
| Model      | Claude Sonnet 4 (`claude-sonnet-4-20250514`)                    |
| Search     | Tavily                                                          |

## Prerequisites

- Python 3.13+
- Node 20+
- API keys for [Anthropic](https://console.anthropic.com/) and [Tavily](https://tavily.com/)

## Setup

```bash
git clone https://github.com/Akash-Sannidhanam/Agentic-Research.git
cd Agentic-Research

# Backend
python3.13 -m venv .venv
source .venv/bin/activate
pip install -r backend/requirements.txt
cp backend/.env.example backend/.env
# then edit backend/.env and fill in ANTHROPIC_API_KEY and TAVILY_API_KEY

# Frontend
cd frontend
npm install
cd ..
```

## Run

Two terminals:

```bash
# Terminal 1 — backend on http://localhost:8000
source .venv/bin/activate
python -m backend.run
```

```bash
# Terminal 2 — frontend on http://localhost:3000
cd frontend
npm run dev
```

Open http://localhost:3000, enter a topic, and approve the checkpoints as they appear. The backend's CORS origin and the frontend's WebSocket URL are hardcoded to these ports — see [Known limitations](#known-limitations) if you need to change them.

## Agent flow

The agent moves through four phases. Between them are two human-in-the-loop gates, during which the run sits in a `waiting_human` state until you submit a decision.

1. **`search`** — Tavily returns up to 8 results for the topic.
2. **Checkpoint 1 — `source_review`** — you pick which sources to read; rejecting ends the run.
3. **`read`** — each selected URL is fetched with `httpx` and cleaned with BeautifulSoup (scripts, nav, footers stripped; text capped at 8 KB per source). Fetches run **in parallel** via `asyncio.as_completed`, so this phase takes roughly the slowest single fetch instead of the sum.
4. **`synthesize`** — Claude produces a 3-5 bullet summary per source.
5. **Checkpoint 2 — `synthesis_review`** — you can add feedback to steer the draft; rejecting ends the run.
6. **`draft`** — Claude generates a structured brief (executive summary, sections, citations, takeaways).

Transient 5xx errors during `search` and `read` are retried twice with exponential backoff (1s, 2s). 4xx errors are logged and skipped — the run continues with the sources that did load.

The `synthesize` phase uses [prompt caching](https://docs.anthropic.com/en/docs/build-with-claude/prompt-caching) on its system prompt: the first source pays the ~1.25× cache-write premium, subsequent sources hit the cache at ~0.1× input cost. Each trace entry surfaces `cache_creation_tokens` and `cache_read_tokens` so you can see this directly. The `draft` phase runs once per run and is not cached.

The `read` phase fetches all selected URLs concurrently with `asyncio.as_completed`. Wall time drops from `sum(per-url latency)` to roughly `max(per-url latency)` — for the default 5 sources, ~5–10 s sequential becomes ~1–2 s. Trace events stream to the frontend in completion order, so the fastest fetches surface first instead of the user waiting for all reads to flush at once.

## WebSocket API

Useful if you want to drive the backend from something other than the Next.js UI.

**Endpoint:** `ws://localhost:8000/ws/research`

### Client → server

```jsonc
// 1. First message after connect — starts the run
{ "topic": "your research topic" }

// 2. Response to each checkpoint
{
  "decision": "approve",          // or "reject"
  "feedback": "optional string",
  "selected_sources": [0, 2, 3]   // indices, or null to use all
}
```

### Server → client

| Event        | Payload                                                      |
| ------------ | ------------------------------------------------------------ |
| `started`    | `{ run_id }`                                                 |
| `trace`      | `{ entry, state }` — one per agent step                      |
| `checkpoint` | `{ name, data: { message, sources?, summaries? }, state }`   |
| `draft`      | `{ content }` — final markdown brief                         |
| `done`       | `{ state, reason? }`                                         |
| `error`      | `{ error, state }`                                           |

Every event carries the full agent state, so a client can reconnect and re-render without keeping its own copy.

## Project structure

```
backend/
  agent/
    state.py        phases, trace entries, cost tracking
    core.py         agent loop + checkpoint orchestration
  tools/
    search.py       Tavily web search
    reader.py       URL fetcher + HTML-to-text
  api/
    server.py       FastAPI app + WebSocket endpoint
  evals/
    dataset.yaml    fixed topic set (standard + scripted HITL cases)
    runner.py       drives the agent headless, auto-answers checkpoints
    graders/        deterministic checks, HITL invariants, LLM-as-judge
    report.py       JSON + Markdown scorecard, baseline diff
    __main__.py     CLI entry point
  run.py            uvicorn entry point
frontend/
  app/page.tsx
  components/       TracePanel, CheckpointModal, CostBar
  lib/useResearchAgent.ts   WebSocket hook
tests/
  test_state.py        state machine tests
  test_read_phase.py   parallel read-phase tests
```

## Testing

```bash
python tests/test_state.py
python tests/test_read_phase.py
```

`test_state.py` covers the state machine (phase transitions, trace aggregation, cost math). `test_read_phase.py` exercises the read phase against a stubbed reader to verify parallel fetching and per-source error isolation. The remaining agent loop, tools, and WebSocket protocol are not covered yet.

## Evals

End-to-end quality check over a fixed dataset of research topics. Answers _"did this change make the brief better or worse?"_ before merging.

```bash
python -m backend.evals                              # full suite (~$2–3)
python -m backend.evals --subset smoke               # first 3 topics, smoke run
python -m backend.evals --topics gpu-shortage-ai     # comma-separated IDs
python -m backend.evals --baseline backend/evals/results/baseline.json
python -m backend.evals --no-cache                   # re-fetch source content
```

### What gets measured

Each topic runs the full agent (search → read → synthesize → draft), auto-approving HITL checkpoints. Two dataset entries are scripted-HITL: they reject specific sources and pass synthesis feedback, and their drafts are checked with invariants (the rejected URLs must not appear, feedback keywords should).

Grading is layered:

| Layer | How | Scores |
| --- | --- | --- |
| Deterministic | Regex/parser on the draft | `structure_score` 0 or 1 — gates the judge |
| Invariants (HITL only) | Pure functions on draft + HITL config | pass/fail per check |
| LLM-as-judge | Claude Haiku 4.5, tool-use for structured output | 1–5 on faithfulness, specificity, coverage, citation quality |

A structure fail skips the LLM judge for that topic and sets its scores to 0 — a broken brief shouldn't get graded on prose.

### Output

Every run writes `backend/evals/results/run-<UTC_ISO>.json` and `run-<UTC_ISO>.md`. The Markdown scorecard shows aggregate means, a per-topic table (composite, F/S/C/CQ dimensions, citation coverage, structure, cost, time), and per-topic rationales. With `--baseline`, a diff section is appended; any judge-dimension drop ≥ 0.5 is flagged as a regression.

### Cost controls

- Source content is cached on disk under `backend/evals/cache/`. First run fetches; later runs skip the network and pay only for Claude calls.
- The LLM judge uses Haiku 4.5 (≈3× cheaper than Sonnet) with its rubric system prompt marked cacheable.
- `--subset smoke` runs 3 topics for quick iteration.

## Known limitations

- **Localhost-only for now.** Backend CORS is pinned to `http://localhost:3000` and the frontend's WebSocket URL is pinned to `ws://localhost:8000/ws/research`. Both will be parameterized once the project is deployed.
- **Cost math assumes Sonnet pricing.** Rates are hardcoded in `backend/agent/state.py`; swapping models without updating them will produce wrong numbers.
- **No token streaming.** The WebSocket streams _events_ (trace steps, checkpoints, final draft), not tokens. Claude responses arrive whole.
- **4xx fetches degrade silently.** A 404 or 403 on a source is logged as an error trace entry but does not fail the run.
- **No persistence.** Each run is held in memory; closing the tab loses everything.

## Roadmap

- `/history` page showing past runs with cost breakdowns
- Per-phase model routing (Sonnet for summaries, Opus for final draft)
- Structured outputs via tool-use JSON schema for the final brief

## License

[MIT](./LICENSE)
