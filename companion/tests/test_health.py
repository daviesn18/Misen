"""Phase 0 acceptance: the service starts and reports its own health honestly."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health_returns_200() -> None:
    response = client.get("/health")
    assert response.status_code == 200


def test_health_reports_service_and_version() -> None:
    body = client.get("/health").json()
    assert body["status"] == "ok"
    assert body["service"] == "companion"
    assert body["version"]


def test_health_checks_the_database() -> None:
    """The database check must actually run — a healthcheck that reports ok
    without touching anything is what we are specifically avoiding."""
    body = client.get("/health").json()
    assert body["checks"]["database"] == "ok"


def test_health_needs_no_auth() -> None:
    """Caddy and the compose healthcheck both call this unauthenticated."""
    response = client.get("/health", headers={})
    assert response.status_code == 200
