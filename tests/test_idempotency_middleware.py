"""Regression tests for U-010: the mobile offline queue replays a write when
it loses the response to a request the server already committed, so a second,
identical POST must return the first attempt's cached response rather than
executing the handler again.

Integration test against the real DB (idempotency_keys table, migration 086).
Cleans up every row it inserts.

    cd backend && python3 -m pytest tests/test_idempotency_middleware.py -q
"""
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.config.database import SessionLocal
from app.core.idempotency import IdempotencyMiddleware
from app.services.auth_service import create_access_token

KEY_PREFIX = "pytest-idempotency-"


def _cleanup():
    db = SessionLocal()
    try:
        db.execute(text("DELETE FROM idempotency_keys WHERE idempotency_key LIKE :p"), {"p": f"{KEY_PREFIX}%"})
        db.commit()
    finally:
        db.close()


def _make_app():
    app = FastAPI()
    app.add_middleware(IdempotencyMiddleware)
    calls = {"n": 0}

    @app.post("/echo")
    def echo():
        calls["n"] += 1
        return {"call_count": calls["n"]}

    return app, calls


def test_replay_with_same_key_returns_cached_response_and_does_not_rerun_handler():
    _cleanup()
    app, calls = _make_app()
    client = TestClient(app)
    token = create_access_token({"sub": "1", "email": "x@example.com", "role": "Worker", "org_id": 1})
    headers = {"Authorization": f"Bearer {token}", "X-Idempotency-Key": f"{KEY_PREFIX}same"}

    try:
        r1 = client.post("/echo", json={}, headers=headers)
        r2 = client.post("/echo", json={}, headers=headers)

        assert r1.status_code == r2.status_code == 200
        assert r1.json() == r2.json() == {"call_count": 1}
        assert calls["n"] == 1, "handler must not run twice for the same idempotency key"
    finally:
        _cleanup()


def test_different_key_runs_the_handler_again():
    _cleanup()
    app, calls = _make_app()
    client = TestClient(app)
    token = create_access_token({"sub": "1", "email": "x@example.com", "role": "Worker", "org_id": 1})

    try:
        r1 = client.post("/echo", json={}, headers={
            "Authorization": f"Bearer {token}", "X-Idempotency-Key": f"{KEY_PREFIX}a",
        })
        r2 = client.post("/echo", json={}, headers={
            "Authorization": f"Bearer {token}", "X-Idempotency-Key": f"{KEY_PREFIX}b",
        })

        assert r1.json() == {"call_count": 1}
        assert r2.json() == {"call_count": 2}
        assert calls["n"] == 2
    finally:
        _cleanup()


def test_no_key_header_is_a_pure_passthrough():
    app, calls = _make_app()
    client = TestClient(app)
    token = create_access_token({"sub": "1", "email": "x@example.com", "role": "Worker", "org_id": 1})
    headers = {"Authorization": f"Bearer {token}"}

    r1 = client.post("/echo", json={}, headers=headers)
    r2 = client.post("/echo", json={}, headers=headers)

    assert r1.json() == {"call_count": 1}
    assert r2.json() == {"call_count": 2}, "without the header every call must run normally"
