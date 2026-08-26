"""Control Plane database/session setup.

The normal deployment uses a dedicated database. Legacy Windows installations may use an isolated
schema in the existing RoofSpan database. Runtime ORM statements use ``schema_translate_map`` for that
fallback; Alembic migration routing is handled separately with PostgreSQL ``search_path``.
"""
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from control_plane.config import CONTROL_PLANE_DATABASE_URL, CONTROL_PLANE_SCHEMA

_engine_kwargs = {"pool_pre_ping": True, "echo": False}
if CONTROL_PLANE_SCHEMA:
    _engine_kwargs["execution_options"] = {"schema_translate_map": {None: CONTROL_PLANE_SCHEMA}}

engine = create_async_engine(CONTROL_PLANE_DATABASE_URL, **_engine_kwargs)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


class CPBase(DeclarativeBase):
    pass


async def get_cp_db():
    """FastAPI dependency that fails Mobile/Control Plane work closed until validation passes."""
    from control_plane import readiness

    try:
        readiness.require_ready()
    except readiness.ControlPlaneUnavailable as exc:
        status = exc.status
        raise HTTPException(
            status_code=503,
            detail={
                "code": status.get("code", "control_plane_unavailable"),
                "message": status.get("message"),
            },
        ) from exc

    async with SessionLocal() as session:
        yield session
