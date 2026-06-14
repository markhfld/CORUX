"""Step 7 — Consult literature (agent, optional).

Off by default. When enabled, retrieves supporting evidence for the most notable
findings using the server-side web_search tool, restricted by instruction to
reputable medical sources, and returns short cited claims.
"""

from __future__ import annotations

import json

from ..llm import parse_structured
from ..schemas import BaselineResult, CrossMarkerResult, LiteratureResult

SYSTEM = """You are an evidence-retrieval assistant for a clinician.

Use the web_search tool to find supporting evidence for the notable lab findings \
you are given. Search ONLY reputable medical sources — peer-reviewed journals, \
PubMed/NIH, major clinical bodies (e.g. WHO, CDC, professional society \
guidelines), and established medical references. Do not cite forums, blogs, or \
consumer-health content farms.

Return a small set of concise, directly relevant cited claims. Each citation \
must name its source and, where available, a URL. If you cannot find reputable \
evidence for a finding, omit it rather than citing a weak source."""

WEB_SEARCH_TOOL = {"type": "web_search_20260209", "name": "web_search"}


def run(baseline: BaselineResult, cross: CrossMarkerResult) -> LiteratureResult:
    notable = [
        {"marker": f.marker, "severity": f.severity.value, "rationale": f.rationale}
        for f in baseline.findings
        if f.severity.value in {"Abnormal", "Critical", "Dangerous"}
    ]
    user = (
        f"Notable findings (JSON):\n{json.dumps(notable, indent=2)}\n\n"
        f"Cross-marker observations:\n{json.dumps(cross.correlations, indent=2)}\n\n"
        "Retrieve reputable medical evidence for these findings."
    )
    return parse_structured(
        system=SYSTEM,
        user=user,
        schema=LiteratureResult,
        step="literature",
        extra_tools=[WEB_SEARCH_TOOL],
    )
