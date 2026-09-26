"""Idempotent replay for mobile offline-queue writes (U-010).

offlineQueue.ts treats "the server never got this" and "the server got it but
the reply was lost" identically — both look like a network failure from the
client, so both get replayed as a fresh POST/PUT/PATCH. Without a server-side
dedup record that replay creates a second incident/permit/checklist row.

This is entirely opt-in: it only ever activates for a request that carries an
`X-Idempotency-Key` header, so every existing caller that does not send one
(the web frontend, curl, tests) behaves exactly as before. Only the mobile
offline queue sends the header.
"""
import logging
from typing import Optional

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

from app.config.database import SessionLocal
from app.services.auth_service import decode_access_token

logger = logging.getLogger(__name__)

_IDEMPOTENT_METHODS = {"POST", "PUT", "PATCH"}
_HEADER = "X-Idempotency-Key"


def _subject_for(request: Request) -> Optional[str]:
    """Scope a key to the caller's own account so one user's key can never
    replay another user's cached response, even by accidental collision."""
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        return None
    payload = decode_access_token(auth.removeprefix("Bearer ").strip())
    if not payload:
        return None
    sub = payload.get("sub")
    return str(sub) if sub else None


class IdempotencyMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        key = request.headers.get(_HEADER)
        if not key or request.method not in _IDEMPOTENT_METHODS:
            return await call_next(request)

        subject = _subject_for(request)
        if not subject:
            # No verifiable identity to scope the key to — fall back to normal
            # handling rather than dedup across unrelated anonymous callers.
            return await call_next(request)

        path = request.url.path
        db = SessionLocal()
        try:
            from sqlalchemy import text

            cached = db.execute(
                text(
                    "SELECT status_code, content_type, response_body FROM idempotency_keys "
                    "WHERE idempotency_key = :k AND request_path = :p AND subject = :s"
                ),
                {"k": key, "p": path, "s": subject},
            ).mappings().first()

            if cached:
                logger.info("Idempotent replay: %s %s key=%s", request.method, path, key)
                return Response(
                    content=cached["response_body"],
                    status_code=cached["status_code"],
                    media_type=cached["content_type"],
                )

            response = await call_next(request)

            # call_next's response is Starlette's internal wrapper, not the
            # route's original JSONResponse — media_type is not set on it,
            # only the header is.
            content_type = (response.headers.get("content-type") or "").split(";")[0].strip()
            if 200 <= response.status_code < 300 and content_type == "application/json":
                body = b""
                async for chunk in response.body_iterator:
                    body += chunk if isinstance(chunk, (bytes, bytearray)) else chunk.encode()

                try:
                    db.execute(
                        text(
                            "INSERT INTO idempotency_keys "
                            "(idempotency_key, request_path, subject, status_code, content_type, response_body) "
                            "VALUES (:k, :p, :s, :sc, :ct, :b)"
                        ),
                        {
                            "k": key, "p": path, "s": subject,
                            "sc": response.status_code, "ct": content_type,
                            "b": body.decode("utf-8", errors="replace"),
                        },
                    )
                    db.commit()
                except Exception:
                    # A duplicate key (concurrent retry) or missing table on an
                    # unmigrated environment must never break the real write —
                    # the response the caller is about to receive already
                    # succeeded regardless of whether it got cached.
                    db.rollback()
                    logger.warning("Could not persist idempotency key %s for %s", key, path, exc_info=True)

                passthrough_headers = {
                    k: v for k, v in response.headers.items()
                    if k.lower() not in ("content-length", "content-type")
                }
                return Response(
                    content=body,
                    status_code=response.status_code,
                    media_type=response.media_type,
                    headers=passthrough_headers,
                )

            return response
        finally:
            db.close()
