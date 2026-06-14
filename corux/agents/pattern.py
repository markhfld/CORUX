"""Tool 4 — assess_pattern (LLM).

Takes a related set of markers — the harmonized cross-panel trajectories plus the
abnormal results from the latest panel — and decides whether they co-occur as a
recognizable clinical pattern worth a STRUCTURED FOLLOW-UP recommendation. This is
the step that turns one marker into a clinical signal. Not a diagnosis.
"""

from __future__ import annotations

import json

from ..llm import parse_structured
from ..schemas import (
    AnalyteTrajectory,
    BaselineResult,
    DeidentifiedPatient,
    PatternResult,
)

SYSTEM = """You are a clinical pattern-recognition assistant supporting a clinician.

You are given (a) harmonized cross-panel trajectories for selected analytes (all \
already converted to a single canonical unit per analyte, so they ARE comparable \
across labs and time) and (b) the abnormal results from the most recent panel.

Decide whether subsets of these markers co-occur as a recognizable clinical \
pattern that warrants structured follow-up (for example, a hepatic/cholestatic \
signal, a metabolic signal, etc.). For each pattern you identify:
- name it, list its member analytes, state whether it is present,
- give a concrete structured follow-up recommendation (e.g. a specific repeat/▸ \
  imaging/referral pathway) with a priority (routine / soon / urgent),
- explain the rationale grounded in the trajectories and values provided.

A single isolated abnormality is usually not a pattern — look for corroborating \
co-occurrence across markers and over time. Base everything on the data given; do \
not invent values. This is decision-support and a follow-up recommendation, NOT a \
diagnosis."""


def run(
    patient: DeidentifiedPatient,
    trajectories: list[AnalyteTrajectory],
    baseline: BaselineResult,
) -> PatternResult:
    traj = [
        {
            "analyte": t.analyte,
            "canonical_unit": t.canonical_unit,
            "classification": t.classification,
            "elevated": t.elevated,
            "series": t.summary,
        }
        for t in trajectories
    ]
    abnormal = [
        {"marker": f.marker, "severity": f.severity.value, "rationale": f.rationale}
        for f in baseline.findings
        if f.severity.value != "Normal"
    ]
    user = (
        f"Patient: age {patient.age_years}, sex {patient.sex or 'unknown'}. "
        f"Notes: {patient.notes or 'none'}.\n\n"
        f"Harmonized cross-panel trajectories (JSON):\n{json.dumps(traj, indent=2, default=str)}\n\n"
        f"Abnormal results in the latest panel:\n{json.dumps(abnormal, indent=2)}\n\n"
        "Identify any clinical pattern(s) worth structured follow-up."
    )
    return parse_structured(
        system=SYSTEM, user=user, schema=PatternResult, step="pattern"
    )
