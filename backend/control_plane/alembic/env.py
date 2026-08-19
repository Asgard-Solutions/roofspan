import os
import sys
from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool
from alembic import context

# Make the backend package importable (control_plane.db/models) and load .env.
BACKEND_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if BACKEND_ROOT not in sys.path:
    sys.path.insert(0, BACKEND_ROOT)

from dotenv import load_dotenv

load_dotenv(os.path.join(BACKEND_ROOT, ".env"))

from control_plane.db import CPBase  # noqa: E402
import control_plane.models  # noqa: E402,F401  (registers CP tables on CPBase.metadata)
from control_plane.config import CONTROL_PLANE_DATABASE_URL, _normalize_async  # noqa: E402

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = CPBase.metadata


def _sync_url() -> str:
    # Alembic runs synchronously. Normalize whatever form the env provides (Railway hands out
    # 'postgresql://' / 'postgres://' with NO driver) to the async form first, THEN swap the driver to
    # psycopg. Reading the raw env without normalizing previously left a driver-less URL that SQLAlchemy
    # routed to the (uninstalled) psycopg2 driver and hung/failed on connect.
    raw = os.environ.get("CONTROL_PLANE_DATABASE_URL") or CONTROL_PLANE_DATABASE_URL
    return _normalize_async(raw).replace("+asyncpg", "+psycopg")


def run_migrations_offline() -> None:
    context.configure(url=_sync_url(), target_metadata=target_metadata, literal_binds=True,
                      compare_type=True, dialect_opts={"paramstyle": "named"})
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    section = config.get_section(config.config_ini_section) or {}
    section["sqlalchemy.url"] = _sync_url()
    # Bound connect + guard statement/lock time so `command.upgrade` can't hang forever on Railway; the
    # cp_asgi startup retry loop can then actually receive an exception and retry.
    connectable = engine_from_config(
        section, prefix="sqlalchemy.", poolclass=pool.NullPool,
        connect_args={"connect_timeout": 10,
                      "options": "-c lock_timeout=30000 -c statement_timeout=120000"},
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
