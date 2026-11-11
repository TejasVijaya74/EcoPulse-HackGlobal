import os
import shutil
import sys
import tempfile
from pathlib import Path

import pytest

TEST_API_ACCESS_TOKEN = "ecopulse-test-only-api-token-32-characters-minimum"
TEST_FRONTEND_ORIGIN = "https://ecopulse-test.example"
TEST_DATA_DIR = Path(tempfile.mkdtemp(prefix="ecopulse-backend-tests-"))
TEST_MODEL_DIR = TEST_DATA_DIR / "models"

os.environ["API_ACCESS_TOKEN"] = TEST_API_ACCESS_TOKEN
os.environ["DATABASE_URL"] = f"sqlite:///{(TEST_DATA_DIR / 'tests.sqlite3').as_posix()}"
os.environ["CORS_ORIGINS"] = TEST_FRONTEND_ORIGIN

from app import config

config.MODEL_DIR = TEST_MODEL_DIR
TEST_MODEL_DIR.mkdir()


@pytest.fixture
def auth_headers():
    return {"Authorization": f"Bearer {TEST_API_ACCESS_TOKEN}"}


@pytest.fixture(autouse=True)
def clear_rate_limit_windows():
    from sqlalchemy import text

    from app.database import engine
    from app.rate_limits import ensure_rate_limit_storage

    with engine.begin() as connection:
        ensure_rate_limit_storage(connection)
        connection.execute(text("DELETE FROM api_rate_limit_windows"))
    yield


def pytest_sessionfinish(session, exitstatus):
    database = sys.modules.get("app.database")
    if database is not None:
        database.engine.dispose()
    shutil.rmtree(TEST_DATA_DIR, ignore_errors=True)
