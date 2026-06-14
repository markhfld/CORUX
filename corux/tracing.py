"""Pipeline tracing — a timestamped, auditable record of every step and agent call.

For certification we need to show exactly what the pipeline did: which steps ran,
which were skipped, every Claude invocation with its model/effort/token usage, and
wall-clock timing. A `Tracer` collects these events; a `sink` callback lets the web
layer stream them live as they happen.

The active tracer is held in a ContextVar, so deep code (the LLM wrapper) can emit
events without threading a tracer through every function signature. Set it at the
top of whatever runs the pipeline; calls with no tracer set are silent no-ops.
"""

from __future__ import annotations

import contextvars
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Callable, Optional

_current: contextvars.ContextVar[Optional["Tracer"]] = contextvars.ContextVar(
    "corux_tracer", default=None
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class Tracer:
    """Collects trace events; optionally forwards each to a live sink."""

    def __init__(self, sink: Optional[Callable[[dict], None]] = None):
        self.events: list[dict] = []
        self.sink = sink

    def event(self, type: str, **fields) -> dict:
        ev = {"seq": len(self.events) + 1, "type": type, "ts": _now_iso(), **fields}
        self.events.append(ev)
        if self.sink:
            try:
                self.sink(ev)
            except Exception:
                pass  # never let a trace sink break the pipeline
        return ev


def set(tracer: Optional[Tracer]) -> contextvars.Token:
    return _current.set(tracer)


def reset(token: contextvars.Token) -> None:
    _current.reset(token)


def get() -> Optional[Tracer]:
    return _current.get()


def emit(type: str, **fields) -> None:
    t = _current.get()
    if t is not None:
        t.event(type, **fields)


@contextmanager
def step(step: str, label: str):
    """Trace a pipeline step: emits started, then completed with a duration."""
    t = _current.get()
    t0 = time.perf_counter()
    if t is not None:
        t.event("step", step=step, label=label, status="started")
    try:
        yield
    finally:
        if t is not None:
            t.event(
                "step",
                step=step,
                label=label,
                status="completed",
                duration_ms=round((time.perf_counter() - t0) * 1000),
            )


def skipped(step: str, label: str, reason: str) -> None:
    emit("step", step=step, label=label, status="skipped", reason=reason)
