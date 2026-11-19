"""
conftest.py  —  shared fixtures for SmartInventory tests

Two modes:
  1. Unit (default, no DB needed)   — uses monkeypatch to mock query/execute
  2. Integration (needs Postgres)   — set TEST_DATABASE_URL env var

Run unit tests only:
    pytest tests/ -m "not integration"

Run all (needs live DB):
    TEST_DATABASE_URL=postgresql://postgres:postgres@localhost:5432/smartinventory_test pytest tests/
"""

import os
import sys
import pytest

# Make sure the project root is on the path so `api.main` imports cleanly
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fastapi.testclient import TestClient


# ── Patch StaticFiles so TestClient doesn't need the dashboard dir ──────────
import unittest.mock as mock

@pytest.fixture(scope="session", autouse=True)
def patch_static_files():
    """Prevent StaticFiles from erroring when dashboard/ dir is absent in tests."""
    with mock.patch("fastapi.staticfiles.StaticFiles.__init__", return_value=None):
        yield


@pytest.fixture(scope="session")
def client():
    from api.main import app
    with TestClient(app) as c:
        yield c


# ── Integration-only DB fixture ──────────────────────────────────────────────

TEST_DSN = os.getenv(
    "TEST_DATABASE_URL",
    "postgresql://postgres:postgres@localhost:5432/smartinventory_test"
)


@pytest.fixture(scope="session")
def test_db():
    """
    Creates a fresh test DB, applies schema, yields a psycopg2 connection,
    then tears down.  Only used by tests marked @pytest.mark.integration.
    """
    import psycopg2

    # Connect to default postgres DB to create/drop the test DB
    admin_conn = psycopg2.connect(
        "postgresql://postgres:postgres@localhost:5432/postgres"
    )
    admin_conn.autocommit = True
    cur = admin_conn.cursor()
    cur.execute("DROP DATABASE IF EXISTS smartinventory_test")
    cur.execute("CREATE DATABASE smartinventory_test")
    cur.close()
    admin_conn.close()

    # Apply schema
    schema_path = os.path.join(os.path.dirname(__file__), "..", "db", "schema.sql")
    conn = psycopg2.connect(TEST_DSN)
    conn.autocommit = True
    with open(schema_path) as f:
        conn.cursor().execute(f.read())

    yield conn

    conn.close()

    # Drop test DB
    admin_conn = psycopg2.connect(
        "postgresql://postgres:postgres@localhost:5432/postgres"
    )
    admin_conn.autocommit = True
    admin_conn.cursor().execute("DROP DATABASE IF EXISTS smartinventory_test")
    admin_conn.close()
