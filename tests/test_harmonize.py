import math

from corux import harmonize
from corux.ingest import ingest


def approx(a, b, tol=0.5):
    return abs(a - b) <= tol


def test_ggt_ukat_to_ul_headline():
    # The demo's headline conversion: 0.85 µkat/L x 60 = 51 U/L
    gr = harmonize.get_reference_ranges("Gamma-GT (GGT)", "2324-2", 0.85, "ukat/L", None, 0.92)
    assert gr["harmonized"] is True
    assert gr["canonical"]["unit"] == "U/L"
    assert approx(gr["canonical"]["value"], 51.0)
    # 0.85 < 0.92 source -> in range; harmonized range 0.92*60 = 55.2, 51 <= 55.2
    assert gr["in_range"] is True


def test_ul_passthrough_not_harmonized():
    gr = harmonize.get_reference_ranges("Gamma-GT (GGT)", "2324-2", 98, "U/L", None, 71)
    assert gr["harmonized"] is False
    assert gr["canonical"]["value"] == 98
    assert gr["in_range"] is False  # 98 > 71


def test_si_conversion_factors():
    # creatinine 80 µmol/L / 88.4 ≈ 0.905 mg/dL
    cr = harmonize.get_reference_ranges("Creatinine", "2160-0", 80, "umol/L", 62, 106)
    assert approx(cr["canonical"]["value"], 0.905, 0.02) and cr["canonical"]["unit"] == "mg/dL"
    # hemoglobin 9.1 mmol/L x 1.611 ≈ 14.66 g/dL
    hb = harmonize.get_reference_ranges("Hemoglobin", "718-7", 9.1, "mmol/L", 8.5, 10.9)
    assert approx(hb["canonical"]["value"], 14.66, 0.1) and hb["canonical"]["unit"] == "g/dL"
    # triglycerides 1.35 mmol/L x 88.57 ≈ 119.6 mg/dL
    tg = harmonize.get_reference_ranges("Triglycerides", "2571-8", 1.35, "mmol/L", None, 1.70)
    assert approx(tg["canonical"]["value"], 119.6, 1.0) and tg["canonical"]["unit"] == "mg/dL"


def test_qualitative_value_passthrough():
    gr = harmonize.get_reference_ranges("eGFR", "62238-1", ">90", "mL/min/1.73m2", 90, None, flag="normal")
    assert gr["harmonized"] is False
    assert gr["canonical"]["value"] is None
    assert gr["in_range"] is True  # falls back to flag


def test_compare_and_trajectory_ggt_fluctuating():
    doc = ingest("data/mark_hahnfeld.json")
    tracked = {e["loinc"] or e["name"].lower(): e for e in harmonize.select_tracked(doc.panels)}
    ggt = tracked["2324-2"]
    cmp = harmonize.compare_to_prior(ggt)
    canon = [s["canonical_value"] for s in cmp["series"]]
    assert [round(c) for c in canon] == [94, 51, 98]  # 94 U/L, 0.85 µkat/L->51, 98 U/L
    assert cmp["canonical_unit"] == "U/L"
    traj = harmonize.assess_trajectory(cmp)
    assert traj["classification"] == "fluctuating"
    assert traj["elevated"] is True


def test_mcv_rising_macrocytosis():
    doc = ingest("data/mark_hahnfeld.json")
    tracked = {e["loinc"] or e["name"].lower(): e for e in harmonize.select_tracked(doc.panels)}
    mcv = harmonize.assess_trajectory(harmonize.compare_to_prior(tracked["787-2"]))
    assert mcv["classification"] == "rising"
    assert mcv["elevated"] is True


def test_tg_spike_classified_resolved_with_peak():
    # Triglycerides 789 (PL) -> 1.35 mmol/L (DE) -> 140 mg/dL: a critical spike that resolved.
    doc = ingest("data/mark_hahnfeld.json")
    tracked = {e["loinc"] or e["name"].lower(): e for e in harmonize.select_tracked(doc.panels)}
    cmp = harmonize.compare_to_prior(tracked["2571-8"])
    tr = harmonize.assess_trajectory(cmp)
    assert tr["classification"] == "resolved"  # not bland "fluctuating"
    assert tr["peak"] is not None and tr["peak"]["value"] == 789.0
    assert tr["peak"]["fold"] >= 5  # ~7.9x upper limit (789 / 100)
    bt = harmonize.build_trajectory(cmp, tr)
    assert "789" in (bt.peak or "")
