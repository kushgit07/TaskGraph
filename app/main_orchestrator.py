"""Entrypoint for the `orchestrator` Docker Compose service.

Its only job: for every active run, compute the eligible frontier and
reap stale claims. It never touches the LLM and never executes task code
— that's the worker's job. Kept as its own process/container so it can be
reasoned about, tested, and scaled independently of workers."""
import logging
import time

from sqlalchemy import select

from app import orchestrator
from app.config import settings
from app.db import init_db, session_scope
from app.models import Run

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("taskgraph.orchestrator_service")


def active_run_ids() -> list[str]:
    with session_scope() as session:
        runs = session.execute(
            select(Run).where(Run.status == "running")
        ).scalars().all()
        return [r.id for r in runs]


def main():
    init_db()
    logger.info("orchestrator service starting, poll interval=%.1fs",
                settings.orchestrator_poll_interval_seconds)
    while True:
        for run_id in active_run_ids():
            with session_scope() as session:
                flipped = orchestrator.compute_eligible_frontier(session, run_id)
                reaped = orchestrator.reap_stale_claims(session, run_id)
                if flipped:
                    logger.info("run %s: %d task(s) now eligible", run_id, len(flipped))
                if reaped:
                    logger.warning("run %s: reaped %d stale claim(s)", run_id, len(reaped))
        time.sleep(settings.orchestrator_poll_interval_seconds)


if __name__ == "__main__":
    main()
