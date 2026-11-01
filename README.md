# TaskGraph — Deterministic Multi-Agent Orchestrator

Turn a CSV + a natural-language question into a validated, human-approved task
graph (DAG), execute it with independently scalable, sandboxed workers, and
get a final report that has been cross-checked against the numbers it claims
to be reporting on.

The core idea: **LLMs propose and judge; code owns execution.** The planner
and reviewer agents produce and vet a plan, but a deterministic orchestrator
— not the model — owns DAG validation, task scheduling, atomic task claiming,
retries, and failure recovery. Every generated code snippet runs in a
resource-limited sandbox with access only to the artifacts its task declared
it needs. The final report is checked by a separate faithfulness pass before
it's shown to you.

## Why this design

Most "agentic" demos let the model drive execution directly — one bad step
can cascade with nothing to catch it, and debugging means re-reading a
reasoning trace instead of a stack trace. TaskGraph treats the LLM as an
unreliable component and builds the reliability *around* it: separate
proposer/judge roles, a deterministic scheduler, sandboxed execution, scoped
artifact access, and post-hoc verification. See `DESIGN.md` for the full
reasoning and failure-mode analysis.

## Architecture

```
 ┌──────────┐   HTTP/SSE   ┌─────────┐        ┌────────────┐
 │ Frontend │◄────────────►│   API   │        │            │
 └──────────┘              └────┬────┘        │ PostgreSQL │
                                 │ writes run/  │ (state +   │
                                 │ plan rows    │  queue)    │
                                 ▼              │            │
                          ┌─────────────┐       └─────┬──────┘
                          │ Orchestrator │◄────────────┤
                          │ (scheduler)  │             │
                          └──────────────┘             │
                                                        │
                          ┌─────────────┐   claims via  │
                          │  Worker(s)   │◄─SKIP LOCKED──┘
                          │ (sandboxed   │
                          │  execution)  │
                          └─────────────┘
```

- **Planner agent** — reads CSV schema/sample + the question, proposes a
  typed task DAG (JSON).
- **DAG validator (code)** — cycle detection, dependency/artifact-reference
  correctness, structural validation. Pure code, fully unit tested.
- **Semantic reviewer agent** — separate LLM call, separate responsibility:
  judges whether the *proposed plan* can actually answer the question.
- **Approval gate** — a human sees the plan and approves/rejects before any
  execution happens.
- **Orchestrator (code)** — computes the eligible frontier of a run's DAG and
  marks tasks eligible for pickup.
- **Worker (code + LLM)** — atomically claims an eligible task
  (`SELECT ... FOR UPDATE SKIP LOCKED`), asks a coder agent to write Python
  scoped to that task's declared inputs, executes it in an isolated
  subprocess with CPU/memory/time limits, and persists only the declared
  output artifacts.
- **Terminal agent** — synthesizes the final report from artifacts.
- **Faithfulness checker (code + LLM)** — extracts the numeric claims in the
  report and verifies each against the actual computed artifact values,
  flagging anything unsupported.

## Deployment topologies

This repo ships **two ways to run the same code**:

1. **Local / Docker Compose (reference architecture)** — `api`,
   `orchestrator`, and `worker` run as independently scalable containers
   (`docker compose up --scale worker=4`) against a real Postgres instance.
   This is the architecture described above and in `DESIGN.md`, and the one
   worth walking through in an interview.
2. **Render (`deploy/render/`)** — a free, always-available public demo.
   Because free container hosts generally don't offer a free
   background-worker tier, this variant runs the orchestrator and worker
   loops as background tasks *inside* the single API process, against a
   free external Postgres (Neon/Supabase). It is the same core modules
   (`app/dag.py`, `app/orchestrator.py`, `app/worker.py`, `app/agents/*`) —
   only the process topology is collapsed for cost reasons. It does not
   demonstrate independent horizontal scaling; the Compose setup does.

## Quickstart (local, full architecture)

```bash
cp .env.example .env        # set GROQ_API_KEY (or leave blank to use the mock LLM)
docker compose up --build --scale worker=3
open http://localhost:8000
```

## Running tests

```bash
pip install -r requirements.txt
pytest -q
```

## Repo layout

```
app/
  dag.py              DAG validation (pure code, unit tested)
  orchestrator.py      frontier computation, atomic claim, retries, supersede
  worker.py             claim -> codegen -> sandbox exec -> persist artifacts
  sandbox.py           resource-limited subprocess execution
  llm.py               LLM client interface (Groq + deterministic mock)
  storage.py           artifact storage adapter (local fs; S3-shaped interface)
  models.py / db.py    SQLAlchemy models + session management
  api.py                FastAPI app: submit, approve, stream status, report
  agents/               planner, reviewer, coder, terminal, faithfulness
deploy/render/          collapsed single-process variant for the free public demo (Render)
frontend/index.html    minimal single-page UI (upload -> plan -> approve -> live status -> report)
tests/                  DAG validator, orchestrator state machine, sandbox
```

## Status / known limitations

- Sandbox isolation is best-effort (resource limits + subprocess isolation),
  not container-level. See `DESIGN.md` for what a production hardening pass
  would add (nsjail/firejail, network namespace isolation).
- Faithfulness checking is a heuristic numeric cross-check, not a full
  natural-language entailment model — documented tradeoff, see `DESIGN.md`.
