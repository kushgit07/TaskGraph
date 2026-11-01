# DESIGN

## 1. Data model

- **Run** — one submitted (CSV, question) pair. Status:
  `pending_plan -> awaiting_approval -> running -> completed | failed`.
- **Task** — one node in the DAG. Status:
  `pending -> eligible -> claimed -> running -> succeeded | failed -> superseded`.
  Holds `depends_on` (task ids), declared `input_keys` / `output_keys`
  (artifact keys), and the code generated for it.
- **TaskAttempt** — one execution attempt of a task (a task can have several
  on retry). Holds status, error, timing, worker id.
- **Artifact** — a named, typed output produced by a task and stored via the
  storage adapter. Downstream tasks reference artifacts by key, never by
  file path — the worker resolves keys to paths, so a task can't reach
  outside what it declared.

## 2. DAG validation (`app/dag.py`)

Pure code, no I/O. Given a proposed plan (list of task specs), it checks:

- Every task id is unique.
- Every `depends_on` reference points at a task id that exists in the plan.
- No cycles (DFS-based detection).
- Every declared `input_key` is produced as an `output_key` by some ancestor
  task (or is the raw uploaded dataset) — catches a planner that invents an
  artifact that nothing produces.

This runs **before** the plan is shown for human approval, so a structurally
broken plan never reaches the approval step.

## 3. Orchestration (`app/orchestrator.py`)

- `compute_eligible_frontier(run_id)` — for a run, finds every `pending`
  task whose dependencies have all `succeeded`, and flips it to `eligible`.
  Runs on a poll loop (or could be event-driven off task completion).
- `claim_next_task(worker_id)` —
  `SELECT ... FOR UPDATE SKIP LOCKED WHERE status='eligible' LIMIT 1`,
  then updates to `claimed`. This is what makes the worker fleet safe to
  scale horizontally: two workers racing for the same row never both win.
- `record_attempt_result(...)` — on success, marks the task `succeeded` and
  persists its artifacts; on failure, either schedules a retry (new
  `TaskAttempt`, task back to `eligible`) if under the attempt cap, or marks
  the task `failed` and calls `supersede_descendants`, which walks the DAG
  forward and marks every downstream task `superseded` rather than letting
  them hang forever waiting on a dependency that will never succeed.

## 4. Sandboxed execution (`app/sandbox.py`)

The coder agent's generated Python runs in a subprocess:

- A fresh temp directory containing **only** the task's declared input
  artifacts (copied in by key, not the run's full artifact set).
- CPU time, memory, and wall-clock timeout limits (`resource.setrlimit` +
  a hard `subprocess` timeout as a backstop).
- Any file the script writes into the temp dir is a *candidate* output; only
  files matching the task's declared `output_keys` are persisted as
  artifacts. Everything else is discarded.

**Known limitation:** this is process-level isolation, not container-level.
It stops accidental resource exhaustion and accidental cross-task file
access, but a sufficiently adversarial generated script could still escape
a subprocess sandbox. A production hardening pass would run each task in
its own short-lived container (or `nsjail`/`firejail`) with a locked-down
network namespace. Documented here rather than silently assumed away.

## 5. Faithfulness check (`app/agents/faithfulness.py`)

The terminal agent writes a report from the run's artifacts. Before showing
it, a separate pass:

1. Extracts numeric claims from the report text (regex-based numeric/percent
   extraction — not full NLI).
2. Checks each extracted number against the actual values present in the
   run's artifacts (with a tolerance for rounding).
3. Flags any claim that doesn't match anything computed, and attaches those
   flags to the report rather than silently hiding them.

**Known limitation:** this catches numeric fabrication, not fabricated
*qualitative* claims ("sales trended upward" when they didn't). A stronger
version would use a second LLM call specifically to verify each sentence's
claim against the artifact data — noted as a natural next step, not built
here to keep the scope honest.

## 6. Failure modes considered

| Failure | Handling |
|---|---|
| Two workers claim the same task | Prevented structurally by `SKIP LOCKED` — not a race that can occur |
| Worker crashes mid-task | Task stays `claimed`/`running`; a reaper (`orchestrator.reap_stale_claims`) reclaims tasks whose attempt has exceeded a heartbeat timeout back to `eligible` |
| Task fails repeatedly | Attempt cap enforced; task marked `failed` after N attempts, not retried forever |
| A task's ancestor permanently fails | Descendants marked `superseded`, not silently stuck `pending` forever |
| Planner proposes an impossible plan | Caught by `dag.py` validation before approval is even possible |
| Planner proposes a *structurally valid but semantically wrong* plan | Caught by the separate reviewer agent, a different responsibility from the planner |
| Generated code tries to read outside its scoped inputs | Sandbox only copies declared inputs into the execution directory |
| Final report overstates what was actually found | Faithfulness pass flags numeric claims unsupported by artifacts |

## 7. Deployment topologies

See `README.md` — the same modules run either as independently scalable
Docker Compose services (reference architecture) or collapsed into a single
process for the free Render demo. The collapse is purely a
process-topology decision made in `deploy/render/app_combined.py`; none of
`app/dag.py`, `app/orchestrator.py`, `app/worker.py`, or `app/agents/*`
change between the two.
