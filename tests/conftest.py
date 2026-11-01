import os
import tempfile

# Must happen before any `app.*` module is imported anywhere in the test
# session, since app.config.Settings reads the environment once at import
# time. conftest.py is loaded by pytest before test modules are collected,
# so this is the correct place for it.
_tmp_db = os.path.join(tempfile.mkdtemp(prefix="taskgraph_test_"), "test.db")
os.environ["DATABASE_URL"] = f"sqlite:///{_tmp_db}"
os.environ.setdefault("GROQ_API_KEY", "")  # force mock LLM in tests

import pytest

from app.db import Base, engine, session_scope


@pytest.fixture(autouse=True)
def _fresh_schema():
    """Recreate all tables before every test so tests are isolated from
    each other despite sharing one sqlite file."""
    from app import models  # noqa: F401  register models
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield


@pytest.fixture
def db_session():
    with session_scope() as session:
        yield session
