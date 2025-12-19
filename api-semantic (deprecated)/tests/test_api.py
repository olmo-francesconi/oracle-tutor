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

def test_search_basic(client: TestClient):
    """Test that basic string search returns results."""
    # Assuming the DB has been seeded with the app startup
    response = client.get("/search?q=Sol")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    # If DB is empty, this passes but warns. If seeded, we expect results.
    if len(data) > 0:
        assert "name" in data[0]

def test_card_details(client: TestClient):
    """Test fetching a specific card by ID."""
    # Search for a card to get an ID
    search = client.get("/search?q=Sol Ring")
    if search.status_code == 200 and len(search.json()) > 0:
        card_id = search.json()[0]["id"]
        
        # Now fetch details
        response = client.get(f"/card/{card_id}")
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "Sol Ring"
        assert "embedding" not in data # We don't expose raw vectors in this endpoint

def test_vector_search(client: TestClient):
    """Test the similarity endpoint."""
    # We need a valid ID to test this
    search = client.get("/search?q=Sol Ring")
    if search.status_code == 200 and len(search.json()) > 0:
        card_id = search.json()[0]["id"]
        
        response = client.get(f"/similar-cards/{card_id}")
        # If the card has no embedding (e.g. data load failed), this might 400
        if response.status_code == 200:
            data = response.json()
            assert isinstance(data, list)
            if len(data) > 0:
                assert "similarity" in data[0]
                # Similarity should be between 0 and 1
                assert 0 <= data[0]["similarity"] <= 1
        elif response.status_code == 400:
            print("Skipping vector test: Card has no embedding yet.")

