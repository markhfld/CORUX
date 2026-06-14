"""Builds the physician-report view-model from pipeline output.

All presentation logic lives here so the UI is a dumb renderer: marker rows with
status tiers (incl. a 'Watch' upper-normal tier) and trend/change vs the prior
panel, derived ratios, and the traditional-lab vs AI side-by-side rows. Everything
is derived from the actual pipeline output — no canned content.
"""

from __future__ import annotations

from typing import Optional

from . import harmonize
from .schemas import AnalyteTrajectory, BaselineResult, Panel


def _g(x) -> str:
    return f"{x:g}" if isinstance(x, (int, float)) else str(x)


def _reference_str(rl, rh, ref_note) -> str:
    if rl is not None and rh is not None:
        return f"{_g(rl)}–{_g(rh)}"
    if rh is not None:
        return f"< {_g(rh)}"
    if rl is not None:
        return f"> {_g(rl)}"
    return ref_note or "—"


def _status(severity: Optional[str], value, rl, rh, flag) -> tuple[str, str]:
    """(label, tier). Severity from the baseline agent; 'Watch' computed for
    in-range values sitting near a bound."""
    numeric = isinstance(value, (int, float))
    if severity == "Dangerous":
        return ("Dangerous", "dangerous")
    if severity == "Critical":
        return ("Critical", "critical")
    if severity == "Abnormal":
        if numeric and rh is not None and value > rh:
            return ("Elevated", "elevated")
        if numeric and rl is not None and value < rl:
            return ("Low", "low")
        return ("Abnormal", "elevated")
    if severity is None and flag in ("high", "low"):
        return ("Elevated" if flag == "high" else "Low", "elevated" if flag == "high" else "low")
    # Normal -> Watch if sitting near a bound (upper or lower).
    if numeric:
        if rh and rh > 0 and rh >= value >= 0.85 * rh:
            return ("Watch", "watch")
        if rl and rl > 0 and rl <= value <= 1.15 * rl:
            return ("Watch", "watch")
    return ("Normal", "normal")


def _trend(traj: Optional[AnalyteTrajectory]) -> dict:
    if traj is None:
        return {"label": "baseline", "tier": "baseline", "previous": None,
                "change": None, "unit": None, "peak": None}
    nums = [p for p in traj.points if isinstance(p.canonical_value, (int, float))]
    previous = nums[-2].canonical_value if len(nums) >= 2 else None
    latest = nums[-1].canonical_value if nums else None
    change = round(latest - previous, 4) if (previous is not None and latest is not None) else None
    latest_in_range = traj.points[-1].in_range if traj.points else None
    now_flagged = (
        len(traj.points) >= 2
        and traj.points[-2].in_range is True
        and traj.points[-1].in_range is False
    )
    c = traj.classification
    if now_flagged:
        label, tier = "Now flagged", "elevated"
    elif c == "resolved":
        label, tier = "Resolved", "falling"
    elif latest_in_range is False:  # currently out of range
        if c == "rising":
            label, tier = "Worsening", "elevated"
        elif c == "falling":
            label, tier = "Improving", "falling"
        else:
            label, tier = "Elevated", "elevated"
    else:  # currently in range — don't call it worsening
        if c == "rising":
            label, tier = "Rising", "stable"
        elif c == "falling":
            label, tier = "Improving", "falling"
        elif c == "fluctuating":
            label, tier = "Variable", "stable"
        else:
            label, tier = "Stable", "stable"
    return {"label": label, "tier": tier, "previous": previous, "change": change,
            "unit": traj.canonical_unit, "peak": traj.peak}


def _find(panel: Panel, loincs: set[str], name_kw: str):
    for r in panel.results:
        if (r.loinc and r.loinc in loincs) or name_kw in r.name.lower():
            if isinstance(r.value, (int, float)):
                return r
    return None


def _ratio(panel: Panel, num, den, name: str, reference: str, hi_flag: float) -> Optional[dict]:
    if not num or not den:
        return None
    a = harmonize.harmonize_value(num.name, num.loinc, num.value, num.unit)["canonical_value"]
    b = harmonize.harmonize_value(den.name, den.loinc, den.value, den.unit)["canonical_value"]
    if not isinstance(a, (int, float)) or not isinstance(b, (int, float)) or not b:
        return None
    val = round(a / b, 2)
    return {
        "name": name,
        "value": val,
        "reference": reference,
        "status": "Elevated" if val > hi_flag else "Normal",
        "tier": "elevated" if val > hi_flag else "normal",
    }


def build(
    latest: Panel,
    baseline: BaselineResult,
    trajectories: list[AnalyteTrajectory],
    panel_count: int,
) -> dict:
    sev_by_marker = {f.marker: f.severity.value for f in baseline.findings}
    traj_by_loinc = {t.loinc: t for t in trajectories if t.loinc}
    traj_by_name = {t.analyte.lower(): t for t in trajectories}

    markers = []
    for r in latest.results:
        sev = sev_by_marker.get(r.name)
        label, tier = _status(sev, r.value, r.ref_low, r.ref_high, r.flag)
        traj = traj_by_loinc.get(r.loinc) or traj_by_name.get(r.name.lower())
        markers.append(
            {
                "name": r.name,
                "result": f"{_g(r.value)} {r.unit or ''}".strip(),
                "reference": _reference_str(r.ref_low, r.ref_high, r.ref_note),
                "status": label,
                "tier": tier,
                "derived": r.derived,
                "trend": _trend(traj),
            }
        )

    # Derived ratios (only when both components are present and numeric).
    tg = _find(latest, {"2571-8"}, "triglycerid")
    hdl = _find(latest, {"2085-9"}, "hdl")
    ast = _find(latest, {"1920-8"}, "ast")
    alt = _find(latest, {"1742-6"}, "alt")
    ratios = [
        r for r in [
            _ratio(latest, tg, hdl, "TG / HDL ratio", "< 2 (low CV risk)", 2.0),
            _ratio(latest, ast, alt, "AST / ALT (De Ritis)", "< 1.0", 1.0),
        ] if r
    ]

    traditional = [
        {
            "name": r.name,
            "result": f"{_g(r.value)} {r.unit or ''}".strip(),
            "reference": _reference_str(r.ref_low, r.ref_high, r.ref_note),
            "flag": r.flag or "normal",
        }
        for r in latest.results
    ]

    lab = latest.source_lab
    header = {
        "panel_title": latest.context or "Lab Panel",
        "date": latest.collected_date,
        "panels_in_history": panel_count,
        "lab": lab.name if lab else None,
        "country": lab.country if lab else None,
        "unit_system": lab.unit_system if lab else None,
    }

    return {"header": header, "markers": markers, "ratios": ratios, "traditional": traditional}
