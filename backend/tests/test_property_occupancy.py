"""Regression tests for property occupancy status used by the map GeoJSON payload."""

from routers.properties import _occupancy_status


def test_occupancy_status_owned():
    assert _occupancy_status(True) == "owned"


def test_occupancy_status_rented():
    assert _occupancy_status(False) == "rented"


def test_occupancy_status_unknown():
    assert _occupancy_status(None) == "unknown"
