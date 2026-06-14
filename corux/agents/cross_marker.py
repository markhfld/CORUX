"""Step 5 — Reason across markers (agent), two-pass.

Pass A (holistic): read the entire panel first and form an overview — the overall
story, dominant patterns, and which markers should move together.

Pass B (marker-by-marker): test each marker against that overview. A value that
is extreme but does NOT resonate with the rest of the panel — i.e. the markers
you'd expect to corroborate it are normal — is more likely a measurement /
transcription error than a true result, and is flagged as a data-quality error.

This ordering is deliberate: an overview first, then a deeper per-marker check
against it. Acts as a gate — detected errors flow to the orchestrator.
"""

from __future__ import annotations

import json

from ..llm import parse_structured
from ..schemas import (
    BaselineResult,
    CrossMarkerResult,
    DeidentifiedPatient,
    Panel,
    PanelOverview,
)


def _result_rows(latest: Panel) -> list[dict]:
    return [
        {
            "marker": r.name,
            "loinc": r.loinc,
            "value": r.value,
            "unit": r.unit,
            "ref_low": r.ref_low,
            "ref_high": r.ref_high,
            "flag": r.flag,
            "derived": r.derived,
        }
        for r in latest.results
    ]

OVERVIEW_SYSTEM = """You are a clinical reviewer forming a HOLISTIC read of an \
entire lab panel before judging any single value.

Do not yet flag or classify individual markers. Instead:
- narrative: describe the overall story the dataset tells — what kind of picture \
  this panel paints as a whole.
- dominant_patterns: the main coherent themes across markers.
- expected_correlations: state which markers should move together physiologically \
  and in which direction (e.g. "a very high triglyceride level would usually be \
  accompanied by X and Y; an isolated extreme value without them is suspicious").

Note which results are `derived` (calculated, e.g. eGFR / calc LDL / FIB-4): these \
are formula outputs and can be artefactual when their inputs are extreme. Account \
for the lab's unit system. This overview is the reference frame a second pass will \
use to judge whether each marker resonates with the rest of the panel."""

MARKER_SYSTEM = """You are a clinical data-quality and correlation reviewer doing a \
marker-by-marker pass AGAINST a holistic overview of the panel you are given.

For each notable marker (abnormal, extreme, or critical), judge RESONANCE: does \
its value fit the overall picture, and is it corroborated by the physiologically \
linked markers that should accompany it? Assign one of three verdicts:

- "corroborated": the value fits the panel and is supported by the linked markers \
  you'd expect to move with it. A corroborated value is a REAL finding even when \
  it is Critical or Dangerous — do NOT flag it and do NOT recommend re-testing it.

- "uncorroborated": an extreme/critical value that stands ALONE — the markers that \
  should corroborate it are normal. This is an isolated extreme and is more likely \
  a measurement/transcription error than a true result. Be appropriately \
  aggressive here: add it to `errors` (a likely data error) with confidence and \
  the reasoning (which corroborating markers are missing).

- "ambiguous": partial, weak, or conflicting corroboration — you cannot confidently \
  call it real or erroneous. Do NOT call it an error. Instead add it to \
  `verifications` (recommend a confirmatory re-test before acting), with a reason \
  and confidence.

Decide by corroboration, not by severity alone. A severe value with strong support \
resonates and passes clean; an isolated extreme with no support is suspect; the \
uncertain middle gets a verify recommendation, not an error label.

Set `coherent` to true only if you found no likely errors. Populate `resonance` \
with every notable marker's verdict, `correlations` with the relationships you \
confirmed, `errors` with uncorroborated isolated extremes, and `verifications` \
with ambiguous values worth re-testing."""


def _context(patient: DeidentifiedPatient, latest: Panel) -> str:
    lab = latest.source_lab
    return (
        f"Patient: age {patient.age_years}, sex {patient.sex or 'unknown'}. "
        f"Notes: {patient.notes or 'none'}.\n"
        f"Lab unit system: {lab.unit_system or 'unknown'}. "
        f"Panel context: {latest.context or 'none'}."
    )


def _overview(patient: DeidentifiedPatient, latest: Panel, baseline: BaselineResult) -> PanelOverview:
    markers = _result_rows(latest)
    severities = [
        {"marker": f.marker, "severity": f.severity.value} for f in baseline.findings
    ]
    user = (
        f"{_context(patient, latest)}\n\n"
        f"Full panel (JSON):\n{json.dumps(markers, indent=2, default=str)}\n\n"
        f"Baseline severities:\n{json.dumps(severities, indent=2)}\n\n"
        "Form the holistic overview of this panel."
    )
    return parse_structured(
        system=OVERVIEW_SYSTEM, user=user, schema=PanelOverview, step="cross_marker_overview"
    )


def run(
    patient: DeidentifiedPatient, latest: Panel, baseline: BaselineResult
) -> CrossMarkerResult:
    # Pass A — holistic overview.
    overview = _overview(patient, latest, baseline)

    # Pass B — marker-by-marker resonance against the overview.
    markers = _result_rows(latest)
    severities = [
        {"marker": f.marker, "severity": f.severity.value} for f in baseline.findings
    ]
    user = (
        f"{_context(patient, latest)}\n\n"
        f"HOLISTIC OVERVIEW (Pass A):\n{overview.model_dump_json(indent=2)}\n\n"
        f"Full panel (JSON):\n{json.dumps(markers, indent=2, default=str)}\n\n"
        f"Baseline severities:\n{json.dumps(severities, indent=2)}\n\n"
        "Now do the marker-by-marker resonance check against the overview."
    )
    result = parse_structured(
        system=MARKER_SYSTEM, user=user, schema=CrossMarkerResult, step="cross_marker"
    )
    # Carry the overview narrative forward for the orchestrator.
    if not result.overview:
        result.overview = overview.narrative
    return result
