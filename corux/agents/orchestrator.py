"""Step 8 — Orchestrator (agent).

Synthesizes the upstream structured outputs (baseline, cross-marker, longitudinal,
literature) into the final clinician-facing JSON: a summary, a narrative
explanation of the numbers, prioritized discussion points, and any data-quality
flags carried forward from step 5.
"""

from __future__ import annotations

import json
from typing import Optional

from ..llm import parse_structured
from ..schemas import (
    AnalyteTrajectory,
    BaselineResult,
    CrossMarkerResult,
    DeidentifiedPatient,
    LiteratureResult,
    OrchestratorResult,
    PatternResult,
)

SYSTEM = """You are the lead interpretation agent producing the final report for a \
clinician. You receive structured outputs from upstream steps: baseline severity \
classifications, cross-marker coherence/error findings, an optional longitudinal \
trend analysis, and optional literature citations.

Produce:
- headline: ONE sentence — the single most important takeaway, the thing a \
  clinician would want to know first.
- summary: 2-3 sentences expanding on the headline.
- key_caveat: the single most important caution to foreground (a data-quality \
  concern, a value to confirm, or a limitation). One or two sentences. May be empty \
  if nothing material.
- explanation: a clear narrative tying the numbers together — what stands out, \
  how markers relate, and (if present) where trends are heading. Call out any \
  historical critical value surfaced by a trajectory's `peak`, even if the latest \
  value has normalized.
- next_panel: recommend when to draw next (interval) with a rationale, and list \
  any additional markers worth adding that would sharpen the picture (suggested_markers).
- discussion_points: concrete, prioritized items for the clinician \
  (priority routine/soon/urgent).
- data_quality_flags: carry forward the cross-marker step's likely data ERRORS \
  (uncorroborated isolated extremes) so they are not mistaken for real findings.
- verification_recommended: carry forward the cross-marker step's AMBIGUOUS values \
  worth a confirmatory re-test before acting. Keep these DISTINCT from \
  data_quality_flags — a verification is "double-check this number", not "this \
  number is wrong". Do NOT recommend re-testing values the cross-marker step \
  judged corroborated, even if severe.

You also receive harmonized cross-panel `trajectories` (already converted to one \
canonical unit per analyte — comparable across labs) and a `pattern` assessment \
(recognized clinical patterns + structured follow-up recommendations). Weave the \
trajectory direction and any identified pattern into the explanation and \
discussion_points; a multi-marker pattern over time is usually the most important \
thing for the clinician to see.

Be precise and grounded in the inputs. Do not invent values or trends not present. \
This is decision-support, not a diagnosis."""


def run(
    patient: DeidentifiedPatient,
    baseline: BaselineResult,
    cross: CrossMarkerResult,
    trajectories: list[AnalyteTrajectory],
    pattern: Optional[PatternResult],
    literature: Optional[LiteratureResult],
) -> OrchestratorResult:
    payload = {
        "patient": {"age": patient.age_years, "sex": patient.sex, "notes": patient.notes},
        "baseline": baseline.model_dump(),
        "cross_marker": cross.model_dump(),
        "trajectories": [t.model_dump() for t in trajectories],
        "pattern": pattern.model_dump() if pattern else None,
        "literature": literature.model_dump() if literature else None,
    }
    user = (
        "Upstream pipeline outputs (JSON):\n"
        f"{json.dumps(payload, indent=2, default=str)}\n\n"
        "Produce the final clinician-facing interpretation."
    )
    return parse_structured(
        system=SYSTEM, user=user, schema=OrchestratorResult, step="orchestrator"
    )
