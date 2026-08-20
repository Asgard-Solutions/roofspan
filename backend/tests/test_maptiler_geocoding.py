from maptiler import best_address_feature, evaluate_address_result


QUERY = "1985 S County Line Ave, Blanchard, OK 73010"


def _feature(
    *,
    address="1985",
    street="S County Line Avenue",
    city="Blanchard",
    state="Oklahoma",
    zip_code="73010",
    relevance=0.99,
    place_type=None,
    coords=None,
):
    return {
        "id": f"address.{address or 'none'}",
        "type": "Feature",
        "place_type": place_type or ["address"],
        "address": address,
        "text": street,
        "place_name": f"{address} {street}, {city}, {state} {zip_code}",
        "relevance": relevance,
        "geometry": {
            "type": "Point",
            "coordinates": coords or [-97.6706, 35.1200],
        },
        "context": [
            {"id": "postal_code.73010", "text": zip_code},
            {"id": "municipality.blanchard", "text": city},
            {"id": "region.oklahoma", "text": state},
            {"id": "country.us", "text": "United States", "country_code": "us"},
        ],
    }


def _result(*features):
    return {"type": "FeatureCollection", "features": list(features)}


def test_accepts_exact_property_address_identity_with_normalized_suffix():
    diagnostic = evaluate_address_result(_result(_feature()), query_address=QUERY)
    assert diagnostic["status"] == "accepted"
    assert diagnostic["reason"] == "exact_address_identity"
    assert diagnostic["identity_checks"] == {
        "house_number": True,
        "street": True,
        "city": True,
        "state": True,
        "zip_code": True,
    }


def test_accepts_directional_and_suffix_equivalents():
    feature = best_address_feature(
        _result(_feature(street="South County Line Avenue")),
        query_address="1985 S County Line Ave, Blanchard, OK 73010",
    )
    assert feature is not None


def test_rejects_neighboring_house_number():
    diagnostic = evaluate_address_result(_result(_feature(address="1987")), query_address=QUERY)
    assert diagnostic["feature"] is None
    assert diagnostic["reason"] == "house_number_mismatch"


def test_rejects_wrong_street_even_with_same_house_number_zip():
    diagnostic = evaluate_address_result(
        _result(_feature(street="S Main St")),
        query_address=QUERY,
    )
    assert diagnostic["feature"] is None
    assert diagnostic["reason"] == "street_mismatch"


def test_rejects_wrong_zip():
    diagnostic = evaluate_address_result(_result(_feature(zip_code="73089")), query_address=QUERY)
    assert diagnostic["feature"] is None
    assert diagnostic["reason"] == "zip_mismatch"


def test_rejects_wrong_city():
    diagnostic = evaluate_address_result(_result(_feature(city="Newcastle")), query_address=QUERY)
    assert diagnostic["feature"] is None
    assert diagnostic["reason"] == "city_mismatch"


def test_rejects_wrong_state():
    diagnostic = evaluate_address_result(_result(_feature(state="Texas")), query_address=QUERY)
    assert diagnostic["feature"] is None
    assert diagnostic["reason"] == "state_mismatch"


def test_chooses_exact_candidate_when_first_candidate_is_wrong_property():
    wrong = _feature(address="1987", relevance=1.0)
    exact = _feature(address="1985", relevance=0.95)
    diagnostic = evaluate_address_result(_result(wrong, exact), query_address=QUERY)
    assert diagnostic["status"] == "accepted"
    assert diagnostic["feature"]["address"] == "1985"


def test_rejects_street_level_address_without_house_number():
    assert best_address_feature(_result(_feature(address=""))) is None


def test_rejects_low_relevance_address():
    assert best_address_feature(_result(_feature(relevance=0.50))) is None


def test_rejects_non_address_feature():
    assert best_address_feature(_result(_feature(place_type=["road"]))) is None


def test_rejects_invalid_coordinates():
    assert best_address_feature(_result(_feature(coords=[999, 999]))) is None
