"""Pydantic models for CORUX.

Two groups:
  1. Input contract — the analyzer output JSON (the single swap point for the real
     analyzer format; change these models and nothing else in the pipeline moves).
  2. Agent output schemas — what each Claude step is constrained to return, enforced
     via `client.messages.parse(...)` so every agent yields valid JSON, no parsing.
"""

from __future__ import annotations

from enum import Enum
from typing import Optional, Union

from pydantic import BaseModel, Field


# --------------------------------------------------------------------------- #
# 1. Input contract — de-identified multi-panel lab results (PatientLabResults)
# --------------------------------------------------------------------------- #

class Analytical(BaseModel):
    """Owned raw-signal context — present only on in-house (CORUX-lab) panels.
    Absent on external data: that absence is the honest demonstration of the moat."""

    cv_percent: Optional[float] = None
    hemolysis_index: Optional[str] = None
    qc_status: Optional[str] = None
    method: Optional[str] = None


class Result(BaseModel):
    """One result within a panel, stored EXACTLY as the lab issued it (original
    value, unit, range). Harmonization is performed live by a tool, never
    pre-converted here. `value` is numeric, or a qualitative string such as
    'negative' / a censored value like '>90' / '<0.6'."""

    name: str
    loinc: Optional[str] = None  # LOINC code; null for derived scores / when absent
    value: Optional[Union[float, str]] = None
    unit: Optional[str] = None  # null for unitless / qualitative results
    ref_low: Optional[float] = None
    ref_high: Optional[float] = None
    flag: Optional[str] = None  # lab-issued (vs its OWN range): "normal" | "low" | "high"
    ref_note: Optional[str] = None
    derived: bool = False  # true when calculated (eGFR, FIB-4, calc LDL), not measured
    analytical: Optional[Analytical] = None  # owned-signal block; absent on external labs


class SourceLab(BaseModel):
    name: str
    country: Optional[str] = None  # ISO 3166-1 alpha-2
    unit_system: Optional[str] = None  # "conventional" | "SI"


class Panel(BaseModel):
    """One collection event (a visit / draw) from one lab."""

    panel_id: str
    collected_date: Optional[str] = None  # ISO date; drives chronology
    reported_date: Optional[str] = None
    source_lab: SourceLab = Field(default_factory=lambda: SourceLab(name=""))
    context: Optional[str] = None  # free-text ordering reason / panel context
    results: list[Result] = Field(default_factory=list)


class Patient(BaseModel):
    """Already de-identified upstream: pseudonymous id, no name/dob."""

    patient_id: str
    sex: Optional[str] = None  # "male" | "female"
    age_years: Optional[int] = None
    notes: Optional[str] = None  # de-identified clinical context


class PatientLabResults(BaseModel):
    """Top-level input document. May carry multiple panels across dates."""

    patient: Patient
    panels: list[Panel] = Field(default_factory=list)


# Backward-compatible alias (the old top-level name).
AnalyzerOutput = PatientLabResults


# --------------------------------------------------------------------------- #
# Internal de-identified view carried through the pipeline
# --------------------------------------------------------------------------- #

class DeidentifiedPatient(BaseModel):
    """What the pipeline carries. Input is already de-identified; we additionally
    keep the pseudonymous `patient_id` out of LLM prompts and pass only the
    clinical context (sex, age, notes) the agents need to reason."""

    patient_key: str  # stable hash of patient_id; links panels across submissions
    sex: Optional[str] = None
    age_years: Optional[int] = None
    notes: Optional[str] = None


# --------------------------------------------------------------------------- #
# 2. Agent output schemas
# --------------------------------------------------------------------------- #

class Severity(str, Enum):
    NORMAL = "Normal"
    ABNORMAL = "Abnormal"
    CRITICAL = "Critical"
    DANGEROUS = "Dangerous"


class BaselineFinding(BaseModel):
    marker: str
    value: Optional[Union[float, str]] = None  # numeric or qualitative
    unit: Optional[str] = None
    ref_low: Optional[float] = None
    ref_high: Optional[float] = None
    position: Optional[str] = None  # below / within / above / qualitative / unknown
    severity: Severity
    rationale: str


class BaselineResult(BaseModel):
    findings: list[BaselineFinding]


class DataQualityError(BaseModel):
    marker: str
    issue: str
    confidence: str  # low / medium / high


class PanelOverview(BaseModel):
    """Pass A — the holistic read of the whole panel, formed before judging any
    single marker."""

    narrative: str  # the overall story the dataset tells
    dominant_patterns: list[str] = Field(default_factory=list)
    expected_correlations: list[str] = Field(
        default_factory=list
    )  # which markers should move together, and how


class ResonanceVerdict(str, Enum):
    CORROBORATED = "corroborated"      # fits the panel; real finding (even if severe)
    AMBIGUOUS = "ambiguous"            # partial/weak corroboration; recommend verifying
    UNCORROBORATED = "uncorroborated"  # isolated extreme; likely data error


class MarkerResonance(BaseModel):
    """Pass B — does one marker fit the overall picture?"""

    marker: str
    verdict: ResonanceVerdict
    expected_corroboration: str  # what linked markers would corroborate this value
    assessment: str  # why it does / doesn't resonate


class VerificationFlag(BaseModel):
    """A marker worth re-testing before acting — not asserted as an error."""

    marker: str
    reason: str
    confidence: str  # low / medium / high


class CrossMarkerResult(BaseModel):
    overview: str = ""  # carried from Pass A for downstream context
    coherent: bool
    correlations: list[str] = Field(default_factory=list)  # plain-language observations
    resonance: list[MarkerResonance] = Field(default_factory=list)
    errors: list[DataQualityError] = Field(  # uncorroborated isolated extremes
        default_factory=list
    )
    verifications: list[VerificationFlag] = Field(  # ambiguous -> re-test recommended
        default_factory=list
    )


class MarkerTrend(BaseModel):
    marker: str
    direction: str  # rising / falling / stable / unclear
    delta_summary: str  # plain-language change across visits
    trajectory: str  # risk trajectory, not a snapshot


class LongitudinalResult(BaseModel):
    visits_compared: int
    trends: list[MarkerTrend] = Field(default_factory=list)
    overall_trajectory: str


# --- Harmonization tool outputs (deterministic; §3 / §5 of the schema spec) --- #

class TrajectoryPoint(BaseModel):
    date: Optional[str] = None
    lab: Optional[str] = None
    source_value: Optional[Union[float, str]] = None
    source_unit: Optional[str] = None
    canonical_value: Optional[float] = None
    canonical_unit: Optional[str] = None
    harmonized: bool = False  # true when the unit was converted
    in_range: Optional[bool] = None
    flag: Optional[str] = None


class AnalyteTrajectory(BaseModel):
    analyte: str
    loinc: Optional[str] = None
    canonical_unit: Optional[str] = None
    classification: str  # stable | rising | falling | fluctuating | resolved | insufficient
    elevated: bool = False
    summary: str  # e.g. "94 -> 51 -> 98 U/L"
    peak: Optional[str] = None  # worst excursion, e.g. "peaked 789 mg/dL — ~7.9x upper limit ..."
    points: list[TrajectoryPoint] = Field(default_factory=list)


# --- assess_pattern (tool 4 — LLM) ------------------------------------------- #

class PatternFinding(BaseModel):
    pattern_name: str
    members: list[str]  # the analytes that co-occur
    present: bool
    recommendation: str  # structured follow-up — not a diagnosis
    priority: str  # routine / soon / urgent
    rationale: str


class PatternResult(BaseModel):
    patterns: list[PatternFinding] = Field(default_factory=list)
    overall: str


class Citation(BaseModel):
    claim: str
    source: str  # title / publisher
    url: Optional[str] = None


class LiteratureResult(BaseModel):
    citations: list[Citation] = Field(default_factory=list)


class DiscussionPoint(BaseModel):
    topic: str
    detail: str
    priority: str  # routine / soon / urgent


class NextPanel(BaseModel):
    """Recommendation for the next draw — interval + markers to add."""

    interval: str  # e.g. "3 months"
    rationale: str
    suggested_markers: list[str] = Field(default_factory=list)  # e.g. ["apoB", "Lp(a)"]


class OrchestratorResult(BaseModel):
    """Final clinician-facing output."""

    summary: str
    headline: str = ""  # one-line lead the clinician reads first
    explanation: str  # narrative explanation of the numbers
    key_caveat: str = ""  # the single most important caution (rendered as a callout)
    discussion_points: list[DiscussionPoint] = Field(default_factory=list)
    next_panel: Optional[NextPanel] = None
    data_quality_flags: list[DataQualityError] = Field(
        default_factory=list
    )  # likely errors (uncorroborated isolated extremes)
    verification_recommended: list[VerificationFlag] = Field(
        default_factory=list
    )  # ambiguous values worth re-testing before acting
    disclaimer: str = (
        "Decision-support only. Not a diagnosis. Clinical judgment required."
    )
