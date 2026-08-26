import os
import sys
from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool
from alembic import context

BACKEND_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if BACKEND_ROOT not in sys.path:
    sys.path.insert(0, BACKEND_ROOT)

from dotenv import load_dotenv

load_dotenv(os.path.join(BACKEND_ROOT, ".env"))

from control_plane.db import CPBase  # noqa: E402
import control_plane.models  # noqa: E402,F401
from control_plane.config import CONTROL_PLANE_DATABASE_URL, CONTROL_PLANE_SCHEMA  # noqa: E402

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = CPBase.metadata


def _sync_url() -> str:
    url = os.environ.get("CONTROL_PLANE_DATABASE_URL") or CONTROL_PLANE_DATABASE_URL
    return url.replace("+asyncpg", "+psycopg")


def _configure_kwargs() -> dict:
    kwargs = {"target_metadata": target_metadata, "compare_type": True}
    if CONTROL_PLANE_SCHEMA:
        kwargs.update(
            include_schemas=True,
            version_table_schema=CONTROL_PLANE_SCHEMA,
            render_as_batch=False,
        )
    return kwargs


def run_migrations_offline() -> None:
    kwargs = _configure_kwargs()
    kwargs.update(url=_sync_url(), literal_binds=True, dialect_opts={"paramstyle": "named"})
    if CONTROL_PLANE_SCHEMA:
        kwargs["schema_translate_map"] = {None: CONTROL_PLANE_SCHEMA}
    context.configure(**kwargs)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    section = config.get_section(config.config_ini_section) or {}
    section["sqlalchemy.url"] = _sync_url()
    connectable = engine_from_config(section, prefix="sqlalchemy.", poolclass=pool.NullPool)
    if CONTROL_PLANE_SCHEMA:
        connectable = connectable.execution_options(schema_translate_map={None: CONTROL_PLANE_SCHEMA})
    with connectable.connect() as connection:
        kwargs = _configure_kwargs()
        kwargs["connection"] = connection
        context.configure(**kwargs)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
