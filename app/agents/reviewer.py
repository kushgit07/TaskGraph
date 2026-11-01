"""Semantic reviewer agent — a SEPARATE role from the planner. The planner
proposes; this agent judges whether the proposal can actually answer the
question. Deliberately not the same call/prompt as the planner, so a
plan's own author isn't the only one vetting it."""
from app.llm import LLMClient

SYSTEM_PROMPT = """You are a plan-review agent. You did not write this \
plan. Given a user's question and a proposed task DAG, judge whether \
executing this plan would actually produce an answer to the question.

Respond with JSON: {"approved": true|false, "feedback": "short explanation"}
"""


def review_plan(llm: LLMClient, question: str, plan: list[dict]) -> dict:
    user = f"Question: {question}\n\nProposed plan: {plan}"
    result = llm.complete_json(SYSTEM_PROMPT, user)
    return {
        "approved": bool(result.get("approved", False)),
        "feedback": result.get("feedback", ""),
    }
