"""Central configuration: model, per-step effort, storage location."""

from __future__ import annotations

import os
from pathlib import Path

# Default model for every agent. Adaptive thinking is set in llm.py.
MODEL = os.environ.get("CORUX_MODEL", "claude-opus-4-8")

# Effort per pipeline step. Reasoning-heavy steps get more; the mechanical
# baseline classifier gets less. Tune freely — see claude-api effort guidance.
EFFORT = {
    "baseline": "medium",
    "cross_marker_overview": "high",  # Pass A: holistic read of the whole panel
    "cross_marker": "high",           # Pass B: marker-by-marker resonance
    "longitudinal": "high",
    "pattern": "high",
    "literature": "high",
    "orchestrator": "high",
}

# max_tokens per agent call. Generous defaults; orchestrator gets the most room.
MAX_TOKENS = {
    "baseline": 8000,
    "cross_marker_overview": 4000,
    "cross_marker": 8000,
    "longitudinal": 6000,
    "pattern": 8000,
    "literature": 8000,
    "orchestrator": 12000,
}

# Where per-patient longitudinal records are persisted (PHI — git-ignored).
STORE_DIR = Path(
    os.environ.get(
        "CORUX_STORE_DIR",
        str(Path(__file__).resolve().parent.parent / "data" / "store"),
    )
)

# Salt for patient_key hashing. Override in the environment for real deployments
# so keys are not reproducible from public data alone.
PATIENT_KEY_SALT = os.environ.get("CORUX_PATIENT_SALT", "corux-dev-salt")
