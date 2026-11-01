"""Terminal agent — synthesizes the final report from the run's artifacts.
Its output is NOT trusted as-is: app.agents.faithfulness checks it before
it's shown to the user."""
from app.llm import LLMClient

SYSTEM_PROMPT = """You are a reporting agent. Given a user's original \
question and the computed artifacts from a data pipeline, write a clear, \
concise report answering the question. Only state numbers that appear in \
the provided artifacts — do not invent figures.
"""


def write_report(llm: LLMClient, question: str, artifact_previews: dict) -> str:
    user = f"Question: {question}\n\nComputed artifacts:\n{artifact_previews}"
    return llm.complete_text(SYSTEM_PROMPT, user)
