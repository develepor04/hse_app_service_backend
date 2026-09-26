"""Where uploaded evidence photos live.

Files go to disk under `backend/uploads/<subdir>/`, and what gets stored on the
record is the URL path, not the bytes. Two reasons: `evidence_json` is a JSON
column read by the mobile app and the website, so a base64 blob there would bloat
every row and every list query that selects it; and a path can be served
directly by the static mount without loading the image into Python.

Deliberately local-disk rather than S3/Azure: nothing else in this codebase talks
to object storage yet, and adding a cloud dependency for a feature the client has
not asked to host remotely would be a bigger decision than this change warrants.
The one function below is the seam to change if that day comes.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import re
import time
import uuid
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# backend/uploads — sibling of app/, outside the package so a redeploy that
# replaces the code does not wipe the evidence.
UPLOAD_ROOT = Path(__file__).resolve().parent.parent.parent / "uploads"

# The public prefix these are served under.
URL_PREFIX = "/uploads"

# ── U-020: evidence used to be served from this prefix with no auth at all —
# a leaked/guessed URL was indefinite, unlogged access to incident photos and
# other evidence. `<img>`/`<Image>` tags across the web and mobile apps render
# these by plain `src`/`uri`, with no custom headers, so gating the route
# behind a Bearer token would break every existing evidence thumbnail. A
# signed URL keeps that unchanged (the signature travels in the query string)
# while making the path space unguessable — a leaked/enumerated UUID alone is
# no longer enough, only the server can mint a URL that verifies.
DEFAULT_SIGNATURE_TTL_SECONDS = 2 * 365 * 24 * 3600  # long-lived: the value is
# persisted once in evidence_json and reused unchanged on every later read,
# not re-signed per request — see sign_path()'s docstring.


def _signing_key() -> bytes:
    from app.config.settings import get_settings

    return get_settings().jwt_secret.encode("utf-8")


def sign_path(path: str, ttl_seconds: int = DEFAULT_SIGNATURE_TTL_SECONDS) -> str:
    """Append `exp`/`sig` query params so `serve_upload` can verify this
    exact path+expiry was minted by this server, not guessed or enumerated.

    Called once, when the URL is first stored on a record (see `save_image`
    below) — not regenerated per API response, so a stored URL keeps working
    unchanged for every later read. That is why the default TTL is long
    (~2 years) rather than the minutes a per-request signed URL would use.
    """
    exp = int(time.time()) + ttl_seconds
    sig = hmac.new(_signing_key(), f"{path}:{exp}".encode("utf-8"), hashlib.sha256).hexdigest()
    return f"{path}?exp={exp}&sig={sig}"


def verify_signed_path(path: str, exp: str, sig: str) -> bool:
    try:
        exp_int = int(exp)
    except (TypeError, ValueError):
        return False
    if exp_int < int(time.time()):
        return False
    expected = hmac.new(_signing_key(), f"{path}:{exp_int}".encode("utf-8"), hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, sig or "")

# Evidence photos and videos.
ALLOWED_CONTENT_TYPES = {
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/png": ".png",
    "image/heic": ".heic",
    "image/heif": ".heif",
    "image/webp": ".webp",
    "video/mp4": ".mp4",
    "video/quicktime": ".mov",
    "video/webm": ".webm",
    "video/3gpp": ".3gp",
    "video/mpeg": ".mpeg",
    "video/x-msvideo": ".avi",
}

MAX_BYTES = 100 * 1024 * 1024  # 100 MB — accommodates video recordings


class MediaRejected(ValueError):
    """The upload was refused. The caller turns this into a 400."""


# CAPA evidence is not only photographs. A procedure change is evidenced by the
# revised document, a training action by the training record, a test by its
# report — so the document formats are allowed alongside the media ones, and
# only for that upload path. Deliberately no archives and nothing executable:
# the allow-list is the whole defence, so it stays boring.
DOCUMENT_CONTENT_TYPES = {
    "application/pdf": ".pdf",
    "application/msword": ".doc",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    "application/vnd.ms-excel": ".xls",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
    "text/csv": ".csv",
    "text/plain": ".txt",
}

EVIDENCE_CONTENT_TYPES = {**ALLOWED_CONTENT_TYPES, **DOCUMENT_CONTENT_TYPES}


def _safe_extension(
    filename: Optional[str],
    content_type: Optional[str],
    allowed: Optional[dict] = None,
) -> str:
    """Pick the extension from the declared type, never from the filename.

    The filename arrives from the device and is attacker-controlled in the
    general case; deriving the extension from it is how you end up writing
    `evidence.php`. The content type is checked against a fixed allow-list, so
    the extension can only ever be one of a handful of known-safe values.
    """
    allowed = allowed if allowed is not None else ALLOWED_CONTENT_TYPES
    if content_type:
        ext = allowed.get(content_type.split(";")[0].strip().lower())
        if ext:
            return ext
    # Fall back to the filename's suffix only if it is itself on the allow-list.
    if filename:
        suffix = Path(filename).suffix.lower()
        if suffix in set(allowed.values()):
            return suffix
    raise MediaRejected(
        f"Unsupported media type '{content_type or filename or 'unknown'}'. "
        f"Allowed: {', '.join(sorted(set(allowed)))}"
    )


def save_image(
    content: bytes,
    filename: Optional[str],
    content_type: Optional[str],
    subdir: str = "incidents",
    allowed_types: Optional[dict] = None,
) -> str:
    """Write one media file and return the URL path to store on the record.

    The stored name is a fresh uuid: the device's filename is discarded entirely,
    so two workers photographing/videoing the same thing cannot collide and nothing
    user-supplied reaches the filesystem.

    `allowed_types` widens the allow-list for callers that legitimately accept
    more than photos — CAPA evidence, which includes documents. It defaults to
    the media-only list, so no existing caller changes behaviour.
    """
    if not content:
        raise MediaRejected("Empty file")
    if len(content) > MAX_BYTES:
        raise MediaRejected(
            f"File is {len(content) // (1024 * 1024)} MB; the limit is {MAX_BYTES // (1024 * 1024)} MB"
        )

    ext = _safe_extension(filename, content_type, allowed_types)

    # Constrain the subdir to a plain word so a caller can never traverse out of
    # UPLOAD_ROOT with something like "../../etc".
    safe_subdir = re.sub(r"[^a-z0-9_]", "", (subdir or "misc").lower()) or "misc"

    target_dir = UPLOAD_ROOT / safe_subdir
    target_dir.mkdir(parents=True, exist_ok=True)

    name = f"{uuid.uuid4().hex}{ext}"
    (target_dir / name).write_bytes(content)

    url = sign_path(f"{URL_PREFIX}/{safe_subdir}/{name}")
    logger.info("Stored evidence media %s (%s bytes)", url, len(content))
    return url
