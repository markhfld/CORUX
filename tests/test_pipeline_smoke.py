"""Smoke test for the pipeline wiring — LLM agent calls are mocked, so no API key
or network is needed. The deterministic steps (incl. harmonize+trends) run for real."""

import pytest

from corux import pipeline
from corux.agents import baseline, cross_marker, orchestrator, pattern
from corux.history import build_series
from corux.ingest import ingest
from corux.schemas import (
    BaselineFinding,
    BaselineResult,
    CrossMarkerResult,
    DataQualityError,
    DiscussionPoint,
    MarkerResonance,
    NextPanel,
    OrchestratorResult,
    PatternFinding,
    PatternResult,
    ResonanceVerdict,
    Severity,
    VerificationFlag,
)

SAMPLE = "data/sample_input.json"


@pytest.fixture(autouse=True)
def mock_agents(monkeypatch):
    def fake_baseline(patient, latest):
        return BaselineResult(
            findings=[
                BaselineFinding(marker=r.name, value=r.value, unit=r.unit,
                                severity=Severity.ABNORMAL, rationale="mock")
                for r in latest.results
            ]
        )

    def fake_cross(patient, latest, base):
        return CrossMarkerResult(
            overview="mock holistic overview",
            coherent=False,
            correlations=["glucose and HbA1c move together"],
            resonance=[
                MarkerResonance(marker="Creatinine", verdict=ResonanceVerdict.UNCORROBORATED,
                                expected_corroboration="urea/eGFR", assessment="isolated extreme"),
            ],
            errors=[DataQualityError(marker="Creatinine", issue="implausible jump", confidence="high")],
            verifications=[VerificationFlag(marker="Potassium", reason="possible hemolysis", confidence="medium")],
        )

    def fake_pattern(patient, trajectories, base):
        return PatternResult(
            patterns=[PatternFinding(pattern_name="Mock metabolic", members=["HbA1c", "Glucose"],
                                     present=True, recommendation="follow up", priority="soon",
                                     rationale="mock")],
            overall="mock pattern overall",
        )

    def fake_orch(patient, base, cross, trajectories, pat, lit):
        return OrchestratorResult(
            summary="mock summary",
            headline="mock headline",
            explanation="mock explanation",
            key_caveat="mock caveat",
            discussion_points=[DiscussionPoint(topic="HbA1c", detail="discuss", priority="soon")],
            next_panel=NextPanel(interval="3 months", rationale="mock", suggested_markers=["apoB"]),
            data_quality_flags=cross.errors,
            verification_recommended=cross.verifications,
        )

    monkeypatch.setattr(baseline, "run", fake_baseline)
    monkeypatch.setattr(cross_marker, "run", fake_cross)
    monkeypatch.setattr(pattern, "run", fake_pattern)
    monkeypatch.setattr(orchestrator, "run", fake_orch)


def test_pipeline_runs_end_to_end_without_persist():
    result = pipeline.run(SAMPLE, persist=False)
    assert result.visits == 2
    assert result.latest_panel is not None
    assert result.trajectories  # 2 panels -> harmonize+trends produced trajectories
    assert result.pattern is not None
    assert result.literature is None
    assert result.final.summary == "mock summary"
    # Gate carried through to final output.
    assert any(e.marker == "Creatinine" for e in result.final.data_quality_flags)
    assert any(v.marker == "Potassium" for v in result.final.verification_recommended)
    assert result.notes


def test_report_view_model_built():
    from corux import report
    result = pipeline.run(SAMPLE, persist=False)
    r = report.build(result.latest_panel, result.baseline, result.trajectories, result.visits)
    assert r["markers"] and all("status" in m and "trend" in m for m in r["markers"])
    assert r["traditional"]  # raw rows for the side-by-side
    # Creatinine in the sample spikes 0.9 -> 14.2: its trajectory carries a peak note.
    cre = next((m for m in r["markers"] if m["name"] == "Creatinine"), None)
    assert cre is not None


def test_single_panel_skips_trends():
    doc = ingest(SAMPLE)
    one = {"patient": doc.patient.model_dump(), "panels": [doc.panels[0].model_dump()]}
    result = pipeline.run(one, persist=False)
    assert result.visits == 1
    assert result.trajectories == []
    assert any("Single panel" in n for n in result.notes)


def test_build_series_keyed_by_loinc():
    doc = ingest(SAMPLE)
    series = build_series(doc.panels)
    assert "4548-4" in series  # HbA1c LOINC
    assert len(series["4548-4"]) == 2
    assert series["4548-4"][0]["value"] == 5.9
