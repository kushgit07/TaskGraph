"""Worker loop: claim an eligible task -> generate scoped code -> run it in
the sandbox -> persist declared outputs as artifacts -> report the result
back to the orchestrator's state machine.

Each worker process is independent and stateless aside from its worker_id;
this is what makes `docker compose up --scale worker=N` safe."""
import logging
import os
import socket
import time
import uuid

from sqlalchemy.orm import Session

from app import orchestrator
from app.agents.coder import generate_task_code
from app.config import settings
from app.llm import get_llm_client
from app.models import Artifact
from app.sandbox import cleanup_sandbox_dir, run_in_sandbox
from app.storage import default_storage

logger = logging.getLogger("taskgraph.worker")


def _worker_id() -> str:
    return f"{socket.gethostname()}-{uuid.uuid4().hex[:8]}"


def _resolve_input_files(session: Session, run_id: str, task, dataset_path: str) -> dict:
    """Map each declared input_key to a real file path the sandbox can
    copy in. 'raw_dataset' resolves to the run's uploaded CSV; anything
    else must be an artifact produced by an earlier task."""
    from app.dag import RAW_DATASET_KEY

    files = {}
    for key in task.input_keys or []:
        if key == RAW_DATASET_KEY:
            files[key] = dataset_path
            continue
        artifact = (
            session.query(Artifact)
            .filter(Artifact.run_id == run_id, Artifact.key == key)
            .order_by(Artifact.created_at.desc())
            .first()
        )
        if artifact is None:
            raise FileNotFoundError(f"artifact '{key}' not found for run {run_id}")
        files[key] = default_storage.resolve(artifact.storage_path)
    return files


def process_one_task(session: Session, run_id: str, dataset_path: str, worker_id: str) -> bool:
    """Claim and execute exactly one eligible task. Returns True if a task
    was processed (regardless of success/failure), False if none available."""
    task = orchestrator.claim_next_task(session, run_id, worker_id)
    if task is None:
        return False

    session.commit()  # release the claim row lock promptly

    orchestrator.start_new_attempt(session, task, worker_id)
    session.commit()

    llm = get_llm_client()
    try:
        code = generate_task_code(llm, {
            "name": task.name,
            "description": task.description,
            "input_keys": task.input_keys,
            "output_keys": task.output_keys,
        })
        task.generated_code = code
        session.commit()

        input_files = _resolve_input_files(session, run_id, task, dataset_path)

        result = run_in_sandbox(
            code=code,
            input_files=input_files,
            expected_output_keys=task.output_keys or [],
            timeout_seconds=settings.task_timeout_seconds,
            memory_mb=settings.task_memory_limit_mb,
        )

        if not result.success:
            orchestrator.record_attempt_result(session, task, success=False, error=result.error)
            session.commit()
            logger.warning(
                "task %s failed: %s\n--- generated code ---\n%s\n--- stderr ---\n%s",
                task.id, result.error, code, result.stderr,
            )
            return True

        for key, path in result.output_files.items():
            storage_path = default_storage.save(run_id, f"{task.id}_{key}", path)
            preview = _make_preview(path)
            session.add(Artifact(
                run_id=run_id, task_id=task.id, key=key,
                storage_path=storage_path, preview=preview,
            ))
        if result.output_files:
            cleanup_sandbox_dir(next(iter(result.output_files.values())))

        orchestrator.record_attempt_result(session, task, success=True)
        session.commit()
        return True

    except Exception as e:  # noqa: BLE001 — a worker must never crash the loop
        logger.exception("unexpected error processing task %s", task.id)
        orchestrator.record_attempt_result(session, task, success=False, error=str(e))
        session.commit()
        return True


def _make_preview(path: str, max_chars: int = 500) -> str:
    try:
        with open(path, "r", errors="replace") as f:
            return f.read(max_chars)
    except Exception:
        return ""


def run_worker_loop(run_id_provider, stop_event=None):
    """`run_id_provider` is a callable returning the set of currently-active
    run ids (and their dataset paths) so one worker process can service
    multiple concurrent runs. Kept generic so both the Docker Compose
    worker service and the collapsed HF Spaces variant can reuse it."""
    from app.db import session_scope

    worker_id = _worker_id()
    logger.info("worker %s starting", worker_id)
    while stop_event is None or not stop_event.is_set():
        did_work = False
        for run_id, dataset_path in run_id_provider():
            with session_scope() as session:
                orchestrator.compute_eligible_frontier(session, run_id)
                orchestrator.reap_stale_claims(session, run_id)
            with session_scope() as session:
                did_work = process_one_task(session, run_id, dataset_path, worker_id) or did_work
        if not did_work:
            time.sleep(settings.worker_poll_interval_seconds)
