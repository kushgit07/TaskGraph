import pytest

from app.dag import DAGValidationError, validate_dag


def make_task(id, depends_on=None, input_keys=None, output_keys=None):
    return {
        "id": id,
        "name": id,
        "depends_on": depends_on or [],
        "input_keys": input_keys or [],
        "output_keys": output_keys or [],
    }


def test_valid_linear_plan_passes():
    plan = [
        make_task("a", input_keys=["raw_dataset"], output_keys=["summary"]),
        make_task("b", depends_on=["a"], input_keys=["summary"], output_keys=["report"]),
    ]
    validated = validate_dag(plan)
    assert validated.topological_order == ["a", "b"]


def test_valid_diamond_plan_passes():
    plan = [
        make_task("a", input_keys=["raw_dataset"], output_keys=["x"]),
        make_task("b", depends_on=["a"], input_keys=["x"], output_keys=["y"]),
        make_task("c", depends_on=["a"], input_keys=["x"], output_keys=["z"]),
        make_task("d", depends_on=["b", "c"], input_keys=["y", "z"], output_keys=["final"]),
    ]
    validated = validate_dag(plan)
    assert validated.topological_order.index("a") < validated.topological_order.index("b")
    assert validated.topological_order.index("a") < validated.topological_order.index("c")
    assert validated.topological_order.index("b") < validated.topological_order.index("d")
    assert validated.topological_order.index("c") < validated.topological_order.index("d")


def test_empty_plan_rejected():
    with pytest.raises(DAGValidationError):
        validate_dag([])


def test_duplicate_ids_rejected():
    plan = [
        make_task("a", input_keys=["raw_dataset"], output_keys=["x"]),
        make_task("a", input_keys=["raw_dataset"], output_keys=["y"]),
    ]
    with pytest.raises(DAGValidationError) as exc:
        validate_dag(plan)
    assert "duplicate" in str(exc.value)


def test_unknown_dependency_rejected():
    plan = [make_task("a", depends_on=["ghost"], input_keys=["raw_dataset"], output_keys=["x"])]
    with pytest.raises(DAGValidationError) as exc:
        validate_dag(plan)
    assert "unknown task" in str(exc.value)


def test_direct_cycle_rejected():
    plan = [
        make_task("a", depends_on=["b"], input_keys=["raw_dataset"], output_keys=["x"]),
        make_task("b", depends_on=["a"], input_keys=["raw_dataset"], output_keys=["y"]),
    ]
    with pytest.raises(DAGValidationError) as exc:
        validate_dag(plan)
    assert "cycle" in str(exc.value)


def test_self_cycle_rejected():
    plan = [make_task("a", depends_on=["a"], input_keys=["raw_dataset"], output_keys=["x"])]
    with pytest.raises(DAGValidationError) as exc:
        validate_dag(plan)
    assert "cycle" in str(exc.value)


def test_longer_cycle_rejected():
    plan = [
        make_task("a", depends_on=["c"], input_keys=["raw_dataset"], output_keys=["x"]),
        make_task("b", depends_on=["a"], input_keys=["x"], output_keys=["y"]),
        make_task("c", depends_on=["b"], input_keys=["y"], output_keys=["z"]),
    ]
    with pytest.raises(DAGValidationError) as exc:
        validate_dag(plan)
    assert "cycle" in str(exc.value)


def test_undeclared_input_rejected():
    # 'b' asks for 'z' but nothing produces 'z'
    plan = [
        make_task("a", input_keys=["raw_dataset"], output_keys=["x"]),
        make_task("b", depends_on=["a"], input_keys=["z"], output_keys=["y"]),
    ]
    with pytest.raises(DAGValidationError) as exc:
        validate_dag(plan)
    assert "not produced by any ancestor" in str(exc.value)


def test_input_from_non_dependency_task_rejected():
    # 'c' wants 'x' (produced by 'a') but doesn't depend on 'a' -- must fail,
    # since ordering/availability isn't guaranteed without the edge.
    plan = [
        make_task("a", input_keys=["raw_dataset"], output_keys=["x"]),
        make_task("b", input_keys=["raw_dataset"], output_keys=["y"]),
        make_task("c", depends_on=["b"], input_keys=["x"], output_keys=["z"]),
    ]
    with pytest.raises(DAGValidationError):
        validate_dag(plan)


def test_raw_dataset_always_available():
    plan = [make_task("a", input_keys=["raw_dataset"], output_keys=["x"])]
    validated = validate_dag(plan)
    assert "a" in validated.tasks_by_id
