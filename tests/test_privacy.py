from corux.ingest import ingest
from corux.privacy import deidentify, patient_key


def test_patient_key_stable_and_anonymous():
    k1 = patient_key("PT-DEMO-0001")
    k2 = patient_key("PT-DEMO-0001")
    assert k1 == k2
    assert "PT-DEMO" not in k1  # raw id not exposed in the key
    assert len(k1) == 16


def test_deidentify_passes_through_context_not_id():
    doc = ingest("data/sample_input.json")  # age_years 53, female, has notes
    p = deidentify(doc)
    assert p.age_years == 53
    assert p.sex == "female"
    assert p.notes  # clinical notes carried for the agents
    # The pseudonymous patient_id is never carried on the de-identified view.
    assert not hasattr(p, "patient_id")
    assert "PT-DEMO" not in p.patient_key


def test_age_none_when_missing():
    doc = ingest(
        {
            "patient": {"patient_id": "X", "sex": "male"},
            "panels": [{"panel_id": "p1", "collected_date": "2025-01-01",
                        "source_lab": {"name": "L"}, "results": []}],
        }
    )
    p = deidentify(doc)
    assert p.age_years is None
