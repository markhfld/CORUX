"""Step 3 — Retrieve history & build longitudinal series.

Persists each patient's panels keyed by `patient_key` and merges incoming panels,
deduping by collected_date. Returns a per-analyte time series (keyed by LOINC when
present, else by name) so the longitudinal agent can reason over trends. Storage is
a JSON file behind this interface — swap for SQLite later without touching the
pipeline.
"""

from __future__ import annotations

import json
from pathlib import Path

from . import config
from .schemas import Panel, PatientLabResults


def _record_path(patient_key: str) -> Path:
    config.STORE_DIR.mkdir(parents=True, exist_ok=True)
    return config.STORE_DIR / f"{patient_key}.json"


def _load_record(patient_key: str) -> list[Panel]:
    path = _record_path(patient_key)
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    return [Panel.model_validate(p) for p in data.get("panels", [])]


def _save_record(patient_key: str, panels: list[Panel]) -> None:
    path = _record_path(patient_key)
    payload = {
        "patient_key": patient_key,
        "panels": [p.model_dump() for p in panels],
    }
    path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")


def merge_and_store(patient_key: str, doc: PatientLabResults) -> list[Panel]:
    """Merge incoming panels with stored history (dedupe by collected_date);
    persist; return all panels oldest -> newest."""
    existing = _load_record(patient_key)
    by_date: dict[str, Panel] = {p.collected_date or "": p for p in existing}
    for p in doc.panels:
        by_date[p.collected_date or ""] = p  # incoming wins on same date
    merged = sorted(by_date.values(), key=lambda p: p.collected_date or "")
    _save_record(patient_key, merged)
    return merged


def build_series(panels: list[Panel]) -> dict[str, list[dict]]:
    """Per-analyte time series. Keyed by LOINC when available (canonical across
    labs), else by name. Each point carries the unit and unit_system so the
    longitudinal agent can avoid invalid cross-unit comparisons."""
    series: dict[str, list[dict]] = {}
    for panel in panels:
        us = panel.source_lab.unit_system if panel.source_lab else None
        for r in panel.results:
            key = r.loinc or r.name
            series.setdefault(key, []).append(
                {
                    "name": r.name,
                    "loinc": r.loinc,
                    "date": panel.collected_date,
                    "value": r.value,
                    "unit": r.unit,
                    "unit_system": us,
                    "flag": r.flag,
                    "derived": r.derived,
                }
            )
    return series
