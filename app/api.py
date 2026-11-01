"""FastAPI app. Endpoints:
  POST /runs                -> upload CSV + question, get a proposed plan back
  GET  /runs/{id}            -> run status + plan
  POST /runs/{id}/approve    -> human approval gate; makes tasks eligible for workers
  GET  /runs/{id}/stream     -> SSE live task status
  GET  /runs/{id}/report     -> final report + faithfulness notes (once complete)
"""
import asyncio
import json
import os
import uuid

from fastapi import FastAPI, HTTPException, UploadFile, File, Form
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select

from app.agents.faithfulness import check_faithfulness
from app.agents.planner import propose_plan
from app.agents.reviewer import review_plan
from app.agents.terminal import write_report
from app.config import settings
from app.dag import DAGValidationError, RAW_DATASET_KEY, validate_dag
from app.db import init_db, session_scope
from app.llm import get_llm_client
from app.models import Artifact, Run, Task

app = FastAPI(title="TaskGraph")

UPLOAD_DIR = os.path.join(settings.storage_dir, "_uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)


@app.on_event("startup")
def _startup():
    init_db()


def _dataset_schema_preview(path: str, max_rows: int = 5) -> str:
    import pandas as pd
    df = pd.read_csv(path, nrows=max_rows)
    return f"columns: {list(df.columns)}\nsample rows:\n{df.head(max_rows).to_string()}"


@app.post("/runs")
async def create_run(question: str = Form(...), file: UploadFile = File(...)):
    dataset_path = os.path.join(UPLOAD_DIR, f"{uuid.uuid4().hex}_{file.filename}")
    with open(dataset_path, "wb") as f:
        f.write(await file.read())

    with session_scope() as session:
        run = Run(dataset_path=dataset_path, question=question, status="pending_plan")
        session.add(run)
        session.flush()
        run_id = run.id

        llm = get_llm_client()
        schema = _dataset_schema_preview(dataset_path)
        try:
            plan = propose_plan(llm, schema, question)
            validated = validate_dag(plan)
        except (ValueError, DAGValidationError) as e:
            run.status = "failed"
            run.reviewer_feedback = f"planning failed: {e}"
            raise HTTPException(status_code=422, detail=str(e))

        review = review_plan(llm, question, plan)
        run.plan_json = plan
        run.reviewer_feedback = review["feedback"]
        run.status = "awaiting_approval" if review["approved"] else "failed"

        if not review["approved"]:
            return {"run_id": run_id, "status": run.status, "plan": plan, "reviewer_feedback": review["feedback"]}

        # Plan-level ids (e.g. "summarize") are only unique within this one
        # plan -- remap them to real, globally-unique row ids so multiple
        # runs can never collide on Task.id (see models.py comment).
        plan_id_to_row_id = {tid: str(uuid.uuid4()) for tid in validated.topological_order}
        for tid in validated.topological_order:
            t = validated.tasks_by_id[tid]
            session.add(Task(
                id=plan_id_to_row_id[tid],
                plan_task_id=tid,
                run_id=run_id, name=t["name"],
                description=t.get("description", ""),
                depends_on=[plan_id_to_row_id[d] for d in t.get("depends_on", [])],
                input_keys=t.get("input_keys", []),
                output_keys=t.get("output_keys", []),
                status="pending",
            ))

        return {"run_id": run_id, "status": run.status, "plan": plan, "reviewer_feedback": review["feedback"]}


@app.get("/runs/{run_id}")
def get_run(run_id: str):
    with session_scope() as session:
        run = session.get(Run, run_id)
        if not run:
            raise HTTPException(status_code=404, detail="run not found")
        tasks = session.execute(select(Task).where(Task.run_id == run_id)).scalars().all()
        return {
            "run_id": run.id,
            "status": run.status,
            "question": run.question,
            "plan": run.plan_json,
            "reviewer_feedback": run.reviewer_feedback,
            "tasks": [
                {"id": t.id, "plan_task_id": t.plan_task_id, "name": t.name,
                 "status": t.status, "error": t.error}
                for t in tasks
            ],
        }


@app.post("/runs/{run_id}/approve")
def approve_run(run_id: str):
    with session_scope() as session:
        run = session.get(Run, run_id)
        if not run:
            raise HTTPException(status_code=404, detail="run not found")
        if run.status != "awaiting_approval":
            raise HTTPException(status_code=409, detail=f"run is '{run.status}', not awaiting approval")
        run.status = "running"
        return {"run_id": run.id, "status": run.status}


@app.get("/runs/{run_id}/stream")
async def stream_run(run_id: str):
    async def event_gen():
        last_snapshot = None
        while True:
            with session_scope() as session:
                run = session.get(Run, run_id)
                if not run:
                    yield f"event: error\ndata: run not found\n\n"
                    return
                tasks = session.execute(select(Task).where(Task.run_id == run_id)).scalars().all()
                all_terminal = bool(tasks) and all(
                    t.status in ("succeeded", "failed", "superseded") for t in tasks
                )
                any_failed = any(t.status in ("failed", "superseded") for t in tasks)
                display_status = run.status
                if run.status == "running" and all_terminal:
                    display_status = "failed" if any_failed else "completed"
                snapshot = {
                    "status": display_status,
                    "tasks": [
                        {"id": t.id, "plan_task_id": t.plan_task_id, "status": t.status}
                        for t in tasks
                    ],
                }
            if snapshot != last_snapshot:
                yield f"data: {json.dumps(snapshot)}\n\n"
                last_snapshot = snapshot
            if snapshot["status"] in ("completed", "failed"):
                return
            await asyncio.sleep(1.0)

    return StreamingResponse(event_gen(), media_type="text/event-stream")


@app.get("/runs/{run_id}/report")
def get_report(run_id: str):
    with session_scope() as session:
        run = session.get(Run, run_id)
        if not run:
            raise HTTPException(status_code=404, detail="run not found")
        tasks = session.execute(select(Task).where(Task.run_id == run_id)).scalars().all()

        if not all(t.status in ("succeeded", "failed", "superseded") for t in tasks):
            return {"status": "not_ready", "run_status": run.status}

        if run.report_text:
            return {
                "status": "ready",
                "report": run.report_text,
                "faithfulness": run.faithfulness_notes,
            }

        artifacts = session.execute(select(Artifact).where(Artifact.run_id == run_id)).scalars().all()
        previews = {a.key: a.preview for a in artifacts}

        llm = get_llm_client()
        report_text = write_report(llm, run.question, previews)
        faithfulness = check_faithfulness(report_text, previews)

        run.report_text = report_text
        run.faithfulness_notes = faithfulness
        any_failed = any(t.status in ("failed", "superseded") for t in tasks)
        run.status = "failed" if any_failed else "completed"

        return {"status": "ready", "report": report_text, "faithfulness": faithfulness}


static_dir = os.path.join(os.path.dirname(__file__), "..", "frontend")
if os.path.isdir(static_dir):
    app.mount("/", StaticFiles(directory=static_dir, html=True), name="frontend")
