"""Tests run against a real MongoDB (transactions and vector search can't be
faked well), using a separate "counterpart_test" database.

After the tests, the documents are deleted but the database is kept, so the
vector index (which takes ~30s to build) survives between runs."""

import os

import pytest
from dotenv import load_dotenv
from fastapi.testclient import TestClient
from pymongo import MongoClient

from scripts.create_vector_index import ensure_vector_index

load_dotenv()
TEST_DB = "counterpart_test"
os.environ["MONGODB_DB"] = TEST_DB  # must be set before the app connects


@pytest.fixture(scope="session")
def client():
    uri = os.getenv("MONGODB_URI", "")
    if not uri.startswith("mongodb") or "<" in uri:
        pytest.skip("Set a real MONGODB_URI in server/.env to run the tests")

    db = MongoClient(uri)[TEST_DB]
    ensure_vector_index(db)

    from app.main import app

    with TestClient(app) as test_client:  # "with" runs the startup/shutdown hooks
        yield test_client

    for name in ["counterparts", "traits", "evidence", "sessions", "debriefs"]:
        db[name].delete_many({})


@pytest.fixture
def counterpart(client):
    """A fresh counterpart with two traits, for tests that need one."""
    res = client.post(
        "/api/counterparts",
        json={
            "name": "Test Person",
            "role": "Landlord",
            "scenario": "Rent negotiation",
            "traits": {
                "conflict_response": {"claim": "Goes quiet when annoyed", "confidence": 0.9},
                "conversation_style": "Answers questions with questions",
            },
        },
    )
    assert res.status_code == 201
    return res.json()["counterpart"]
