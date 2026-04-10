"""Tests for the /health endpoint."""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from engine.main import app


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app)


def test_health_ok(client: TestClient) -> None:
    """Health endpoint returns 200 and expected shape when DB and Redis are reachable."""
    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(return_value=MagicMock())
    mock_redis = AsyncMock()
    mock_redis.ping = AsyncMock(return_value=True)

    with (
        patch("engine.api.health.DbSession", return_value=mock_db),
        patch("engine.api.health.RedisClient", return_value=mock_redis),
    ):
        response = client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert "status" in body
    assert "version" in body
    assert "db_connected" in body
    assert "redis_connected" in body


def test_health_route_exists(client: TestClient) -> None:
    """The /health route is registered on the app."""
    routes = [route.path for route in app.routes]  # type: ignore[attr-defined]
    assert "/health" in routes
