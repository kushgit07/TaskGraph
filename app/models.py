"""ORM models. IDs are string UUIDs (portable across Postgres/SQLite)."""
import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Column, String, Text, DateTime, Integer, ForeignKey, JSON
)
from sqlalchemy.orm import relationship

from app.db import Base


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Run(Base):
    __tablename__ = "runs"

    id = Column(String(36), primary_key=True, default=_uuid)
    dataset_path = Column(String(512), nullable=False)
    question = Column(Text, nullable=False)
    status = Column(String(32), nullable=False, default="pending_plan")
    # pending_plan -> awaiting_approval -> running -> completed | failed
    plan_json = Column(JSON, nullable=True)
    reviewer_feedback = Column(Text, nullable=True)
    report_text = Column(Text, nullable=True)
    faithfulness_notes = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=_now)
    updated_at = Column(DateTime, default=_now, onupdate=_now)

    tasks = relationship("Task", back_populates="run", cascade="all, delete-orphan")


class Task(Base):
    __tablename__ = "tasks"

    id = Column(String(36), primary_key=True, default=_uuid)
    # The planner names tasks with short human ids (e.g. "summarize") that
    # are only unique *within one plan* -- they are NOT safe as a global
    # primary key across runs. plan_task_id keeps the human-readable name
    # for display/debugging; `id` (a real uuid) is the actual PK, and
    # depends_on is remapped to real ids at insertion time (see api.py).
    plan_task_id = Column(String(256), nullable=True)
    run_id = Column(String(36), ForeignKey("runs.id"), nullable=False, index=True)
    name = Column(String(256), nullable=False)
    description = Column(Text, nullable=True)
    depends_on = Column(JSON, nullable=False, default=list)   # list[task_id]
    input_keys = Column(JSON, nullable=False, default=list)   # list[artifact_key]
    output_keys = Column(JSON, nullable=False, default=list)  # list[artifact_key]
    status = Column(String(32), nullable=False, default="pending", index=True)
    # pending -> eligible -> claimed -> running -> succeeded | failed -> superseded
    claimed_by = Column(String(64), nullable=True)
    claimed_at = Column(DateTime, nullable=True)
    attempt_count = Column(Integer, nullable=False, default=0)
    generated_code = Column(Text, nullable=True)
    error = Column(Text, nullable=True)
    created_at = Column(DateTime, default=_now)
    updated_at = Column(DateTime, default=_now, onupdate=_now)

    run = relationship("Run", back_populates="tasks")
    attempts = relationship("TaskAttempt", back_populates="task", cascade="all, delete-orphan")


class TaskAttempt(Base):
    __tablename__ = "task_attempts"

    id = Column(String(36), primary_key=True, default=_uuid)
    task_id = Column(String(36), ForeignKey("tasks.id"), nullable=False, index=True)
    attempt_number = Column(Integer, nullable=False)
    worker_id = Column(String(64), nullable=True)
    status = Column(String(32), nullable=False, default="running")
    error = Column(Text, nullable=True)
    started_at = Column(DateTime, default=_now)
    finished_at = Column(DateTime, nullable=True)

    task = relationship("Task", back_populates="attempts")


class Artifact(Base):
    __tablename__ = "artifacts"

    id = Column(String(36), primary_key=True, default=_uuid)
    run_id = Column(String(36), ForeignKey("runs.id"), nullable=False, index=True)
    task_id = Column(String(36), ForeignKey("tasks.id"), nullable=True)
    key = Column(String(256), nullable=False)
    storage_path = Column(String(512), nullable=False)
    preview = Column(Text, nullable=True)  # short text preview for faithfulness checks / UI
    created_at = Column(DateTime, default=_now)
