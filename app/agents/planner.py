"""Planner agent — proposes a task DAG. This is a *proposal only*; it is
validated by app.dag.validate_dag() and separately judged by the reviewer
agent before a human ever approves it. The planner has no authority over
execution."""
from app.llm import LLMClient

SYSTEM_PROMPT = """You are a data analysis planning agent. Given a dataset \
schema and a user's question, propose a task DAG that computes what's \
needed to answer the question.

Respond with JSON of the shape:
{
  "tasks": [
    {
      "id": "short_snake_case_id",
      "name": "Human readable name",
      "description": "what this task computes and how",
      "depends_on": ["other_task_id", ...],
      "input_keys": ["raw_dataset" or an output_key of an ancestor task],
      "output_keys": ["artifact_key_this_task_produces"]
    }
  ]
}

Rules:
- "raw_dataset" always exists and refers to the uploaded CSV; you never \
need to produce it.
- Keep the DAG small (2-6 tasks) and only as complex as the question needs.
- Every input_key must be either "raw_dataset" or an output_key produced \
by an ancestor task (via depends_on).
"""


def propose_plan(llm: LLMClient, dataset_schema: str, question: str) -> list[dict]:
    user = f"Dataset schema:\n{dataset_schema}\n\nQuestion: {question}"
    result = llm.complete_json(SYSTEM_PROMPT, user)
    tasks = result.get("tasks", [])
    if not tasks:
        raise ValueError("planner returned no tasks")
    return tasks
