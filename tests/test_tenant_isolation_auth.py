"""Regression tests for U-001 and U-002: the org-setup Excel import and the
checklist submission endpoints used to run for an unauthenticated caller (or
one that only supplied an `X-User-Email` header), which is how an unbounded
bulk-data injection (U-001) and a cross-tenant checklist write (U-002)
happened. These endpoints must now refuse the request before any handler
logic — never take a JWT-less request past that point.

Integration tests against the real app + DB (read-only: every case here is
rejected before anything is written, so nothing needs cleanup).

    cd backend && python3 -m pytest tests/test_tenant_isolation_auth.py -q
"""
import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.services.auth_service import create_access_token

client = TestClient(create_app())


def _token(email: str = "nobody-in-particular@example.com", org_id=None) -> str:
    payload = {"sub": "999999", "email": email, "role": "Worker"}
    if org_id is not None:
        payload["org_id"] = org_id
    return create_access_token(payload)


# ── U-001: org-setup Excel import ──────────────────────────────────────────────

def test_upload_stream_requires_authentication():
    r = client.post("/api/v1/organisation/setup/upload-stream", files={"file": ("t.xlsx", b"x")})
    assert r.status_code == 401


def test_upload_requires_authentication():
    r = client.post("/api/v1/organisation/setup/upload", files={"file": ("t.xlsx", b"x")})
    assert r.status_code == 401


def test_upload_authenticated_but_no_pending_invite_is_rejected():
    """A real JWT is not enough — the account must have a pending invite.
    Before the fix this ran the import unconditionally regardless of invite."""
    headers = {"Authorization": f"Bearer {_token()}"}
    r = client.post(
        "/api/v1/organisation/setup/upload",
        files={"file": ("t.xlsx", b"not a real workbook")},
        headers=headers,
    )
    assert r.status_code == 403
    assert "pending" in r.json()["detail"].lower()


# ── U-002: checklist submissions ───────────────────────────────────────────────

def test_create_submission_requires_authentication():
    r = client.post("/api/v1/checklists/submissions", json={"checklist_type": "does-not-exist"})
    assert r.status_code == 401


def test_create_submission_ignores_spoofed_identity_headers():
    """Before the fix, an unauthenticated caller's X-User-Email/X-User-Role
    headers (default role: Admin) were trusted as the acting identity."""
    r = client.post(
        "/api/v1/checklists/submissions",
        json={"checklist_type": "does-not-exist"},
        headers={"X-User-Email": "attacker@example.com", "X-User-Role": "Admin"},
    )
    assert r.status_code == 401


def test_submit_submission_requires_authentication():
    r = client.post("/api/v1/checklists/submissions/00000000-0000-0000-0000-000000000000/submit")
    assert r.status_code == 401


def test_validate_submission_with_real_auth_but_wrong_role_is_forbidden_or_not_found():
    """Even with a real JWT, validate_submission must not run the transition
    for a submission that either doesn't resolve for this org (404) or whose
    validator_roles the caller's role does not satisfy (403) — never a bare
    200 from an unrelated caller (U-004)."""
    headers = {"Authorization": f'Bearer {_token(org_id=1)}'}
    r = client.post(
        "/api/v1/checklists/submissions/00000000-0000-0000-0000-000000000000/validate",
        json={"decision": "approved"},
        headers=headers,
    )
    assert r.status_code in (403, 404)
