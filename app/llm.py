"""LLM client behind a small interface so agents don't care whether they're
talking to Groq or a deterministic mock. The mock exists so the whole
pipeline (including tests and a no-API-key demo) is runnable for $0 without
external network access — set GROQ_API_KEY to switch to the real thing.
"""
import json
from abc import ABC, abstractmethod

from app.config import settings


class LLMClient(ABC):
    @abstractmethod
    def complete_json(self, system: str, user: str) -> dict:
        """Return a parsed JSON object. Implementations must instruct the
        model to return ONLY JSON, and should raise ValueError on a
        response that doesn't parse."""

    @abstractmethod
    def complete_text(self, system: str, user: str) -> str:
        """Return free-form text (used for the terminal report)."""


class GroqLLMClient(LLMClient):
    def __init__(self):
        from groq import Groq  # imported lazily so the mock path never needs the package
        self._client = Groq(api_key=settings.groq_api_key)
        self._model = settings.groq_model

    def _chat(self, system: str, user: str) -> str:
        resp = self._client.chat.completions.create(
            model=self._model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature=0.2,
        )
        return resp.choices[0].message.content

    def complete_json(self, system: str, user: str) -> dict:
        text = self._chat(
            system + "\nRespond with ONLY valid JSON. No prose, no markdown fences.",
            user,
        )
        text = text.strip().strip("`")
        if text.startswith("json"):
            text = text[4:]
        try:
            return json.loads(text)
        except json.JSONDecodeError as e:
            raise ValueError(f"LLM did not return valid JSON: {e}\nRaw: {text[:500]}")

    def complete_text(self, system: str, user: str) -> str:
        return self._chat(system, user)


class MockLLMClient(LLMClient):
    """Deterministic, rule-based stand-in for a real model. Good enough to
    exercise the full pipeline (planner -> reviewer -> coder -> terminal ->
    faithfulness) end-to-end without any API key. Real intelligence comes
    from GroqLLMClient; this exists purely so the system is runnable and
    testable for free."""

    def complete_json(self, system: str, user: str) -> dict:
        if "propose a task DAG" in system:
            return self._mock_plan()
        if "judge whether" in system:
            return {"approved": True, "feedback": "Mock reviewer: plan looks structurally reasonable."}
        if "Write Python code" in system:
            return self._mock_code(user)
        return {}

    def complete_text(self, system: str, user: str) -> str:
        return (
            "This is a mock terminal report generated without a live LLM. "
            "It summarizes the artifacts computed by the pipeline. "
            "Set GROQ_API_KEY to generate a real narrative report."
        )

    @staticmethod
    def _mock_plan() -> dict:
        return {
            "tasks": [
                {
                    "id": "summarize",
                    "name": "Summarize dataset",
                    "description": "Compute basic summary statistics of the uploaded dataset.",
                    "depends_on": [],
                    "input_keys": ["raw_dataset"],
                    "output_keys": ["summary_stats"],
                }
            ]
        }

    @staticmethod
    def _mock_code(user: str) -> dict:
        # Minimal, safe pandas summary script as a placeholder "generated" task.
        code = (
            "import pandas as pd, json, os\n"
            "df = pd.read_csv(os.path.join(os.environ['TASKGRAPH_WORKDIR'], 'input_raw_dataset'))\n"
            "summary = {'rows': len(df), 'columns': list(df.columns)}\n"
            "with open(os.path.join(os.environ['TASKGRAPH_WORKDIR'], 'output_summary_stats'), 'w') as f:\n"
            "    json.dump(summary, f)\n"
        )
        return {"code": code}


def get_llm_client() -> LLMClient:
    if settings.use_mock_llm:
        return MockLLMClient()
    return GroqLLMClient()
