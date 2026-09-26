"""Reading a worker report that may arrive with evidence files attached.

The mobile app posts a report one of two ways. With nothing attached it sends
plain JSON, which is cheap and is what most reports are. As soon as the worker
attaches a photo or a video it switches to multipart: a `data` part holding the
same JSON, and one part per file.

This module is the single reader for that pair. It exists because the two
handlers that needed it had already drifted — `/worker/incidents` grew a private
`_body_and_photos` and learned to accept multipart, while the three
factory-built families (near miss, unsafe act, risk) kept a JSON-only Pydantic
signature. The consequence was not a lost photo but a rejected report: FastAPI
saw a multipart body where a model was declared and answered 422, so attaching a
photo to a near miss failed the whole submission.

**File parts are named `media_0..n`, or `photo_0..n`.** `photo_` is the older
name and every released build of the app still sends it, so it is accepted
unchanged. `media_` is the name to use going forward, because the files are no
longer only photographs — `media_storage.ALLOWED_CONTENT_TYPES` has accepted
video since it was written, and the capture UI now offers it.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Tuple

from fastapi import HTTPException, Request

from app.services import media_storage

# Ordered so a mixed body still reads left to right within each group. The two
# prefixes are equivalent; see the module docstring for why both exist.
_FILE_PREFIXES = ("media_", "photo_")


async def read_report_body(request: Request, subdir: str = "incidents") -> Tuple[Dict[str, Any], List[str]]:
    """Return `(report dict, URLs of any files written to disk)`.

    A JSON request yields an empty URL list and touches no storage. `subdir`
    picks the folder under `uploads/` so one family's evidence is not mixed in
    with another's.
    """
    content_type = (request.headers.get("content-type") or "").lower()

    if not content_type.startswith("multipart/form-data"):
        payload = await request.json()
        # `/worker/incidents` has always accepted both a bare body and one
        # wrapped in `data`. Kept, because released builds send both shapes.
        return payload.get("data", payload), []

    form = await request.form()

    raw = form.get("data")
    try:
        data = json.loads(raw) if isinstance(raw, str) else (raw or {})
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail=f"`data` is not valid JSON: {exc}")
    if not isinstance(data, dict):
        raise HTTPException(status_code=400, detail="`data` must be a JSON object")

    keys = sorted(
        (k for k in form.keys() if k.startswith(_FILE_PREFIXES)),
        key=_part_order,
    )

    urls: List[str] = []
    for key in keys:
        upload = form[key]
        if not hasattr(upload, "read"):
            continue
        try:
            urls.append(
                media_storage.save_image(
                    await upload.read(),
                    getattr(upload, "filename", None),
                    getattr(upload, "content_type", None),
                    subdir=subdir,
                )
            )
        except media_storage.MediaRejected as exc:
            raise HTTPException(status_code=400, detail=str(exc))

    return data, urls


def _part_order(key: str) -> tuple:
    """Sort `media_2` after `media_10`'s neighbours correctly, not lexically.

    Plain string sort puts `photo_10` between `photo_1` and `photo_2`, which
    silently reorders a worker's evidence once they attach more than ten files.
    """
    prefix, _, index = key.partition("_")
    try:
        return (prefix, int(index))
    except ValueError:
        return (prefix, 1 << 30)


def merge_media(data: Dict[str, Any], urls: List[str]) -> Dict[str, Any]:
    """Fold uploaded file URLs into the report's `photos` list.

    Appends rather than replaces: a client may legitimately send URLs for
    evidence it uploaded earlier alongside new files in the same request.
    """
    if not urls:
        return data
    existing = data.get("photos") or []
    if not isinstance(existing, list):
        existing = [existing]
    data["photos"] = [*existing, *urls]
    return data
