from geocodio import evaluate_geocodio_results, make_query


def _expected():
    return {
        "house_number": "1127",
        "street": "sw 22nd st",
        "city": "blanchard",
        "state": "ok",
        "zip_code": "73010",
    }


def _candidate(*, accuracy_type="rooftop", accuracy=1.0, city="Blanchard", postal_code="73010"):
    return {
        "address_components": {
            "number": "1127",
            "predirectional": "SW",
            "street": "22nd",
            "suffix": "St",
            "formatted_street": "SW 22nd St",
            "city": city,
            "state_province": "OK",
            "postal_code": postal_code,
            "country": "US",
        },
        "formatted_address": f"1127 SW 22nd St, {city}, OK {postal_code}",
        "location": {"lat": 35.123, "lng": -97.456},
        "accuracy": accuracy,
        "accuracy_type": accuracy_type,
        "match_type": "building_centroid",
        "source": "Oklahoma",
        "stable_address_key": "gcod_test",
    }


def test_structured_query_uses_stored_rentcast_components():
    query, expected = make_query({
        "id": "p1",
        "address_line1": "1127 Southwest 22nd Street",
        "city": "Blanchard",
        "state": "OK",
        "zip_code": "73010",
    })
    assert query == {
        "street": "1127 Southwest 22nd Street",
        "city": "Blanchard",
        "state_province": "OK",
        "postal_code": "73010",
        "country": "US",
    }
    assert expected == _expected()


def test_rooftop_known_address_is_accepted():
    result = evaluate_geocodio_results([_candidate()], _expected())
    assert result["status"] == "located"
    assert result["reason"] == "known_address_located"
    assert result["accuracy_type"] == "rooftop"
    assert result["location_quality"] == "high"


def test_directional_and_suffix_variants_still_match():
    candidate = _candidate()
    candidate["address_components"].update({
        "predirectional": "Southwest",
        "suffix": "Street",
        "formatted_street": "Southwest 22nd Street",
    })
    result = evaluate_geocodio_results([candidate], _expected())
    assert result["status"] == "located"


def test_wrong_city_is_rejected_even_with_rooftop_accuracy():
    result = evaluate_geocodio_results([_candidate(city="Newcastle", postal_code="73065")], _expected())
    assert result["status"] == "rejected"
    assert result["reason"] in {"city_mismatch", "zip_mismatch"}


def test_street_center_is_not_used_as_property_pin():
    result = evaluate_geocodio_results([_candidate(accuracy_type="street_center")], _expected())
    assert result["status"] == "rejected"
    assert result["reason"] == "insufficient_precision"


def test_range_interpolation_is_accepted_but_marked_approximate():
    result = evaluate_geocodio_results([_candidate(accuracy_type="range_interpolation", accuracy=0.95)], _expected())
    assert result["status"] == "located"
    assert result["location_quality"] == "approximate"


def test_low_accuracy_is_rejected():
    result = evaluate_geocodio_results([_candidate(accuracy=0.60)], _expected())
    assert result["status"] == "rejected"
    assert result["reason"] == "low_accuracy"
