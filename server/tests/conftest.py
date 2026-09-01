"""Tests run against a real MongoDB (transactions can't be faked well), using a
separate "counterpart_test" database that is dropped afterwards."""

import os

import pytest
from dotenv import load_dotenv
from fastapi.testclient import TestClient
from pymongo import MongoClient

load_dotenv()
TEST_DB = "counterpart_test"
os.environ["MONGODB_DB"] = TEST_DB  # must be set before the app connects


@pytest.fixture(scope="session")
def client():
    uri = os.getenv("MONGODB_URI", "")
    if not uri.startswith("mongodb") or "<" in uri:
        pytest.skip("Set a real MONGODB_URI in server/.env to run the tests")

    from app.main import app

    with TestClient(app) as test_client:  # "with" runs the startup/shutdown hooks
        yield test_client

    MongoClient(uri).drop_database(TEST_DB)


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
