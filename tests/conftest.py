import os
import shutil
import tempfile
from pathlib import Path

import pytest


_TEST_ROOT = Path(tempfile.mkdtemp(prefix="kineo_pytest_"))
os.environ["DATABASE_URL"] = f"sqlite:///{_TEST_ROOT / 'kineo_test.db'}"
os.environ["KINEO_ENV"] = "test"
os.environ["KINEO_AUTO_MIGRATE"] = "1"
os.environ["KINEO_BOOTSTRAP_ADMIN_PASSWORD"] = "Teste-Seguro-123!"
os.environ["KINEO_LOG_DIR"] = str(_TEST_ROOT / "logs")

import database  # noqa: E402


@pytest.fixture
def db_session():
    database.Base.metadata.drop_all(bind=database.engine)
    database.Base.metadata.create_all(bind=database.engine)
    session = database.SessionLocal()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


def pytest_sessionfinish(session, exitstatus):
    database.engine.dispose()
    shutil.rmtree(_TEST_ROOT, ignore_errors=True)
