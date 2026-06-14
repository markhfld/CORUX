"""Step 4 — Compare baseline (agent).

Deterministic math computes each result's position vs its in-report reference
range (qualitative/censored values are marked accordingly); then ONE batched
Claude call classifies every result as Normal / Abnormal / Critical / Dangerous
with a short rationale. Batching keeps this to a single request regardless of
result count.
"""

from __future__ import annotations

import json
from typing import Optional, Union

from ..llm import parse_structured
from ..schemas import BaselineResult, DeidentifiedPatient, Panel

SYSTEM = """You are a clinical laboratory interpretation assistant supporting a \
clinician. For each result you are given its value, unit, in-report reference \
range, the lab's own flag, whether it is a derived/calculated value, and a \
deterministically computed position (below / within / above / qualitative / \
unknown). Values may be numeric or qualitative (e.g. 'negative', '>90').

Classify each result's severity:
- Normal: within reference range, no concern.
- Abnormal: outside range but not immediately concerning.
- Critical: markedly outside range; warrants prompt clinical attention.
- Dangerous: at a level associated with imminent risk; warrants urgent action.

Use the patient's age, sex, any clinical notes, and the panel context. Account \
for the lab's unit system (conventional vs SI) when reasoning about magnitudes. \
Treat derived values as calculated estimates. Keep each rationale to one or two \
sentences. Do not invent reference ranges you were not given. This is \
decision-support, not a diagnosis."""


def _position(
    value: Optional[Union[float, str]], low: Optional[float], high: Optional[float]
) -> str:
    if value is None:
        return "unknown"
    if not isinstance(value, (int, float)):
        return "qualitative"
    if low is not None and value < low:
        return "below"
    if high is not None and value > high:
        return "above"
    if low is None and high is None:
        return "unknown"
    return "within"


def run(patient: DeidentifiedPatient, latest: Panel) -> BaselineResult:
    rows = []
    for r in latest.results:
        rows.append(
            {
                "marker": r.name,
                "loinc": r.loinc,
                "value": r.value,
                "unit": r.unit,
                "ref_low": r.ref_low,
                "ref_high": r.ref_high,
                "ref_note": r.ref_note,
                "lab_flag": r.flag,
                "derived": r.derived,
                "position": _position(r.value, r.ref_low, r.ref_high),
            }
        )

    lab = latest.source_lab
    user = (
        f"Patient: age {patient.age_years}, sex {patient.sex or 'unknown'}.\n"
        f"Clinical notes: {patient.notes or 'none'}.\n"
        f"Lab: {lab.name or 'unknown'} ({lab.country or '??'}), "
        f"unit system {lab.unit_system or 'unknown'}, collected {latest.collected_date or 'unknown'}.\n"
        f"Panel context: {latest.context or 'none'}.\n\n"
        f"Results (JSON):\n{json.dumps(rows, indent=2, default=str)}\n\n"
        "Classify every result. Return one finding per result."
    )
    return parse_structured(
        system=SYSTEM, user=user, schema=BaselineResult, step="baseline"
    )
