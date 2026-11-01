"""Coder agent — writes the Python for ONE task, scoped to only that
task's declared inputs/outputs. Runs inside the sandbox (app.sandbox),
never given filesystem access beyond what's copied in for it."""
from app.llm import LLMClient

SYSTEM_PROMPT = """Write Python code to accomplish exactly one task in a \
data pipeline.

Environment contract (do not deviate):
- Input artifacts are available at:
  os.path.join(os.environ['TASKGRAPH_WORKDIR'], 'input_<key>')
  for each declared input key.
- You MUST write each declared output to:
  os.path.join(os.environ['TASKGRAPH_WORKDIR'], 'output_<key>')
- Use only pandas/json/os/csv from the standard toolset. No network calls, \
no reading/writing any path outside TASKGRAPH_WORKDIR.
- The raw dataset input (if used) is a CSV file readable with pd.read_csv.

Respond with JSON: {"code": "<the full python script as a string>"}
"""


def generate_task_code(llm: LLMClient, task: dict) -> str:
    user = (
        f"Task: {task['name']}\n"
        f"Description: {task.get('description', '')}\n"
        f"Input keys: {task.get('input_keys', [])}\n"
        f"Output keys: {task.get('output_keys', [])}\n"
    )
    result = llm.complete_json(SYSTEM_PROMPT, user)
    code = result.get("code")
    if not code:
        raise ValueError("coder agent returned no code")
    return code
