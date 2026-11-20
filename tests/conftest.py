import sys
from pathlib import Path

import pytest

SERVER_DIR = Path(__file__).resolve().parent.parent / "server"
sys.path.insert(0, str(SERVER_DIR))

import ap_core  # noqa: E402


@pytest.fixture(autouse=True)
def fresh_db(tmp_path, monkeypatch):
    """Give every test its own freshly seeded database and audit log."""
    monkeypatch.setattr(ap_core, "DB_PATH", tmp_path / "ap_demo.db")
    monkeypatch.setattr(ap_core, "AUDIT_LOG_PATH", tmp_path / "audit.jsonl")
    monkeypatch.setenv("AP_DATA_DIR", str(tmp_path))
    ap_core.reset_database()
    yield tmp_path
