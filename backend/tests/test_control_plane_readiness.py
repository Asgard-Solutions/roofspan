"""Fast regression tests for the safe Control Plane readiness/error contract."""
from control_plane import readiness
from licensing import pairing_client


class _Response:
    def __init__(self, status_code, body):
        self.status_code = status_code
        self._body = body

    def json(self):
        return self._body


def setup_function():
    readiness.reset_for_tests()


def teardown_function():
    readiness.reset_for_tests()


def test_readiness_fails_closed_until_marked_ready():
    status = readiness.snapshot()
    assert status["ready"] is False
    try:
        readiness.require_ready()
    except readiness.ControlPlaneUnavailable as exc:
        assert exc.status["code"] == "initializing"
    else:
        raise AssertionError("readiness must fail closed")

    readiness.mark_ready({
        "storage_mode": "schema",
        "target_schema": "roofspan_control_plane",
        "migration_head": "e1f2a3b4c5d6",
        "current_revision": "e1f2a3b4c5d6",
        "warnings": [],
    })
    assert readiness.require_ready()["ready"] is True


def test_failed_status_never_requires_internal_exception_text():
    status = readiness.mark_failed(
        "schema_validation_failed",
        "RoofSpan Mobile Access database migration did not complete successfully.",
        {
            "storage_mode": "schema",
            "target_schema": "roofspan_control_plane",
            "migration_head": "head",
            "current_revision": "old",
            "missing_tables": ["companies"],
        },
    )
    assert status["ready"] is False
    assert status["code"] == "schema_validation_failed"
    assert status["missing_tables"] == ["companies"]
    assert "postgresql://" not in str(status).lower()


def test_pairing_client_prefers_safe_structured_message():
    response = _Response(503, {
        "detail": {
            "code": "migration_failed",
            "message": "RoofSpan Mobile Access is not initialized on this Office installation.",
            "internal": "should-not-be-rendered",
        }
    })
    assert pairing_client._safe_detail(response) == (
        "RoofSpan Mobile Access is not initialized on this Office installation."
    )


def test_pairing_client_withholds_raw_database_exception():
    response = _Response(500, {
        "detail": "sqlalchemy asyncpg password=bad postgresql://roofspan:bad@localhost/db"
    })
    detail = pairing_client._safe_detail(response)
    assert detail == "Control Plane returned HTTP 500 (details withheld for security)."
    assert "password" not in detail.lower()


def test_db_dependency_returns_safe_503_before_opening_a_session():
    from fastapi import Depends, FastAPI
    from fastapi.testclient import TestClient
    from control_plane.db import get_cp_db

    app = FastAPI()

    @app.get("/protected")
    async def protected(_db=Depends(get_cp_db)):
        return {"ok": True}

    readiness.mark_failed(
        "schema_validation_failed",
        "RoofSpan Mobile Access database migration did not complete successfully.",
    )
    response = TestClient(app).get("/protected")
    assert response.status_code == 503
    assert response.json()["detail"] == {
        "code": "schema_validation_failed",
        "message": "RoofSpan Mobile Access database migration did not complete successfully.",
    }
    assert "sqlalchemy" not in response.text.lower()
