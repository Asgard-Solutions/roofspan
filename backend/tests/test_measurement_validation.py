from services.measurement_validation import build_warnings


def test_report_delta_missing_pitch_zero_area_and_uniform_pitch_are_soft_warnings():
    measurement = {
        "totals": {
            "reported_area_sqft": 1000, "total_area_sqft": 950, "reported_area_delta_sqft": -50,
            "edge_totals": {"valley_lf": 0},
        },
        "facets": [
            {"id": "1", "facet_label": "F1", "area_sqft": 250, "pitch_rise": 6},
            {"id": "2", "facet_label": "F2", "area_sqft": 250, "pitch_rise": 6},
            {"id": "3", "facet_label": "F3", "area_sqft": 250, "pitch_rise": 6},
            {"id": "4", "facet_label": "F4", "area_sqft": 200, "pitch_rise": 6},
            {"id": "5", "facet_label": "F5", "area_sqft": 0, "pitch_rise": None},
        ],
        "edges": [{"edge_type": "valley", "length_ft": 0}],
    }
    codes = {w["code"] for w in build_warnings(measurement)}
    assert "REPORTED_AREA_MISMATCH" in codes
    assert "VALLEY_LENGTH_MISSING" in codes
    assert "ZERO_AREA_FACET" in codes
    assert "UNIFORM_PITCH_SANITY" in codes
    assert "FACET_PITCH_MISSING" not in codes  # zero-area placeholder does not create a pitch warning


def test_positive_area_facet_without_pitch_warns():
    measurement = {
        "totals": {"edge_totals": {}, "total_area_sqft": 100},
        "facets": [{"id": "f1", "facet_label": "F1", "area_sqft": 100, "pitch_rise": None}],
        "edges": [],
    }
    warnings = build_warnings(measurement)
    assert any(w["code"] == "FACET_PITCH_MISSING" for w in warnings)


def test_clean_measurement_has_no_warnings():
    measurement = {
        "totals": {"reported_area_sqft": 1000, "total_area_sqft": 1000, "reported_area_delta_sqft": 0,
                   "edge_totals": {"valley_lf": 20}},
        "facets": [
            {"id": "1", "facet_label": "F1", "area_sqft": 500, "pitch_rise": 6},
            {"id": "2", "facet_label": "F2", "area_sqft": 500, "pitch_rise": 4},
        ],
        "edges": [{"edge_type": "valley", "length_ft": 20}],
    }
    assert build_warnings(measurement) == []
