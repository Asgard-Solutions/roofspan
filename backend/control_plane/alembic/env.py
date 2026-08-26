import os
import sys
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool, text

BACKEND_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if BACKEND_ROOT not in sys.path:
    sys.path.insert(0, BACKEND_ROOT)

from dotenv import load_dotenv

load_dotenv(os.path.join(BACKEND_ROOT, ".env"))

from control_plane.db import CPBase  # noqa: E402
import control_plane.models  # noqa: E402,F401
from control_plane.config import CONTROL_PLANE_DATABASE_URL, CONTROL_PLANE_SCHEMA  # noqa: E402

config = context.config
if config.config_file_name is not None and config.attributes.get("configure_logger", True):
    fileConfig(config.config_file_name)

target_metadata = CPBase.metadata


def _sync_url() -> str:
    url = os.environ.get("CONTROL_PLANE_DATABASE_URL") or CONTROL_PLANE_DATABASE_URL
    return url.replace("+asyncpg", "+psycopg")


def _target_schema() -> str | None:
    return config.attributes.get("target_schema") or CONTROL_PLANE_SCHEMA


def _configure(connection=None, *, offline: bool = False) -> None:
    kwargs = {
        "target_metadata": target_metadata,
        "compare_type": True,
        # Alembic's schema_translate_map support is not sufficient for schema-level migrations. The
        # runner sets PostgreSQL search_path on this exact connection instead.
        "include_schemas": False,
    }
    schema = _target_schema()
    if schema:
        kwargs["version_table_schema"] = config.attributes.get("version_table_schema") or schema
    if offline:
        kwargs.update(
            url=_sync_url(),
            literal_binds=True,
            dialect_opts={"paramstyle": "named"},
        )
    else:
        kwargs["connection"] = connection
    context.configure(**kwargs)


def _apply_schema_target(connection) -> None:
    schema = _target_schema()
    if not schema:
        return
    quoted = connection.dialect.identifier_preparer.quote(schema)
    connection.execute(text(f"SET search_path TO {quoted}"))
    connection.commit()
    connection.dialect.default_schema_name = schema


def run_migrations_offline() -> None:
    _configure(offline=True)
    with context.begin_transaction():
        context.run_migrations()


def _run_with_connection(connection) -> None:
    _configure(connection)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    external_connection = config.attributes.get("connection")
    if external_connection is not None:
        # migrations_runner already set search_path, default_schema_name, and advisory locking on this
        # same connection. Reusing it prevents inspection/stamping/upgrading different schemas.
        _run_with_connection(external_connection)
        return

    section = config.get_section(config.config_ini_section) or {}
    section["sqlalchemy.url"] = _sync_url()
    connectable = engine_from_config(section, prefix="sqlalchemy.", poolclass=pool.NullPool)
    with connectable.connect() as connection:
        _apply_schema_target(connection)
        _run_with_connection(connection)


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
