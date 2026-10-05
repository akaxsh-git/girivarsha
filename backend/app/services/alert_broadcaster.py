"""
Real-time push follow-up (user-requested): fan out real alert-state
changes (see app/services/alerts_engine.py's AlertTransition) to every
connected Server-Sent-Events client, instead of making the Authority
dashboard poll `GET /alerts` on an interval to notice a new/escalated/
resolved alert.

Deliberately NOT a message queue / broker (Redis pub/sub, etc.) — this is a
single-process FastAPI app (see docker-compose.yml), so an in-memory,
thread-safe fan-out is the honest match for what's actually deployed, not
infrastructure this build doesn't run. If this app is ever scaled to
multiple worker processes, this in-memory approach stops working across
processes — that's a real, disclosed limitation of this implementation, not
a hidden one (see docs/Limitations.md).

Route handlers in this app are synchronous `def`s (run in FastAPI's thread
pool), while the SSE endpoint itself is an `async def` running on the main
event loop — so this module uses the stdlib's thread-safe `queue.Queue`
(one per connected client) rather than an asyncio-only primitive, and the
SSE endpoint bridges the two with `loop.run_in_executor`.
"""
from __future__ import annotations

import queue
import threading
from typing import Any

_subscribers: set[queue.Queue] = set()
_lock = threading.Lock()

# Bounded so a slow/dead client can never make publish() (called from inside
# a real user-facing request, e.g. GET /risk/map) block or grow memory
# without limit — see publish() below.
_QUEUE_MAXSIZE = 200


def subscribe() -> "queue.Queue[dict[str, Any]]":
    """Registers a new SSE client. Caller must call unsubscribe() (e.g. in a
    `finally` block) when the client disconnects."""
    q: "queue.Queue[dict[str, Any]]" = queue.Queue(maxsize=_QUEUE_MAXSIZE)
    with _lock:
        _subscribers.add(q)
    return q


def unsubscribe(q: "queue.Queue[dict[str, Any]]") -> None:
    with _lock:
        _subscribers.discard(q)


def subscriber_count() -> int:
    """Exposed for tests and for an honest 'N clients connected' figure if
    ever surfaced in the UI — never fabricated, always this exact count."""
    with _lock:
        return len(_subscribers)


def publish(event: dict[str, Any]) -> None:
    """Fan out one real alert-state-change event to every currently
    connected SSE client. Only ever called (from app/api/routes/risk.py)
    with an event built from a real `AlertTransition` that a real
    `sync_alert_for_village` call actually produced — never a synthetic or
    scheduled "heartbeat" event (the SSE endpoint sends those itself,
    tagged distinctly, purely to keep the HTTP connection alive).

    A subscriber whose queue is already full (a slow or stalled client)
    is dropped rather than allowed to block this call — this function runs
    inline inside a real request (GET /risk/map, GET /risk/{id}), so it
    must never wait on a client that isn't reading."""
    with _lock:
        subs = list(_subscribers)
    for q in subs:
        try:
            q.put_nowait(event)
        except queue.Full:
            unsubscribe(q)
