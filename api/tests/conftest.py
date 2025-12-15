import pytest
from fastapi.testclient import TestClient

from oracle_tutor_api.main import app


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app)


