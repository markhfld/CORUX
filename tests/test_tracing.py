from corux import tracing


def test_tracer_collects_events_and_sink():
    seen = []
    tracer = tracing.Tracer(sink=seen.append)
    token = tracing.set(tracer)
    try:
        tracing.emit("pipeline", status="started")
        with tracing.step("ingest", "Ingest signal"):
            pass
        tracing.skipped("literature", "Consult literature (agent)", "disabled")
    finally:
        tracing.reset(token)

    types = [e["type"] for e in tracer.events]
    assert types[0] == "pipeline"
    # step context manager emits started + completed
    statuses = [e.get("status") for e in tracer.events if e["type"] == "step"]
    assert "started" in statuses and "completed" in statuses and "skipped" in statuses
    # sink received the same events; seq numbers are monotonic
    assert len(seen) == len(tracer.events)
    assert [e["seq"] for e in tracer.events] == list(range(1, len(tracer.events) + 1))
    # completed step carries a duration
    completed = next(e for e in tracer.events if e.get("status") == "completed")
    assert "duration_ms" in completed


def test_no_tracer_is_silent_noop():
    # emit / step / skipped must not raise when no tracer is set.
    tracing.emit("llm", step="baseline")
    with tracing.step("x", "X"):
        pass
    tracing.skipped("y", "Y", "reason")
