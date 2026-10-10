"""
Points the app at a throwaway data dir/DB and forces mock mode *before*
anything under app/ is imported, since config.py reads the environment at
import time. This has to happen at conftest module load time (which
pytest does before collecting test modules in this directory), not inside
a fixture.
"""
import os
import sys
import tempfile
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

_tmp_data_dir = Path(tempfile.mkdtemp(prefix="qgs-test-data-"))
os.environ["DATA_DIR"] = str(_tmp_data_dir)
os.environ["DATABASE_URL"] = f"sqlite:///{_tmp_data_dir / 'test.db'}"
os.environ["MOCK_MODE"] = "true"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.db import init_db  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture()
def client():
    init_db()
    with TestClient(app) as c:
        yield c
