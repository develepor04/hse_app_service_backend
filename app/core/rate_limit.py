"""Minimal in-process rate limiter (U-032).

No Redis or other shared store exists in this stack yet, so this is a
per-process in-memory sliding window — correct for a single uvicorn worker,
but each worker process (or each instance behind a load balancer) keeps its
own counters. Good enough to close a simple email-enumeration probe on
/organisation/setup/check; a real distributed limiter is a bigger call than
this fix warrants (see media_storage.py's note on the same tradeoff for S3).
"""
import time
from collections import defaultdict
from threading import Lock

from fastapi import HTTPException, Request, status

_hits: dict[str, list[float]] = defaultdict(list)
_lock = Lock()


def rate_limit(key_prefix: str, max_requests: int, window_seconds: int):
    """FastAPI dependency factory: `Depends(rate_limit("setup-check", 10, 60))`."""

    def _dep(request: Request) -> None:
        client_ip = request.client.host if request.client else "unknown"
        key = f"{key_prefix}:{client_ip}"
        now = time.monotonic()
        cutoff = now - window_seconds

        with _lock:
            hits = [t for t in _hits[key] if t > cutoff]
            if len(hits) >= max_requests:
                _hits[key] = hits
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail="Too many requests — try again shortly.",
                )
            hits.append(now)
            _hits[key] = hits

    return _dep
