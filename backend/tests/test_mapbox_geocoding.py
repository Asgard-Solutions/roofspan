from mapbox_geocoding import evaluate_mapbox_result, make_query


def _record():
    return {
        "id": "1",
        "address_line1": "1127 SW 22nd St",
        "city": "Blanchard",
        "state": "OK",
        "zip_code": "73010",
        "rentcast_latitude": 35.1171,
        "rentcast_longitude": -97.6725,
    }


def _feature(*, accuracy="rooftop", confidence="exact", house="1127", street="Southwest 22nd Street", postcode="73010", place="Blanchard", region_code="OK", street_match="matched"):
    return {
        "type": "Feature",
        "id": "mapbox-address-id",
        "geometry": {"type": "Point", "coordinates": [-97.67, 35.12]},
        "properties": {
            "mapbox_id": "mapbox-address-id",
            "feature_type": "address",
            "name": f"{house} {street}",
            "full_address": f"{house} {street}, {place}, Oklahoma {postcode}, United States",
            "coordinates": {
                "longitude": -97.67,
                "latitude": 35.12,
                "accuracy": accuracy,
            },
            "match_code": {
                "address_number": "plausible" if accuracy == "interpolated" else "matched",
                "street": street_match,
                "postcode": "matched",
                "place": "matched",
                "region": "matched",
                "country": "inferred",
                "confidence": confidence,
            },
            "context": {
                "address": {"address_number": house, "street_name": street},
                "street": {"name": street},
                "postcode": {"name": postcode},
                "place": {"name": place},
                "region": {"name": "Oklahoma", "region_code": region_code},
                "country": {"name": "United States", "country_code": "US"},
            },
        },
    }


def test_structured_query_uses_known_rentcast_components_and_location_hints():
    query = make_query(_record(), bbox=[-98, 35, -97, 36])
    assert query["address_number"] == "1127"
    assert query["street"] == "sw 22nd st"
    assert query["place"] == "Blanchard"
    assert query["region"] == "OK"
    assert query["postcode"] == "73010"
    assert query["country"] == "us"
    assert query["types"] == ["address"]
    assert query["autocomplete"] is False
    assert query["proximity"] == [-97.6725, 35.1171]
    assert query["bbox"] == [-98, 35, -97, 36]


def test_rooftop_exact_match_is_located():
    result = evaluate_mapbox_result({"features": [_feature()]}, _record())
    assert result["status"] == "located"
    assert result["reason"] == "known_address_located"
    assert result["accuracy"] == "rooftop"
    assert result["confidence"] == "exact"
    assert result["location_quality"] == "high"


def test_parcel_and_point_are_high_quality():
    for accuracy in ("parcel", "point"):
        result = evaluate_mapbox_result({"features": [_feature(accuracy=accuracy, confidence="high")]}, _record())
        assert result["status"] == "located"
        assert result["location_quality"] == "high"


def test_interpolated_is_allowed_but_marked_approximate():
    result = evaluate_mapbox_result({"features": [_feature(accuracy="interpolated", confidence="high")]}, _record())
    assert result["status"] == "located"
    assert result["location_quality"] == "approximate"


def test_approximate_zip_centroid_is_rejected():
    result = evaluate_mapbox_result({"features": [_feature(accuracy="approximate")]}, _record())
    assert result["status"] == "rejected"
    assert result["reason"] == "insufficient_precision"


def test_low_confidence_is_rejected():
    result = evaluate_mapbox_result({"features": [_feature(confidence="low")]}, _record())
    assert result["status"] == "rejected"
    assert result["reason"] == "low_confidence"


def test_high_confidence_parcel_allows_rural_street_alias_when_other_identity_matches():
    record = {
        "id": "2",
        "address_line1": "1985 S County Line Ave",
        "city": "Blanchard",
        "state": "OK",
        "zip_code": "73010",
        "rentcast_latitude": 35.119961,
        "rentcast_longitude": -97.670637,
    }
    feature = _feature(
        accuracy="parcel",
        confidence="high",
        house="1985",
        street="N2990 Road",
        postcode="73010",
        place="Blanchard",
        region_code="OK",
        street_match="unmatched",
    )
    result = evaluate_mapbox_result({"features": [feature]}, record)
    assert result["status"] == "located"
    assert result["reason"] == "known_address_located_street_alias"
    assert result["street_alias_detected"] is True
    assert result["street_alias_expected"] == "s county line ave"
    assert result["street_alias_returned"] == "n2990 rd"


def test_street_alias_exception_does_not_apply_to_medium_confidence():
    record = {
        "id": "3",
        "address_line1": "1985 S County Line Ave",
        "city": "Blanchard",
        "state": "OK",
        "zip_code": "73010",
    }
    feature = _feature(
        accuracy="parcel",
        confidence="medium",
        house="1985",
        street="N2990 Road",
        street_match="unmatched",
    )
    result = evaluate_mapbox_result({"features": [feature]}, record)
    assert result["status"] == "rejected"
    assert result["reason"] == "street_mismatch"
