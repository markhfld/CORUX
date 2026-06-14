"""Local single-page app for CORUX.

Mimics the analyzer handing its JSON to CORUX: paste/edit the analyzer output in
a JSON editor, click Run, and the full pipeline executes and renders the result.

Run:
    uvicorn corux.webapp:app --reload
    # or
    python -m corux.webapp
"""

from __future__ import annotations

import json
import queue
import threading
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, StreamingResponse
from pydantic import BaseModel

from . import report, tracing
from .pipeline import PipelineResult, run

load_dotenv()  # ANTHROPIC_API_KEY

app = FastAPI(title="CORUX", description="Lab-result interpretation prototype")

_WEB_DIR = Path(__file__).resolve().parent / "web"
_DATA_DIR = Path(__file__).resolve().parent.parent / "data"


class RunRequest(BaseModel):
    input: dict
    literature: bool = False
    persist: bool = False


def _serialize(result: PipelineResult, trace: list[dict] | None = None) -> dict:
    return {
        "patient_key": result.patient.patient_key,
        "visits": result.visits,
        "notes": result.notes,
        "baseline": result.baseline.model_dump(mode="json"),
        "cross_marker": result.cross_marker.model_dump(mode="json"),
        "trajectories": [t.model_dump(mode="json") for t in result.trajectories],
        "pattern": result.pattern.model_dump(mode="json") if result.pattern else None,
        "literature": result.literature.model_dump(mode="json")
        if result.literature
        else None,
        "final": result.final.model_dump(mode="json"),
        "report": report.build(
            result.latest_panel, result.baseline, result.trajectories, result.visits
        ),
        "trace": trace or [],
    }


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return (_WEB_DIR / "index.html").read_text(encoding="utf-8")


@app.get("/api/samples")
def samples() -> list[str]:
    if not _DATA_DIR.exists():
        return []
    return sorted(p.name for p in _DATA_DIR.glob("*.json"))


@app.get("/api/sample/{name}")
def sample(name: str) -> dict:
    # Guard against path traversal; only serve top-level data/*.json files.
    safe = Path(name).name
    path = _DATA_DIR / safe
    if not path.exists() or path.suffix != ".json":
        raise HTTPException(status_code=404, detail="Sample not found")
    return json.loads(path.read_text(encoding="utf-8"))


@app.post("/api/run")
def api_run(req: RunRequest) -> dict:
    # Sync def -> FastAPI runs it in a worker thread, so the long Claude calls
    # don't block the event loop. Non-streaming; trace is included in the result.
    tracer = tracing.Tracer()
    token = tracing.set(tracer)
    try:
        result = run(
            req.input,
            literature_enabled=req.literature,
            persist=req.persist,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:  # surface pipeline/API errors to the UI
        raise HTTPException(status_code=500, detail=f"{type(e).__name__}: {e}")
    finally:
        tracing.reset(token)
    return _serialize(result, tracer.events)


@app.post("/api/run/stream")
def api_run_stream(req: RunRequest) -> StreamingResponse:
    """Run the pipeline in a worker thread, streaming each trace event live as
    Server-Sent Events; the final `result` event carries the full interpretation
    (with the embedded trace for certification records)."""
    q: "queue.Queue[dict | None]" = queue.Queue()

    def worker() -> None:
        tracer = tracing.Tracer(sink=q.put)  # every trace event -> the stream
        token = tracing.set(tracer)
        try:
            result = run(
                req.input,
                literature_enabled=req.literature,
                persist=req.persist,
            )
            q.put({"type": "result", "data": _serialize(result, tracer.events)})
        except ValueError as e:
            q.put({"type": "error", "detail": str(e)})
        except Exception as e:
            q.put({"type": "error", "detail": f"{type(e).__name__}: {e}"})
        finally:
            tracing.reset(token)
            q.put(None)  # sentinel: stream complete

    threading.Thread(target=worker, daemon=True).start()

    def event_stream():
        while True:
            ev = q.get()
            if ev is None:
                break
            yield f"data: {json.dumps(ev)}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def main() -> None:
    import os

    import uvicorn

    port = int(os.environ.get("CORUX_PORT", "8000"))
    uvicorn.run("corux.webapp:app", host="127.0.0.1", port=port, reload=False)


if __name__ == "__main__":
    main()
