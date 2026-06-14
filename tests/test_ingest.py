from corux.ingest import ingest


def test_ingest_parses_and_sorts_panels():
    doc = ingest(
        {
            "patient": {"patient_id": "A", "sex": "male", "age_years": 35},
            "panels": [
                {"panel_id": "p2", "collected_date": "2025-01-01",
                 "source_lab": {"name": "L"}, "results": []},
                {"panel_id": "p1", "collected_date": "2023-01-01",
                 "source_lab": {"name": "L"}, "results": []},
            ],
        }
    )
    assert [p.collected_date for p in doc.panels] == ["2023-01-01", "2025-01-01"]


def test_ingest_result_fields_and_qualitative_value():
    doc = ingest(
        {
            "patient": {"patient_id": "A", "sex": "female", "age_years": 50},
            "panels": [
                {
                    "panel_id": "p1",
                    "collected_date": "2025-01-01",
                    "source_lab": {"name": "L", "country": "US", "unit_system": "conventional"},
                    "results": [
                        {"name": "Glucose", "loinc": "1558-6", "value": 99, "unit": "mg/dL",
                         "ref_low": 70, "ref_high": 99, "flag": "normal"},
                        {"name": "HCV Ab", "loinc": "16128-1", "value": "negative",
                         "unit": None, "ref_low": None, "ref_high": None, "flag": "normal"},
                    ],
                }
            ],
        }
    )
    res = doc.panels[0].results
    assert res[0].name == "Glucose" and res[0].value == 99
    assert res[1].value == "negative"  # qualitative string preserved
    assert doc.panels[0].source_lab.unit_system == "conventional"


def test_ingest_from_sample_file():
    doc = ingest("data/sample_input.json")
    assert len(doc.panels) == 2
    assert doc.panels[0].collected_date == "2024-03-10"  # sorted oldest first
