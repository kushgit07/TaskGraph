"""Pure-code DAG validation. No I/O, no LLM calls — this is the piece that
must be trustworthy on its own, so it's the most heavily unit-tested module
in the repo (see tests/test_dag.py).

A "plan" is a list of task dicts of the shape:

    {
        "id": "task_1",
        "name": "...",
        "description": "...",
        "depends_on": ["task_0"],
        "input_keys": ["raw_dataset"],
        "output_keys": ["monthly_revenue"],
    }

The special artifact key "raw_dataset" always exists (it's the uploaded
CSV) and never needs to be produced by a task.
"""
from dataclasses import dataclass, field

RAW_DATASET_KEY = "raw_dataset"


class DAGValidationError(Exception):
    """Raised when a proposed plan is structurally invalid. Carries a list
    of human-readable problems so the API can surface all of them at once
    instead of failing on the first one."""

    def __init__(self, problems: list[str]):
        self.problems = problems
        super().__init__("; ".join(problems))


@dataclass
class ValidatedPlan:
    tasks_by_id: dict = field(default_factory=dict)
    topological_order: list = field(default_factory=list)


def validate_dag(plan: list[dict]) -> ValidatedPlan:
    problems: list[str] = []

    if not plan:
        raise DAGValidationError(["plan must contain at least one task"])

    # 1. Unique ids
    ids = [t.get("id") for t in plan]
    seen = set()
    dupes = set()
    for tid in ids:
        if tid in seen:
            dupes.add(tid)
        seen.add(tid)
    if dupes:
        problems.append(f"duplicate task ids: {sorted(dupes)}")

    tasks_by_id = {t["id"]: t for t in plan if t.get("id")}

    # 2. depends_on references exist
    for t in plan:
        for dep in t.get("depends_on", []):
            if dep not in tasks_by_id:
                problems.append(
                    f"task '{t.get('id')}' depends_on unknown task '{dep}'"
                )

    # 3. Cycle detection (DFS, only if references are otherwise sane)
    if not problems:
        color = {tid: "white" for tid in tasks_by_id}  # white/gray/black
        cycle_found = []

        def dfs(node):
            color[node] = "gray"
            for dep in tasks_by_id[node].get("depends_on", []):
                if color[dep] == "gray":
                    cycle_found.append((node, dep))
                elif color[dep] == "white":
                    dfs(dep)
            color[node] = "black"

        for tid in tasks_by_id:
            if color[tid] == "white":
                dfs(tid)

        if cycle_found:
            problems.append(f"cycle detected involving edges: {cycle_found}")

    # 4. Every declared input_key is either the raw dataset or produced by
    #    an ancestor's output_keys
    if not problems:
        for t in plan:
            producers_available = {RAW_DATASET_KEY}
            # collect output_keys of all (transitive) ancestors
            stack = list(t.get("depends_on", []))
            visited_anc = set()
            while stack:
                anc_id = stack.pop()
                if anc_id in visited_anc:
                    continue
                visited_anc.add(anc_id)
                anc = tasks_by_id.get(anc_id)
                if not anc:
                    continue
                producers_available.update(anc.get("output_keys", []))
                stack.extend(anc.get("depends_on", []))

            for key in t.get("input_keys", []):
                if key not in producers_available:
                    problems.append(
                        f"task '{t.get('id')}' requires input '{key}' which "
                        "is not the raw dataset and is not produced by any "
                        "ancestor task"
                    )

    if problems:
        raise DAGValidationError(problems)

    return ValidatedPlan(
        tasks_by_id=tasks_by_id,
        topological_order=_topological_order(tasks_by_id),
    )


def _topological_order(tasks_by_id: dict) -> list[str]:
    """Kahn's algorithm. Only called after cycle detection has already
    passed, so this cannot raise on a cyclic graph."""
    in_degree = {tid: 0 for tid in tasks_by_id}
    children = {tid: [] for tid in tasks_by_id}
    for tid, t in tasks_by_id.items():
        for dep in t.get("depends_on", []):
            in_degree[tid] += 1
            children[dep].append(tid)

    queue = [tid for tid, d in in_degree.items() if d == 0]
    order = []
    while queue:
        node = queue.pop(0)
        order.append(node)
        for child in children[node]:
            in_degree[child] -= 1
            if in_degree[child] == 0:
                queue.append(child)
    return order
