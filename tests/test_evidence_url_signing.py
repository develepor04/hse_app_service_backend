"""Regression tests for U-020: evidence used to be served from a plain
StaticFiles mount with no auth at all — any UUID filename, guessed or
leaked, was served to anyone, indefinitely, with no log. save_image() now
signs every URL it hands out, and the serving route rejects anything
unsigned, tampered, or expired.

Pure unit tests for the signing helpers, plus an integration test of the
route against the real app (writes and cleans up one file under uploads/).

    cd backend && python3 -m pytest tests/test_evidence_url_signing.py -q
"""
import time

from fastapi.testclient import TestClient

from app.main import create_app
from app.services import media_storage


def test_sign_and_verify_round_trip():
    url = media_storage.sign_path("/uploads/incidents/abc.jpg")
    path, qs = url.split("?", 1)
    params = dict(p.split("=") for p in qs.split("&"))
    assert media_storage.verify_signed_path(path, params["exp"], params["sig"])


def test_verify_rejects_tampered_signature():
    url = media_storage.sign_path("/uploads/incidents/abc.jpg")
    path, qs = url.split("?", 1)
    params = dict(p.split("=") for p in qs.split("&"))
    assert not media_storage.verify_signed_path(path, params["exp"], "0" * 64)


def test_verify_rejects_wrong_path_with_right_signature():
    """A signature is bound to its exact path — reusing one valid signature
    for a different filename must not verify."""
    url = media_storage.sign_path("/uploads/incidents/abc.jpg")
    path, qs = url.split("?", 1)
    params = dict(p.split("=") for p in qs.split("&"))
    assert not media_storage.verify_signed_path("/uploads/incidents/other.jpg", params["exp"], params["sig"])


def test_verify_rejects_expired_signature():
    url = media_storage.sign_path("/uploads/incidents/abc.jpg", ttl_seconds=-10)
    path, qs = url.split("?", 1)
    params = dict(p.split("=") for p in qs.split("&"))
    assert not media_storage.verify_signed_path(path, params["exp"], params["sig"])


def test_serve_upload_route_end_to_end():
    url = media_storage.save_image(b"pytest-fixture-bytes", "x.jpg", "image/jpeg", subdir="pytest_tmp")
    path, qs = url.split("?", 1)
    params = dict(p.split("=") for p in qs.split("&"))
    file_path = media_storage.UPLOAD_ROOT / "pytest_tmp" / path.rsplit("/", 1)[-1]

    try:
        client = TestClient(create_app())

        r_ok = client.get(path, params=params)
        assert r_ok.status_code == 200
        assert r_ok.content == b"pytest-fixture-bytes"

        r_no_sig = client.get(path)
        assert r_no_sig.status_code == 403

        bad_sig = {**params, "sig": "0" * 64}
        r_bad = client.get(path, params=bad_sig)
        assert r_bad.status_code == 403
    finally:
        file_path.unlink(missing_ok=True)
