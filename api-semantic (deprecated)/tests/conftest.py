import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from oracle_tutor_api.api import app
from oracle_tutor_api.database import Base, get_db
from oracle_tutor_api.models import Card

# Use an in-memory SQLite database for fast unit tests?
# NO. SQLite cannot handle pgvector types easily.
# We must use the real Postgres DB but maybe a separate test database?
# For simplicity in this environment, we will use the MAIN DB but rollback changes.

from oracle_tutor_api.database import engine, SessionLocal

@pytest.fixture(scope="module")
def test_db():
    # Create a new session for testing
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@pytest.fixture(scope="module")
def client():
    # Override the get_db dependency to use our test session logic if needed
    # For integration tests, the default is fine
    with TestClient(app) as c:
        yield c
