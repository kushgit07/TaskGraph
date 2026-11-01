"""Entrypoint for the `worker` Docker Compose service. Stateless aside from
a generated worker_id — this is what `docker compose up --scale worker=N`
scales independently of the api/orchestrator services."""
import logging

from sqlalchemy import select

from app.db import init_db, session_scope
from app.models import Run
from app.worker import run_worker_loop

logging.basicConfig(level=logging.INFO)


def active_runs_provider():
    with session_scope() as session:
        runs = session.execute(
            select(Run).where(Run.status == "running")
        ).scalars().all()
        return [(r.id, r.dataset_path) for r in runs]


if __name__ == "__main__":
    init_db()
    run_worker_loop(active_runs_provider)
