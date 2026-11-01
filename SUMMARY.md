# SUMMARY

## Problem
LLM agents are good at proposing plans and writing code, unreliable at
knowing when they've gone wrong. Letting a model drive execution directly
means one bad step can cascade silently.

## Approach
Split the system into two trust domains:

- **Non-deterministic (LLM):** propose a plan, judge a plan, write task
  code, write a report, judge the report's own claims.
- **Deterministic (code):** validate the plan's structure, decide what's
  eligible to run, atomically claim work, isolate execution, retry or
  supersede on failure, persist everything for audit.

The model is never on the control-flow path. It only produces artifacts
that code then validates, schedules, sandboxes, or checks.

## Reliability mechanisms
1. DAG validation (cycle detection, dependency correctness) before any
   approval is even possible.
2. Separate planner / reviewer roles — the model that proposes a plan is
   not the model that approves it.
3. Human approval gate before execution starts.
4. Atomic task claiming (`SELECT ... FOR UPDATE SKIP LOCKED`) so multiple
   workers can pull from the same queue without double-executing a task.
5. Sandboxed, resource-limited execution of model-generated code, scoped to
   only the artifacts a task declared as inputs.
6. Retry with attempt tracking; permanent ancestor failure supersedes
   (rather than silently skips) downstream tasks.
7. Post-hoc faithfulness check: claims in the final report are extracted and
   verified against the actual computed artifact values before being shown.

## Tradeoffs made (see DESIGN.md for detail)
- Sandbox is process-level isolation (resource limits + subprocess), not
  container-level — documented, not hidden.
- Faithfulness check is a numeric-claim heuristic, not full NLI.
- Two deployment topologies ship from one codebase: full independently
  scalable services locally via Docker Compose, and a cost-collapsed
  single-process variant for the free public demo on Render.
