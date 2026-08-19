"""Control Plane database (its own engine/session; separate from the business DB)."""
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import DeclarativeBase

from control_plane.config import CONTROL_PLANE_DATABASE_URL

engine = create_async_engine(
    CONTROL_PLANE_DATABASE_URL, pool_pre_ping=True, echo=False,
    # Bound connect + per-statement time so a stuck DB can't hang the async engine (e.g. /health probe).
    connect_args={"timeout": 10, "command_timeout": 30},
)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


class CPBase(DeclarativeBase):
    pass


async def get_cp_db():
    async with SessionLocal() as session:
        yield session
