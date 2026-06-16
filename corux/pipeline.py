"""The code-controlled pipeline.

Deterministic steps (ingest, PII firewall, history, harmonize+trends) are plain
code; the agent steps (baseline, cross-marker, pattern, literature, orchestrator)
call Claude. Cross-lab unit/range harmonization is done deterministically (§5) and
its tool calls are surfaced in the trace. Returns a result bundle with the final
orchestrator output plus the intermediate artifacts.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Union

from . import harmonize, history, ingest, privacy, tracing
from .agents import baseline, cross_marker, literature, orchestrator, pattern
from .schemas import (
    AnalyteTrajectory,
    BaselineResult,
    CrossMarkerResult,
    DeidentifiedPatient,
    LiteratureResult,
    OrchestratorResult,
    Panel,
    PatternResult,
)


@dataclass
class PipelineResult:
    patient: DeidentifiedPatient
    visits: int
    latest_panel: Panel
    baseline: BaselineResult
    cross_marker: CrossMarkerResult
    trajectories: list[AnalyteTrajectory]
    pattern: Optional[PatternResult]
    literature: Optional[LiteratureResult]
    final: OrchestratorResult
    notes: list[str] = field(default_factory=list)
    panel_dates: list[str] = field(default_factory=list)
    all_panels: list[Panel] = field(default_factory=list)


def _fmt_num(x) -> str:
    return f"{x:g}" if isinstance(x, (int, float)) else str(x)


def run(
    source: Union[str, Path, dict],
    *,
    literature_enabled: bool = False,
    persist: bool = True,
) -> PipelineResult:
    notes: list[str] = []
    tracing.emit("pipeline", status="started")

    # 1. Ingest
    with tracing.step("ingest", "Ingest signal"):
        doc = ingest.ingest(source)
        if not doc.panels:
            raise ValueError("No panels in lab results.")

    # 2. PII firewall
    with tracing.step("privacy", "PII firewall"):
        patient = privacy.deidentify(doc)

    # 3. Retrieve history
    with tracing.step("history", "Retrieve history"):
        if persist:
            all_panels = history.merge_and_store(patient.patient_key, doc)
        else:
            all_panels = sorted(doc.panels, key=lambda p: p.collected_date or "")
        visits = len(all_panels)
        latest = all_panels[-1]

    # 4. Compare baseline
    with tracing.step("baseline", "Compare baseline (agent)"):
        baseline_res = baseline.run(patient, latest)

    # 5. Reason across markers (gate)
    with tracing.step("cross_marker", "Reason across markers (agent)"):
        cross_res = cross_marker.run(patient, latest, baseline_res)
    if cross_res.errors:
        notes.append(
            f"{len(cross_res.errors)} likely data error(s) flagged by cross-marker review."
        )
    if cross_res.verifications:
        notes.append(
            f"{len(cross_res.verifications)} value(s) recommended for confirmatory re-test."
        )

    # 6. Harmonize & trends (deterministic tools, surfaced in the trace)
    trajectories: list[AnalyteTrajectory] = []
    if visits >= 2:
        with tracing.step("harmonize", "Harmonize & trends (tools)"):
            harmonized_count = 0
            for entry in harmonize.select_tracked(all_panels):
                # Tool 1 — get_reference_ranges (surface the cross-unit conversions)
                for p in sorted(entry["points"], key=lambda x: x["date"] or ""):
                    if not p["harmonized"]:
                        continue
                    gr = harmonize.get_reference_ranges(
                        p["name"], p["loinc"], p["value"], p["unit"],
                        p["ref_low"], p["ref_high"], p["flag"],
                    )
                    harmonized_count += 1
                    cv = gr["canonical"]["value"]
                    tracing.emit(
                        "tool", tool="get_reference_ranges", analyte=entry["name"],
                        input=f"{p['value']} {p['unit']}",
                        output=f"{_fmt_num(cv)} {gr['canonical']['unit']}"
                        + (" (in range)" if gr["in_range"] else " (out of range)"),
                        status="completed",
                    )
                # Tool 2 — compare_to_prior
                cmp = harmonize.compare_to_prior(entry)
                tracing.emit(
                    "tool", tool="compare_to_prior", analyte=entry["name"],
                    output=cmp["series_str"], status="completed",
                )
                # Tool 3 — assess_trajectory
                tr = harmonize.assess_trajectory(cmp)
                label = tr["classification"] + (
                    "-elevated"
                    if tr["elevated"] and tr["classification"] not in ("stable", "insufficient")
                    else ""
                )
                tracing.emit(
                    "tool", tool="assess_trajectory", analyte=entry["name"],
                    output=label, status="completed",
                )
                trajectories.append(harmonize.build_trajectory(cmp, tr))
            if harmonized_count:
                notes.append(
                    f"Harmonized {harmonized_count} cross-unit value(s) across labs "
                    "to compare like-for-like."
                )
    else:
        tracing.skipped("harmonize", "Harmonize & trends (tools)", "single panel on record")
        notes.append("Single panel — cross-panel trends skipped; seeded for next time.")

    # 7. Assess pattern (tool 4 — agent)
    pattern_res: Optional[PatternResult] = None
    abnormal_n = sum(1 for f in baseline_res.findings if f.severity.value != "Normal")
    if trajectories or abnormal_n >= 2:
        with tracing.step("pattern", "Assess pattern (agent)"):
            pattern_res = pattern.run(patient, trajectories, baseline_res)
    else:
        tracing.skipped("pattern", "Assess pattern (agent)", "no multi-marker pattern to assess")

    # 8. Consult literature (optional)
    literature_res: Optional[LiteratureResult] = None
    if literature_enabled:
        with tracing.step("literature", "Consult literature (agent)"):
            literature_res = literature.run(baseline_res, cross_res)
    else:
        tracing.skipped("literature", "Consult literature (agent)", "disabled for this run")

    # 9. Orchestrator
    with tracing.step("orchestrator", "Orchestrator (agent)"):
        final = orchestrator.run(
            patient, baseline_res, cross_res, trajectories, pattern_res, literature_res
        )

    tracing.emit("pipeline", status="completed")

    return PipelineResult(
        patient=patient,
        visits=visits,
        latest_panel=latest,
        baseline=baseline_res,
        cross_marker=cross_res,
        trajectories=trajectories,
        pattern=pattern_res,
        literature=literature_res,
        final=final,
        notes=notes,
        panel_dates=[p.collected_date for p in all_panels if p.collected_date],
        all_panels=all_panels,
    )
