"""Hermetic HTTP/clone lifecycle tests; never load or connect to a configured customer DB.

Run: PYTHONPATH=backend pytest -q backend/tests/test_mobile_new_revision.py
Requires the backend dependencies plus pytest, pytest-xdist, httpx and aiosqlite.
The disposable SQLite database adapts PostgreSQL UUID/JSONB types. It exercises actual
authentication, handlers, clone services and transactions, but cannot prove PostgreSQL
concurrent lock scheduling. The allocation test verifies the emitted FOR UPDATE query.
"""
import asyncio
import os
import uuid
from contextlib import asynccontextmanager
from datetime import timezone
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import DateTime, JSON, Uuid, event, func, select
from sqlalchemy.dialects import postgresql
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.types import TypeDecorator

# db.py constructs its engine at import; all requests below override get_db with our
# own disposable engine, regardless of a caller's DATABASE_URL.
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite://")

from core import create_access_token
from db import Base, get_db
from models import AuditLog, IdempotencyKey, Lead, MeasurementRevision, Photo, RelayOutboxEvent, User
from routers.mobile import router
from schemas_measurements import MeasurementRevisionIn
from services import measurements, measurement_sketches, office_outbox


class _FlexibleSQLiteUuid(Uuid):
    """Match asyncpg's acceptance of both UUID objects and UUID strings."""
    cache_ok = True

    def bind_processor(self, dialect):
        process = super().bind_processor(dialect)
        return lambda value: process(uuid.UUID(str(value)) if value is not None else None)


class _UTCDateTime(TypeDecorator):
    """SQLite drops timezone information; restore the production UTC representation."""
    impl = DateTime
    cache_ok = True

    def process_result_value(self, value, dialect):
        return value.replace(tzinfo=timezone.utc) if value is not None else None


@asynccontextmanager
async def _scenario(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "isolated-mobile-revision-test-secret")
    for table in Base.metadata.tables.values():
        for column in table.columns:
            if isinstance(column.type, UUID):
                monkeypatch.setattr(column, "type", column.type.with_variant(_FlexibleSQLiteUuid(), "sqlite"))
            elif isinstance(column.type, JSONB):
                monkeypatch.setattr(column, "type", column.type.with_variant(JSON(), "sqlite"))
            elif isinstance(column.type, DateTime) and column.type.timezone:
                monkeypatch.setattr(column, "type", column.type.with_variant(_UTCDateTime(), "sqlite"))
    engine = create_async_engine("sqlite+aiosqlite://")

    @event.listens_for(engine.sync_engine, "connect")
    def configure_sqlite(connection, _):
        connection.isolation_level = None
        connection.execute("PRAGMA foreign_keys=ON")

    @event.listens_for(engine.sync_engine, "begin")
    def begin(connection):
        connection.exec_driver_sql("BEGIN")

    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        async with sessions() as db:
            users = {}
            for role in ("sales", "other_sales", "owner", "viewer"):
                user = User(email=f"{role}@revision.test", password_hash="unused", full_name=role,
                            role="sales" if role == "other_sales" else role)
                db.add(user)
                users[role] = user
            await db.flush()
            leads, revisions = [], []
            for assigned in (users["sales"], users["sales"], users["other_sales"]):
                lead = Lead(name="Isolated roof", assigned_user_id=assigned.id)
                db.add(lead)
                await db.flush()
                rev = await measurements.create_revision(db, MeasurementRevisionIn.model_validate({
                    "lead_id": str(lead.id), "source": "office", "notes": "Keep the source",
                    "structures": [{"ref": "s1", "name": "Main roof"}],
                    "facets": [{"ref": "f1", "structure_ref": "s1", "facet_label": "F1", "area_sqft": 120, "pitch_rise": 6}],
                    "edges": [{"facet_ref": "f1", "edge_type": "eave", "length_ft": 20}],
                    "penetrations": [{"facet_ref": "f1", "pen_type": "pipe_boot", "quantity": 2}],
                    "summary": {"existing_layers": 2, "gutter_lf": 40},
                }), users["owner"])
                leads.append(lead)
                revisions.append(rev)
            original = await measurements.build_out(db, revisions[0])
            structure, facet, edge, penetration = [original[key][0]["id"] for key in ("structures", "facets", "edges", "penetrations")]
            document = {
                "schema_version": 1, "edit_mode": "connected_graph", "structure_id": structure,
                "vertices": [{"id": "v1", "x": 0, "y": 0}, {"id": "v2", "x": 10, "y": 0},
                             {"id": "v3", "x": 10, "y": 8}, {"id": "v4", "x": 0, "y": 8}],
                "edges": [{"id": "e1", "v1": "v1", "v2": "v2", "measurement_edge_id": edge},
                          {"id": "e2", "v1": "v2", "v2": "v3"}, {"id": "e3", "v1": "v3", "v2": "v4"},
                          {"id": "e4", "v1": "v4", "v2": "v1"}],
                "facets": [{"id": "f1", "edgeIds": ["e1", "e2", "e3", "e4"],
                            "vertexIds": ["v1", "v2", "v3", "v4"], "measurement_facet_id": facet}],
                "penetrations": [{"id": "p1", "facet": "f1", "measurement_penetration_id": penetration}],
            }
            await measurement_sketches.save_sketch(db, str(revisions[0].id), structure, edit_mode="connected_graph",
                document=document, schema_version=1, expected_version=None, user=users["owner"])
            db.add(Photo(object_path="isolated/test.jpg", record_type="measurement_structure", record_id=structure))
            for rev in revisions:
                await measurements.transition_status(db, rev, "office_verified", users["owner"])
                await measurements.transition_status(db, rev, "locked", users["owner"])
            await db.commit()

        app = FastAPI()
        app.include_router(router)

        async def isolated_db():
            async with sessions() as db:
                yield db

        app.dependency_overrides[get_db] = isolated_db
        async with AsyncClient(transport=ASGITransport(app=app, raise_app_exceptions=False), base_url="http://test") as client:
            headers = {name: {"Authorization": f"Bearer {create_access_token(str(user.id), user.email, user.role)}"} for name, user in users.items()}
            yield SimpleNamespace(client=client, sessions=sessions, headers=headers, users=users,
                                  source=str(revisions[0].id), other_source=str(revisions[1].id),
                                  other_rep_source=str(revisions[2].id), lead=leads[0])
    finally:
        await engine.dispose()


async def _clone(s, *, source=None, role="sales", key="test-new-revision"):
    headers = dict(s.headers[role])
    if key is not None:
        headers["Idempotency-Key"] = key
    return await s.client.post(f"/api/mobile/measurements/{source or s.source}/new-revision", headers=headers)


def test_clone_locked_roof_preserves_history_children_sketch_and_photos(monkeypatch):
    async def run():
        async with _scenario(monkeypatch) as s:
            source_path = f"/api/mobile/measurements/{s.source}"
            source_response = await s.client.get(source_path, headers=s.headers["sales"])
            assert source_response.status_code == 200, source_response.text
            before = source_response.json()
            response = await _clone(s)
            assert response.status_code == 201, response.text
            clone = response.json()
            assert clone["id"] != s.source
            assert clone["status"] == "draft" and clone["editable"] is True and clone["is_immutable"] is False
            assert clone["source"] == "field" and clone["supersedes_revision_id"] == s.source
            assert clone["revision_number"] == 2 and clone["set_id"] == before["set_id"]
            assert clone["created_by"] == "sales@revision.test"
            assert clone["summary"]["existing_layers"] == 2 and clone["totals"]["total_area_sqft"] == 120
            for key in ("structures", "facets", "edges", "penetrations"):
                assert clone[key][0]["id"] != before[key][0]["id"]
            structure, facet, edge, penetration = [clone[k][0]["id"] for k in ("structures", "facets", "edges", "penetrations")]
            assert clone["facets"][0]["structure_id"] == structure
            assert clone["edges"][0]["facet_id"] == clone["penetrations"][0]["facet_id"] == facet
            sketch_response = await s.client.get(f"/api/mobile/measurements/{clone['id']}/sketches/{structure}", headers=s.headers["sales"])
            assert sketch_response.status_code == 200, sketch_response.text
            document = sketch_response.json()["document"]
            assert document["structure_id"] == structure
            assert document["facets"][0]["measurement_facet_id"] == facet
            assert document["edges"][0]["measurement_edge_id"] == edge
            assert document["penetrations"][0]["measurement_penetration_id"] == penetration
            assert [v["id"] for v in document["vertices"]] == ["v1", "v2", "v3", "v4"]
            edited = dict(clone, notes="Updated in the field")
            for kind in ("structures", "facets", "edges", "penetrations"):
                edited[kind] = [dict(row, ref=row["id"]) for row in clone[kind]]
            edit_response = await s.client.put(f"/api/mobile/measurements/{clone['id']}", json=edited,
                                              headers={**s.headers["sales"], "If-Match": clone["updated_at"]})
            assert edit_response.status_code == 200, edit_response.text
            assert edit_response.json()["notes"] == "Updated in the field"
            assert (await s.client.get(source_path, headers=s.headers["sales"])).json() == before
            async with s.sessions() as db:
                photos = (await db.execute(select(Photo))).scalars().all()
                assert len(photos) == 2
                assert {p.record_id for p in photos} == {before["structures"][0]["id"], structure}
                assert {p.object_path for p in photos} == {"isolated/test.jpg"}
    asyncio.run(run())


def test_replay_returns_same_canonical_revision_and_single_atomic_event(monkeypatch):
    async def run():
        async with _scenario(monkeypatch) as s:
            first = await _clone(s)
            assert first.status_code == 201, first.text
            replay = await _clone(s)
            assert replay.status_code == 201, replay.text
            result = replay.json()
            assert result.pop("replayed") is True
            original = first.json()
            original.pop("replayed", None)
            assert result == original
            async with s.sessions() as db:
                assert await db.scalar(select(func.count()).select_from(MeasurementRevision)) == 4
                assert await db.scalar(select(func.count()).select_from(AuditLog)) == 1
                events = (await db.execute(select(RelayOutboxEvent))).scalars().all()
                assert len(events) == 1
                assert str(events[0].revision_id) == result["id"] and events[0].event_type == "measurement.new_revision"
                key = await db.get(IdempotencyKey, "test-new-revision")
                assert key.entity_id == result["id"] and key.request_fingerprint
    asyncio.run(run())


@pytest.mark.parametrize("role,source,expected", [
    ("sales", "other_rep_source", 403), ("other_sales", "source", 403), ("viewer", "source", 403),
])
def test_clone_enforces_field_role_and_source_ownership(monkeypatch, role, source, expected):
    async def run():
        async with _scenario(monkeypatch) as s:
            response = await _clone(s, role=role, source=getattr(s, source))
            assert response.status_code == expected, response.text
            async with s.sessions() as db:
                assert await db.scalar(select(func.count()).select_from(IdempotencyKey)) == 0
                assert await db.scalar(select(func.count()).select_from(MeasurementRevision)) == 3
    asyncio.run(run())


@pytest.mark.parametrize("key", [None, "", " " * 4, "a" * 129])
def test_clone_requires_nonempty_bounded_key(monkeypatch, key):
    async def run():
        async with _scenario(monkeypatch) as s:
            response = await _clone(s, key=key)
            assert response.status_code == 422, response.text
    asyncio.run(run())


@pytest.mark.parametrize("role,source", [("sales", "other_source"), ("owner", "source")])
def test_key_cannot_replay_for_another_source_or_authorized_user(monkeypatch, role, source):
    async def run():
        async with _scenario(monkeypatch) as s:
            assert (await _clone(s)).status_code == 201
            response = await _clone(s, role=role, source=getattr(s, source))
            assert response.status_code == 409, response.text
    asyncio.run(run())


def test_replay_rechecks_source_access_after_assignment_changes(monkeypatch):
    async def run():
        async with _scenario(monkeypatch) as s:
            assert (await _clone(s)).status_code == 201
            async with s.sessions() as db:
                lead = await db.get(Lead, s.lead.id)
                lead.assigned_user_id = s.users["other_sales"].id
                await db.commit()
            replay = await _clone(s)
            assert replay.status_code == 403, replay.text
    asyncio.run(run())


@pytest.mark.parametrize("field,value", [
    ("entity_type", "mobile_visit"), ("request_fingerprint", None), ("entity_id", "pending"),
])
def test_incompatible_or_incomplete_key_never_creates_another_revision(monkeypatch, field, value):
    async def run():
        async with _scenario(monkeypatch) as s:
            assert (await _clone(s)).status_code == 201
            async with s.sessions() as db:
                key = await db.get(IdempotencyKey, "test-new-revision")
                setattr(key, field, value)
                await db.commit()
            response = await _clone(s)
            assert response.status_code == 409, response.text
            async with s.sessions() as db:
                assert await db.scalar(select(func.count()).select_from(MeasurementRevision)) == 4
    asyncio.run(run())


def test_clone_requires_authentication_and_existing_source(monkeypatch):
    async def run():
        async with _scenario(monkeypatch) as s:
            response = await s.client.post(f"/api/mobile/measurements/{s.source}/new-revision",
                                           headers={"Idempotency-Key": "anonymous"})
            assert response.status_code == 401, response.text
            response = await _clone(s, source=str(uuid.uuid4()))
            assert response.status_code == 404, response.text
    asyncio.run(run())


def test_outbox_failure_rolls_back_clone_audit_and_key_then_retry_succeeds(monkeypatch):
    async def run():
        async with _scenario(monkeypatch) as s:
            real_emit = office_outbox.emit_for_revision

            async def fail_after_enqueue(*args, **kwargs):
                await real_emit(*args, **kwargs)
                raise RuntimeError("Injected outbox failure")

            monkeypatch.setattr(office_outbox, "emit_for_revision", fail_after_enqueue)
            response = await _clone(s)
            assert response.status_code == 500, response.text
            async with s.sessions() as db:
                assert await db.scalar(select(func.count()).select_from(MeasurementRevision)) == 3
                for model in (AuditLog, RelayOutboxEvent, IdempotencyKey):
                    assert await db.scalar(select(func.count()).select_from(model)) == 0
            monkeypatch.setattr(office_outbox, "emit_for_revision", real_emit)
            response = await _clone(s)
            assert response.status_code == 201, response.text
            assert response.json()["revision_number"] == 2
    asyncio.run(run())


def test_revision_allocation_locks_parent_before_reading_maximum(monkeypatch):
    async def run():
        async with _scenario(monkeypatch) as s:
            statements = []

            def capture(execute_state):
                statements.append(str(execute_state.statement.compile(dialect=postgresql.dialect())))

            async with s.sessions() as db:
                source = await db.get(MeasurementRevision, s.source)
                event.listen(db.sync_session, "do_orm_execute", capture)
                assert await measurements._next_revision_number(db, source.set_id) == 2
            lock = next((i for i, sql in enumerate(statements) if "measurement_sets" in sql and "FOR UPDATE" in sql), None)
            maximum = next(i for i, sql in enumerate(statements) if "max(" in sql)
            assert lock is not None and lock < maximum, statements
    asyncio.run(run())
