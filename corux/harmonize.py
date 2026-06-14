"""Deterministic unit/range harmonization + the cross-lab analysis tools (§3/§5).

The headline differentiator: results are stored exactly as each lab issued them
(original value, unit, range); harmonization to a single canonical unit per analyte
is done HERE, in deterministic code, not by the LLM — more credible to a clinician
and free of on-screen arithmetic errors.

Tools (surfaced individually in the trace by the pipeline):
  1. get_reference_ranges(result)  -> harmonize one value + its range
  2. compare_to_prior(points)      -> harmonized series across panels, with deltas
  3. assess_trajectory(comparison) -> classify the harmonized series
(Tool 4, assess_pattern, is an LLM step — see agents/pattern.py.)
"""

from __future__ import annotations

from typing import Optional, Union

from .schemas import AnalyteTrajectory, Panel, TrajectoryPoint

# --------------------------------------------------------------------------- #
# §5 — canonical unit per analyte group + multiplicative factor source -> canonical
# --------------------------------------------------------------------------- #

GROUPS: dict[str, dict] = {
    # enzymes (GGT / AST / ALT / ALP): canonical U/L; µkat/L x 60
    "enzyme": {"canonical": "U/L", "units": {"u/l": 1.0, "ukat/l": 60.0}},
    "hemoglobin": {"canonical": "g/dL", "units": {"g/dl": 1.0, "mmol/l": 1.611}},
    "creatinine": {"canonical": "mg/dL", "units": {"mg/dl": 1.0, "umol/l": 1 / 88.4}},
    "cholesterol": {"canonical": "mg/dL", "units": {"mg/dl": 1.0, "mmol/l": 38.67}},
    "triglycerides": {"canonical": "mg/dL", "units": {"mg/dl": 1.0, "mmol/l": 88.57}},
    "bilirubin": {"canonical": "mg/dL", "units": {"mg/dl": 1.0, "umol/l": 1 / 17.1}},
    "uric_acid": {"canonical": "mg/dL", "units": {"mg/dl": 1.0, "umol/l": 1 / 59.48}},
    "mch": {"canonical": "pg", "units": {"pg": 1.0, "fmol": 1 / 0.062}},
    "glucose": {"canonical": "mg/dL", "units": {"mg/dl": 1.0, "mmol/l": 18.0}},
}

# Analyte -> group, by LOINC (preferred) then name keyword.
LOINC_GROUP = {
    "2324-2": "enzyme",  # GGT
    "1920-8": "enzyme",  # AST
    "1742-6": "enzyme",  # ALT
    "6768-6": "enzyme",  # ALP
    "718-7": "hemoglobin",
    "2160-0": "creatinine",
    "2093-3": "cholesterol",
    "2085-9": "cholesterol",
    "13457-7": "cholesterol",
    "43396-1": "cholesterol",
    "2571-8": "triglycerides",
    "1975-2": "bilirubin",
    "3084-1": "uric_acid",
    "785-6": "mch",
    "1558-6": "glucose",
    "2345-7": "glucose",
}


def _norm_unit(unit: Optional[str]) -> str:
    if not unit:
        return ""
    return unit.strip().lower().replace("µ", "u").replace("μ", "u")


def resolve_group(name: str, loinc: Optional[str]) -> Optional[str]:
    if loinc and loinc in LOINC_GROUP:
        return LOINC_GROUP[loinc]
    n = (name or "").lower()
    if any(k in n for k in ("gamma-gt", "ggt", "alkaline phosphatase", "alp")) or n in ("ast (got)", "alt (gpt)") or "ast" in n or "alt" in n:
        return "enzyme"
    if "hemoglobin" in n or n == "hgb":
        return "hemoglobin"
    if "creatinine" in n:
        return "creatinine"
    if "triglycerid" in n:
        return "triglycerides"
    if "cholesterol" in n:
        return "cholesterol"
    if "bilirubin" in n:
        return "bilirubin"
    if "uric acid" in n:
        return "uric_acid"
    if "mch" in n and "mchc" not in n:
        return "mch"
    if "glucose" in n:
        return "glucose"
    return None


def _factor(group: Optional[str], unit: Optional[str]) -> Optional[float]:
    if not group:
        return None
    return GROUPS[group]["units"].get(_norm_unit(unit))


def harmonize_value(
    name: str, loinc: Optional[str], value: Union[float, str, None], unit: Optional[str]
) -> dict:
    """Return canonical_value/unit and whether a conversion happened. Qualitative
    values have no canonical number; numeric analytes with no conversion rule pass
    through unchanged (canonical == source) so they still trend."""
    group = resolve_group(name, loinc)
    if not isinstance(value, (int, float)):
        return {"canonical_value": None, "canonical_unit": unit, "harmonized": False, "group": group}
    factor = _factor(group, unit) if group else None
    if group is None or factor is None:  # no conversion rule -> canonical == source
        return {"canonical_value": float(value), "canonical_unit": unit, "harmonized": False, "group": group}
    canonical_unit = GROUPS[group]["canonical"]
    return {
        "canonical_value": round(float(value) * factor, 4),
        "canonical_unit": canonical_unit,
        "harmonized": _norm_unit(unit) != _norm_unit(canonical_unit),
        "group": group,
    }


# --------------------------------------------------------------------------- #
# Tool 1 — get_reference_ranges
# --------------------------------------------------------------------------- #

def get_reference_ranges(
    name: str,
    loinc: Optional[str],
    value: Union[float, str, None],
    unit: Optional[str],
    ref_low: Optional[float],
    ref_high: Optional[float],
    flag: Optional[str] = None,
) -> dict:
    h = harmonize_value(name, loinc, value, unit)
    cv = h["canonical_value"]
    group = h["group"]
    # Harmonize the reference range with the same factor (1.0 when no conversion).
    factor = _factor(group, unit) if group else None
    mult = factor if factor is not None else 1.0
    crl = round(ref_low * mult, 4) if ref_low is not None else None
    crh = round(ref_high * mult, 4) if ref_high is not None else None
    in_range: Optional[bool]
    if cv is not None and (crl is not None or crh is not None):
        in_range = (crl is None or cv >= crl) and (crh is None or cv <= crh)
    elif flag is not None:
        in_range = flag == "normal"
    else:
        in_range = None
    return {
        "analyte": name,
        "loinc": loinc,
        "source": {"value": value, "unit": unit, "ref_low": ref_low, "ref_high": ref_high},
        "canonical": {"value": cv, "unit": h["canonical_unit"], "ref_low": crl, "ref_high": crh},
        "harmonized": h["harmonized"],
        "in_range": in_range,
    }


# --------------------------------------------------------------------------- #
# select tracked analytes + Tool 2 (compare_to_prior) + Tool 3 (assess_trajectory)
# --------------------------------------------------------------------------- #

def _analyte_key(name: str, loinc: Optional[str]) -> str:
    return loinc or name.lower()


def select_tracked(panels: list[Panel]) -> list[dict]:
    """Analytes worth tracing across panels: present in >= 2 panels AND notable
    (abnormal in any panel, derived, or requiring unit harmonization)."""
    by_key: dict[str, dict] = {}
    for panel in panels:
        lab = panel.source_lab.name if panel.source_lab else None
        for r in panel.results:
            key = _analyte_key(r.name, r.loinc)
            entry = by_key.setdefault(key, {"name": r.name, "loinc": r.loinc, "points": []})
            entry["name"] = r.name  # keep latest display name
            h = harmonize_value(r.name, r.loinc, r.value, r.unit)
            entry["points"].append(
                {
                    "date": panel.collected_date,
                    "lab": lab,
                    "name": r.name,
                    "loinc": r.loinc,
                    "value": r.value,
                    "unit": r.unit,
                    "ref_low": r.ref_low,
                    "ref_high": r.ref_high,
                    "flag": r.flag,
                    "derived": r.derived,
                    "harmonized": h["harmonized"],
                    "abnormal": (r.flag or "normal") != "normal",
                }
            )
    tracked = []
    for key, entry in by_key.items():
        pts = entry["points"]
        if len(pts) < 2:
            continue
        notable = any(p["abnormal"] for p in pts) or any(p["derived"] for p in pts) or any(p["harmonized"] for p in pts)
        if notable:
            tracked.append(entry)
    # Sort: harmonized/abnormal first for a more compelling trace order.
    tracked.sort(key=lambda e: (not any(p["harmonized"] for p in e["points"]), e["name"]))
    return tracked


def compare_to_prior(entry: dict) -> dict:
    """Harmonize every point for one analyte; return the canonical series + deltas."""
    name, loinc = entry["name"], entry["loinc"]
    points = sorted(entry["points"], key=lambda p: p["date"] or "")
    series = []
    canonical_unit = None
    for p in points:
        gr = get_reference_ranges(p["name"], p["loinc"], p["value"], p["unit"], p["ref_low"], p["ref_high"], p["flag"])
        cv = gr["canonical"]["value"]
        canonical_unit = gr["canonical"]["unit"] or canonical_unit
        series.append(
            {
                "date": p["date"],
                "lab": p["lab"],
                "source_value": p["value"],
                "source_unit": p["unit"],
                "canonical_value": cv,
                "canonical_unit": gr["canonical"]["unit"],
                "harmonized": gr["harmonized"],
                "in_range": gr["in_range"],
                "c_ref_low": gr["canonical"]["ref_low"],
                "c_ref_high": gr["canonical"]["ref_high"],
                "flag": p["flag"],
            }
        )
    nums = [s["canonical_value"] for s in series if isinstance(s["canonical_value"], (int, float))]
    deltas = [round(b - a, 4) for a, b in zip(nums, nums[1:])]
    series_str = " -> ".join(
        (f"{s['canonical_value']:g}" if isinstance(s["canonical_value"], (int, float)) else str(s["source_value"]))
        for s in series
    )
    if canonical_unit:
        series_str = f"{series_str} {canonical_unit}"
    return {
        "analyte": name,
        "loinc": loinc,
        "canonical_unit": canonical_unit,
        "series": series,
        "deltas": deltas,
        "series_str": series_str,
    }


def _fold_out_of_range(s: dict) -> float:
    """How far a point sits beyond its nearest reference bound (1.0 = at the bound,
    in range -> < 1.0). Used to find the worst excursion."""
    v = s["canonical_value"]
    if not isinstance(v, (int, float)):
        return 0.0
    hi, lo = s.get("c_ref_high"), s.get("c_ref_low")
    if hi is not None and v > hi and hi:
        return v / hi
    if lo is not None and v < lo and v:
        return lo / v
    return 0.0


def assess_trajectory(comparison: dict) -> dict:
    """Classify the harmonized numeric series and surface the worst excursion so a
    historical critical value (e.g. a 789 spike) is never hidden behind a bland
    shape label.

    classification: stable | rising | falling | fluctuating | resolved | insufficient
      - 'resolved' = there was a marked excursion (>=1.5x a bound) that has returned
        to range at the latest point (a critical spike that came down).
    `elevated` is true if any point is out of range. `peak` describes the worst point.
    """
    series = comparison["series"]
    nums = [s["canonical_value"] for s in series if isinstance(s["canonical_value"], (int, float))]
    elevated = any((s["flag"] or "normal") != "normal" for s in series)

    # Worst excursion across the series.
    worst = max(series, key=_fold_out_of_range) if series else None
    worst_fold = _fold_out_of_range(worst) if worst else 0.0
    peak = None
    if worst and worst_fold >= 1.5:
        direction = "above" if worst.get("c_ref_high") is not None and isinstance(worst["canonical_value"], (int, float)) and worst["canonical_value"] > worst["c_ref_high"] else "below"
        peak = {
            "value": worst["canonical_value"],
            "unit": worst["canonical_unit"],
            "date": worst["date"],
            "lab": worst["lab"],
            "fold": round(worst_fold, 1),
            "direction": direction,
        }

    latest_in_range = series[-1].get("in_range") if series else None

    if len(nums) < 2:
        classification = "insufficient"
    elif peak and latest_in_range and series[-1] is not worst:
        classification = "resolved"
    else:
        deltas = [b - a for a, b in zip(nums, nums[1:])]
        mean = sum(nums) / len(nums)
        eps = 0.015 * (abs(mean) or 1)
        spread = max(nums) - min(nums)
        if all(d > eps for d in deltas):
            classification = "rising"
        elif all(d < -eps for d in deltas):
            classification = "falling"
        elif spread <= 0.03 * (abs(mean) or 1):
            classification = "stable"
        else:
            classification = "fluctuating"
    return {
        "analyte": comparison["analyte"],
        "classification": classification,
        "elevated": elevated,
        "summary": comparison["series_str"],
        "peak": peak,
    }


def _peak_str(peak: Optional[dict]) -> Optional[str]:
    if not peak:
        return None
    v = peak["value"]
    vs = f"{v:g}" if isinstance(v, (int, float)) else str(v)
    bound = "upper" if peak["direction"] == "above" else "lower"
    where = f" on {peak['date']} ({peak['lab']})" if peak.get("date") else ""
    return f"peaked {vs} {peak['unit'] or ''} — ~{peak['fold']:g}x {bound} limit{where}"


def build_trajectory(comparison: dict, trajectory: dict) -> AnalyteTrajectory:
    # Only surface a peak callout for dramatic excursions (>=3x a bound) or a
    # resolved spike — otherwise it just duplicates "Now flagged" / "Elevated".
    pk = trajectory.get("peak")
    show_peak = pk and (trajectory["classification"] == "resolved" or pk["fold"] >= 3)
    return AnalyteTrajectory(
        analyte=comparison["analyte"],
        loinc=comparison["loinc"],
        canonical_unit=comparison["canonical_unit"],
        classification=trajectory["classification"],
        elevated=trajectory["elevated"],
        summary=comparison["series_str"],
        peak=_peak_str(pk) if show_peak else None,
        points=[TrajectoryPoint(**s) for s in comparison["series"]],
    )
