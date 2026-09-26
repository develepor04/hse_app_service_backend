"""Domain event bus and the closure cascade.

Importing this package registers every handler — the @subscribe decorators run
at import time, so `handlers` must be imported for the bus to have subscribers.
"""
from app.services.events import handlers  # noqa: F401  (registers subscribers)
from app.services.events.bus import (  # noqa: F401
    HandlerResult, dispatch, publish, publish_and_dispatch, registry, subscribe,
)
from app.services.events.catalogue import CLOSURE_EVENT_FOR  # noqa: F401
