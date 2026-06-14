"""Step 1 — Ingest signal.

Parse and validate the analyzer JSON into typed models, then sort panels
chronologically (by collected_date) so every downstream step sees oldest -> newest.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Union

from .schemas import Panel, PatientLabResults


def _sort_key(panel: Panel) -> str:
    # Empty/missing dates sort first (treated as oldest/unknown).
    return panel.collected_date or ""


def ingest(source: Union[str, Path, dict]) -> PatientLabResults:
    """Load lab results from a path, JSON string, or dict; validate; sort panels."""
    if isinstance(source, dict):
        data = source
    else:
        text = (
            Path(source).read_text(encoding="utf-8")
            if Path(str(source)).exists()
            else str(source)
        )
        data = json.loads(text)

    doc = PatientLabResults.model_validate(data)
    doc.panels.sort(key=_sort_key)
    return doc
