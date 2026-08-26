"""Control Plane database (its own engine/session; separate from the business DB by default).

Legacy Windows installs that cannot create the dedicated Control Plane database may use the existing
RoofSpan database with CONTROL_PLANE_SCHEMA set. SQLAlchemy's schema_translate_map keeps CP tables
isolated from business tables without changing the model definitions.
"""
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
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
    async with SessionLocal() as session:
        yield session
