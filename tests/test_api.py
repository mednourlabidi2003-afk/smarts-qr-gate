from __future__ import annotations

import importlib

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(tmp_path, monkeypatch):
    db_path = tmp_path / "api.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite+pysqlite:///{db_path.as_posix()}")
    monkeypatch.setenv("AUTO_SEED", "true")
    monkeypatch.setenv("APP_NAME", "SMARTS QR Gate Test")

    import app.main as app_main

    app_main = importlib.reload(app_main)
    with TestClient(app_main.app) as test_client:
        yield test_client

    app_main.engine.dispose()


def test_validate_ticket_endpoint_opens_gate_for_active_ticket(client: TestClient) -> None:
    response = client.post("/api/validate-ticket", json={"ticket_code": "SMARTSDEMO1"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["access_granted"] is True
    assert payload["gate_status"] == "OPEN"


def test_validate_ticket_endpoint_denies_future_ticket(client: TestClient) -> None:
    response = client.post("/api/validate-ticket", json={"ticket_code": "SMARTSDEMO2"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["access_granted"] is False
    assert payload["reason"] == "booking_not_started"
