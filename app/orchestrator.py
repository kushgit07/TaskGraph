"""Deterministic orchestrator. No LLM calls in this module — this is the
control plane and it must be predictable and fully unit-testable
(see tests/test_orchestrator.py).
"""
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.models import Task, TaskAttempt


def compute_eligible_frontier(session: Session, run_id: str) -> list[str]:
    """Flip every `pending` task whose dependencies have all `succeeded`
    to `eligible`. Returns the ids that were flipped."""
    tasks = session.execute(
        select(Task).where(Task.run_id == run_id)
    ).scalars().all()
    status_by_id = {t.id: t.status for t in tasks}

    flipped = []
    for t in tasks:
        if t.status != "pending":
            continue
        deps = t.depends_on or []
        if all(status_by_id.get(d) == "succeeded" for d in deps):
            t.status = "eligible"
            flipped.append(t.id)
    if flipped:
        session.flush()  # sessions are autoflush=False; make changes visible
        # to subsequent queries (e.g. claim_next_task) within the same session.
    return flipped


def claim_next_task(session: Session, run_id: str, worker_id: str) -> Task | None:
    """Atomically claim one eligible task for this run. Uses
    SELECT ... FOR UPDATE SKIP LOCKED on Postgres so multiple workers can
    poll concurrently without ever double-claiming a row. (SQLite doesn't
    support SKIP LOCKED; falls back to plain FOR-UPDATE-less select, which
    is fine for tests/single-process runs.)"""
    query = select(Task).where(
        Task.run_id == run_id, Task.status == "eligible"
    ).order_by(Task.created_at).limit(1)

    bind = session.get_bind()
    if bind.dialect.name == "postgresql":
        query = query.with_for_update(skip_locked=True)

    task = session.execute(query).scalars().first()
    if task is None:
        return None

    task.status = "claimed"
    task.claimed_by = worker_id
    task.claimed_at = datetime.now(timezone.utc)
    session.flush()
    return task


def record_attempt_result(
    session: Session,
    task: Task,
    success: bool,
    error: str | None = None,
) -> str:
    """Update task + attempt state after a worker finishes. Returns the
    resulting task status."""
    attempt = session.execute(
        select(TaskAttempt)
        .where(TaskAttempt.task_id == task.id)
        .order_by(TaskAttempt.attempt_number.desc())
        .limit(1)
    ).scalars().first()

    if attempt:
        attempt.status = "succeeded" if success else "failed"
        attempt.error = error
        attempt.finished_at = datetime.now(timezone.utc)

    if success:
        task.status = "succeeded"
        task.error = None
        return task.status

    task.error = error
    if task.attempt_count < settings.max_task_attempts:
        task.status = "eligible"  # will be retried
        task.claimed_by = None
        task.claimed_at = None
    else:
        task.status = "failed"
        supersede_descendants(session, task)
    return task.status


def start_new_attempt(session: Session, task: Task, worker_id: str) -> TaskAttempt:
    task.attempt_count += 1
    task.status = "running"
    attempt = TaskAttempt(
        task_id=task.id,
        attempt_number=task.attempt_count,
        worker_id=worker_id,
        status="running",
    )
    session.add(attempt)
    session.flush()
    return attempt


def supersede_descendants(session: Session, failed_task: Task) -> list[str]:
    """A task has permanently failed. Walk the DAG forward and mark every
    downstream task `superseded` rather than letting them sit `pending`
    forever waiting on a dependency that will never succeed."""
    all_tasks = session.execute(
        select(Task).where(Task.run_id == failed_task.run_id)
    ).scalars().all()

    children_of = {t.id: [] for t in all_tasks}
    for t in all_tasks:
        for dep in (t.depends_on or []):
            if dep in children_of:
                children_of[dep].append(t.id)

    by_id = {t.id: t for t in all_tasks}
    superseded = []
    stack = list(children_of.get(failed_task.id, []))
    seen = set()
    while stack:
        tid = stack.pop()
        if tid in seen:
            continue
        seen.add(tid)
        t = by_id[tid]
        if t.status not in ("succeeded", "failed"):
            t.status = "superseded"
            superseded.append(tid)
        stack.extend(children_of.get(tid, []))
    return superseded


def reap_stale_claims(session: Session, run_id: str) -> list[str]:
    """Reclaim tasks stuck `claimed`/`running` past the heartbeat timeout
    (worker crashed mid-task) back to `eligible`."""
    cutoff = datetime.now(timezone.utc) - timedelta(
        seconds=settings.claim_heartbeat_timeout_seconds
    )
    tasks = session.execute(
        select(Task).where(
            Task.run_id == run_id,
            Task.status.in_(["claimed", "running"]),
            Task.claimed_at.isnot(None),
            Task.claimed_at < cutoff,
        )
    ).scalars().all()

    reaped = []
    for t in tasks:
        t.status = "eligible"
        t.claimed_by = None
        t.claimed_at = None
        reaped.append(t.id)
    return reaped


def run_is_complete(session: Session, run_id: str) -> bool:
    tasks = session.execute(
        select(Task).where(Task.run_id == run_id)
    ).scalars().all()
    return all(t.status in ("succeeded", "failed", "superseded") for t in tasks)


def run_has_failure(session: Session, run_id: str) -> bool:
    tasks = session.execute(
        select(Task).where(Task.run_id == run_id)
    ).scalars().all()
    return any(t.status in ("failed", "superseded") for t in tasks)
