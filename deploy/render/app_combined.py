"""Collapsed single-process variant for the free Render demo.

This is NOT a different implementation — it imports the exact same
app.dag / app.orchestrator / app.worker / app.agents modules used by the
Docker Compose services. The only difference is process topology: because
Render's free tier doesn't offer a separate free background-worker service,
the orchestrator and worker loops run as asyncio background tasks inside
the single FastAPI process instead of as separate containers.

See README.md "Deployment topologies" for why.
"""
import asyncio
import logging
import threading

from sqlalchemy import select

from app import orchestrator
from app.api import app  # reuse every route as-is
from app.db import session_scope
from app.models import Run
from app.worker import run_worker_loop

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("taskgraph.render_combined")

_stop_event = threading.Event()


def _active_runs_provider():
    with session_scope() as session:
        runs = session.execute(select(Run).where(Run.status == "running")).scalars().all()
        return [(r.id, r.dataset_path) for r in runs]


async def _orchestrator_background_loop():
    from app.config import settings
    while not _stop_event.is_set():
        with session_scope() as session:
            runs = session.execute(select(Run).where(Run.status == "running")).scalars().all()
            for run in runs:
                orchestrator.compute_eligible_frontier(session, run.id)
                orchestrator.reap_stale_claims(session, run.id)
        await asyncio.sleep(settings.orchestrator_poll_interval_seconds)


@app.on_event("startup")
def _start_background_services():
    # Worker loop runs in a real OS thread (it does blocking subprocess
    # calls in app.sandbox); orchestrator loop runs as an asyncio task
    # inside the same event loop as the API.
    threading.Thread(
        target=run_worker_loop,
        args=(_active_runs_provider, _stop_event),
        daemon=True,
    ).start()
    asyncio.create_task(_orchestrator_background_loop())
    logger.info("orchestrator + worker background loops started in-process")


@app.on_event("shutdown")
def _stop_background_services():
    _stop_event.set()
