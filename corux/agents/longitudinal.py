"""Step 6 — Compare visits (agent, conditional).

Runs only when the patient has >= 2 visits. Reasons over the per-marker time
series to describe deltas, trend direction, rate of change, and — the core thesis
— risk trajectory rather than a single-snapshot read.
"""

from __future__ import annotations

import json

from ..llm import parse_structured
from ..schemas import DeidentifiedPatient, LongitudinalResult

SYSTEM = """You are a longitudinal lab-trend analyst supporting a clinician.

You receive a per-marker time series across multiple visits (each point carries a \
date, value, unit, and unit_system). For each marker with enough points, describe \
the direction (rising / falling / stable / unclear), summarize the change in plain \
language, and characterise the risk trajectory — where the trend is heading and \
how fast — not just the latest value. Then give an overall trajectory across the \
panel.

Critical: values may be numeric or qualitative (e.g. 'negative'), and points may \
come from different unit systems (conventional vs SI). Do NOT compare values \
across different units/unit_systems as if they were on the same scale — if a \
marker's points mix unit systems, say the trend cannot be assessed without \
conversion rather than inventing one. Ground every statement in the series \
provided; do not fabricate values."""


def run(
    patient: DeidentifiedPatient, series: dict[str, list[dict]], visits: int
) -> LongitudinalResult:
    # Only include markers with >= 2 numeric time points (qualitative-only series
    # have no trend to compute).
    def _numeric_points(pts):
        return [p for p in pts if isinstance(p.get("value"), (int, float))]

    multi = {k: v for k, v in series.items() if len(_numeric_points(v)) >= 2}
    user = (
        f"Patient: age {patient.age_years}, sex {patient.sex or 'unknown'}.\n"
        f"Visits on record: {visits}.\n\n"
        f"Per-marker series (JSON):\n{json.dumps(multi, indent=2, default=str)}\n\n"
        "Analyze trends and risk trajectory."
    )
    return parse_structured(
        system=SYSTEM, user=user, schema=LongitudinalResult, step="longitudinal"
    )
