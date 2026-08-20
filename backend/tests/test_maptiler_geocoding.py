from maptiler import best_address_feature


def _result(*, address="1985", relevance=0.99, place_type=None, coords=None):
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "id": "address.test",
                "type": "Feature",
                "place_type": place_type or ["address"],
                "address": address,
                "relevance": relevance,
                "geometry": {
                    "type": "Point",
                    "coordinates": coords or [-97.6706, 35.1200],
                },
            }
        ],
    }


def test_accepts_high_confidence_house_number_address():
    feature = best_address_feature(_result())
    assert feature is not None
    assert feature["address"] == "1985"


def test_rejects_street_level_address_without_house_number():
    assert best_address_feature(_result(address="")) is None


def test_rejects_low_relevance_address():
    assert best_address_feature(_result(relevance=0.50)) is None


def test_rejects_non_address_feature():
    assert best_address_feature(_result(place_type=["road"])) is None


def test_rejects_invalid_coordinates():
    assert best_address_feature(_result(coords=[999, 999])) is None
