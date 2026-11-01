from datetime import datetime, timedelta, timezone

from app import orchestrator
from app.config import settings
from app.models import Run, Task


def make_run_with_tasks(session, task_specs):
    """task_specs: list of (id, depends_on) tuples."""
    run = Run(dataset_path="/tmp/fake.csv", question="q", status="running")
    session.add(run)
    session.flush()
    for tid, deps in task_specs:
        session.add(Task(
            id=tid, run_id=run.id, name=tid, depends_on=deps,
            input_keys=[], output_keys=[], status="pending",
        ))
    session.flush()
    return run


def test_frontier_starts_with_root_tasks_only(db_session):
    run = make_run_with_tasks(db_session, [("a", []), ("b", ["a"])])
    flipped = orchestrator.compute_eligible_frontier(db_session, run.id)
    assert flipped == ["a"]

    a = db_session.get(Task, "a")
    b = db_session.get(Task, "b")
    assert a.status == "eligible"
    assert b.status == "pending"


def test_frontier_advances_after_dependency_succeeds(db_session):
    run = make_run_with_tasks(db_session, [("a", []), ("b", ["a"])])
    orchestrator.compute_eligible_frontier(db_session, run.id)

    a = db_session.get(Task, "a")
    a.status = "succeeded"
    db_session.flush()

    flipped = orchestrator.compute_eligible_frontier(db_session, run.id)
    assert flipped == ["b"]


def test_claim_next_task_is_idempotent_when_none_eligible(db_session):
    run = make_run_with_tasks(db_session, [("a", [])])
    # not yet flipped to eligible
    task = orchestrator.claim_next_task(db_session, run.id, "worker-1")
    assert task is None


def test_claim_next_task_claims_and_marks(db_session):
    run = make_run_with_tasks(db_session, [("a", [])])
    orchestrator.compute_eligible_frontier(db_session, run.id)

    task = orchestrator.claim_next_task(db_session, run.id, "worker-1")
    assert task is not None
    assert task.status == "claimed"
    assert task.claimed_by == "worker-1"

    # a second claim attempt finds nothing left eligible
    again = orchestrator.claim_next_task(db_session, run.id, "worker-2")
    assert again is None


def test_retry_on_failure_until_attempt_cap(db_session):
    run = make_run_with_tasks(db_session, [("a", [])])
    a = db_session.get(Task, "a")
    a.status = "eligible"
    db_session.flush()

    for attempt_num in range(1, settings.max_task_attempts + 1):
        orchestrator.start_new_attempt(db_session, a, "worker-1")
        status = orchestrator.record_attempt_result(db_session, a, success=False, error="boom")
        if attempt_num < settings.max_task_attempts:
            assert status == "eligible", f"attempt {attempt_num} should retry"
        else:
            assert status == "failed", "should stop retrying at the attempt cap"


def test_success_marks_succeeded(db_session):
    run = make_run_with_tasks(db_session, [("a", [])])
    a = db_session.get(Task, "a")
    a.status = "eligible"
    db_session.flush()

    orchestrator.start_new_attempt(db_session, a, "worker-1")
    status = orchestrator.record_attempt_result(db_session, a, success=True)
    assert status == "succeeded"


def test_permanent_failure_supersedes_descendants(db_session):
    run = make_run_with_tasks(db_session, [
        ("a", []), ("b", ["a"]), ("c", ["b"]), ("d", []),  # d is unrelated
    ])
    a = db_session.get(Task, "a")
    a.status = "eligible"
    a.attempt_count = settings.max_task_attempts  # already at cap
    db_session.flush()

    orchestrator.start_new_attempt(db_session, a, "worker-1")
    orchestrator.record_attempt_result(db_session, a, success=False, error="boom")

    b = db_session.get(Task, "b")
    c = db_session.get(Task, "c")
    d = db_session.get(Task, "d")
    assert b.status == "superseded"
    assert c.status == "superseded"
    assert d.status == "pending"  # unrelated branch untouched


def test_reap_stale_claims_reclaims_past_heartbeat(db_session):
    run = make_run_with_tasks(db_session, [("a", [])])
    a = db_session.get(Task, "a")
    a.status = "claimed"
    a.claimed_by = "dead-worker"
    a.claimed_at = datetime.now(timezone.utc) - timedelta(
        seconds=settings.claim_heartbeat_timeout_seconds + 10
    )
    db_session.flush()

    reaped = orchestrator.reap_stale_claims(db_session, run.id)
    assert reaped == ["a"]
    assert a.status == "eligible"
    assert a.claimed_by is None


def test_reap_stale_claims_ignores_fresh_claims(db_session):
    run = make_run_with_tasks(db_session, [("a", [])])
    a = db_session.get(Task, "a")
    a.status = "claimed"
    a.claimed_by = "worker-1"
    a.claimed_at = datetime.now(timezone.utc)
    db_session.flush()

    reaped = orchestrator.reap_stale_claims(db_session, run.id)
    assert reaped == []
    assert a.status == "claimed"


def test_run_is_complete_detection(db_session):
    run = make_run_with_tasks(db_session, [("a", []), ("b", ["a"])])
    assert orchestrator.run_is_complete(db_session, run.id) is False

    db_session.get(Task, "a").status = "succeeded"
    db_session.get(Task, "b").status = "succeeded"
    db_session.flush()
    assert orchestrator.run_is_complete(db_session, run.id) is True


def test_run_has_failure_detection(db_session):
    run = make_run_with_tasks(db_session, [("a", [])])
    assert orchestrator.run_has_failure(db_session, run.id) is False
    db_session.get(Task, "a").status = "failed"
    db_session.flush()
    assert orchestrator.run_has_failure(db_session, run.id) is True
