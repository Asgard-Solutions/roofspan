"""Production-safe Control Plane schema management.

RoofSpan normally stores Control Plane metadata in its own ``roofspan_control_plane`` database. Older
Windows installations may not retain the PostgreSQL superuser secret needed to create that database;
those installations use an isolated ``roofspan_control_plane`` schema inside the existing RoofSpan
business database.

Alembic migrations do not use ``schema_translate_map`` here. Schema fallback mode uses one SQLAlchemy
connection, PostgreSQL ``search_path``, the dialect default schema, and that same external connection
through inspection, stamping, migration, and validation.
"""
from __future__ import annotations
import logging
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import unquote, urlparse
import psycopg
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Connection
from sqlalchemy.pool import NullPool
from psycopg import sql
from control_plane.config import CONTROL_PLANE_DATABASE_URL, CONTROL_PLANE_SCHEMA

logger = logging.getLogger("roofspan")
_ROOT = Path(__file__).resolve().parent
_MIGRATION_LOCK_KEY = 918273
_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

REQUIRED_TABLES = frozenset({
    "companies", "cp_audit_logs", "entitlement_issuances", "request_nonces", "signing_keys",
    "version_policy", "installations", "licenses", "subscriptions", "billing_events",
    "mobile_devices", "pairing_tokens",
})
REQUIRED_COLUMNS = {
    "subscriptions": frozenset({
        "provider_subscription_id", "cancel_at_period_end", "current_period_end", "pending_seats",
        "pending_seats_effective_at", "grace_started_at",
    }),
    "mobile_devices": frozenset({"credential_hash", "expected_user_id", "expected_user_label"}),
    "pairing_tokens": frozenset({"expected_user_id", "expected_user_label"}),
}
REV_BASELINE = "5263a6bf173f"
REV_BILLING_EVENTS = "c716e38cdfa3"
REV_SUBSCRIPTION_FIELDS = "0b067e6d75cc"
REV_PAIRING_TABLES = "8d6a0d7b8949"
REV_PROVIDER_SUBSCRIPTION = "a1c4f9d2e7b3"
REV_DEVICE_CREDENTIAL = "b2d7e1f4a9c6"
REV_USER_BINDING = "e1f2a3b4c5d6"
BASELINE_TABLES = frozenset({
    "companies", "cp_audit_logs", "entitlement_issuances", "request_nonces", "signing_keys",
    "version_policy", "installations", "licenses", "subscriptions",
})


@dataclass
class MigrationReport:
    ready: bool = False
    storage_mode: str = "schema" if CONTROL_PLANE_SCHEMA else "database"
    target_schema: str = CONTROL_PLANE_SCHEMA or "public"
    migration_head: str | None = None
    current_revision: str | None = None
    state_before: str | None = None
    missing_tables: list[str] = field(default_factory=list)
    missing_columns: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    misplaced_public_tables: list[str] = field(default_factory=list)
    repair_action: str | None = None
    archived_schema: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


class ControlPlaneMigrationError(RuntimeError):
    def __init__(self, code: str, safe_message: str, *, report: MigrationReport | None = None):
        self.code = code
        self.safe_message = safe_message
        self.report = report or MigrationReport()
        super().__init__(safe_message)


def _validate_identifier(value: str) -> str:
    if not value or not _IDENTIFIER.fullmatch(value):
        raise ControlPlaneMigrationError(
            "invalid_storage_config", "RoofSpan Mobile Access storage configuration is invalid."
        )
    return value


def _sync_url() -> str:
    return CONTROL_PLANE_DATABASE_URL.replace("+asyncpg", "+psycopg")


def _conn_args() -> tuple[dict, str]:
    url = CONTROL_PLANE_DATABASE_URL.replace("+asyncpg", "").replace("+psycopg", "")
    parsed = urlparse(url)
    return ({
        "host": parsed.hostname,
        "port": parsed.port or 5432,
        "user": unquote(parsed.username or ""),
        "password": unquote(parsed.password or ""),
        "connect_timeout": 5,
    }, (parsed.path or "/").lstrip("/"))


def storage_mode() -> str:
    return "schema" if CONTROL_PLANE_SCHEMA else "database"


def target_schema() -> str:
    return _validate_identifier(CONTROL_PLANE_SCHEMA or "public")


def _config() -> Config:
    ini = _ROOT / "alembic.ini"
    script_location = _ROOT / "alembic"
    versions = script_location / "versions"
    if not ini.is_file() or not script_location.is_dir() or not versions.is_dir():
        raise ControlPlaneMigrationError(
            "migration_assets_missing",
            "RoofSpan Mobile Access migration files are missing from this Office installation.",
            report=MigrationReport(migration_head=None),
        )
    cfg = Config(str(ini))
    cfg.set_main_option("script_location", str(script_location))
    cfg.attributes["configure_logger"] = False
    return cfg


def get_migration_head() -> str:
    heads = ScriptDirectory.from_config(_config()).get_heads()
    if len(heads) != 1:
        raise ControlPlaneMigrationError(
            "migration_graph_invalid", "RoofSpan Mobile Access migration history is invalid."
        )
    return heads[0]


def ensure_database() -> None:
    args, dbname = _conn_args()
    try:
        with psycopg.connect(dbname=dbname, **args):
            return
    except psycopg.OperationalError as exc:
        if CONTROL_PLANE_SCHEMA or "does not exist" not in str(exc):
            raise ControlPlaneMigrationError(
                "database_unreachable", "RoofSpan Mobile Access cannot reach its PostgreSQL storage."
            ) from exc
    try:
        with psycopg.connect(dbname="postgres", autocommit=True, **args) as conn:
            conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(dbname)))
    except psycopg.Error as exc:
        raise ControlPlaneMigrationError(
            "database_missing", "RoofSpan Mobile Access storage has not been provisioned."
        ) from exc
    logger.info("Created Control Plane database '%s'", dbname)


def _quote(connection: Connection, identifier: str) -> str:
    return connection.dialect.identifier_preparer.quote(_validate_identifier(identifier))


def _commit_if_needed(connection: Connection) -> None:
    if connection.in_transaction():
        connection.commit()


def _create_target_schema(connection: Connection, schema: str) -> None:
    if schema != "public":
        connection.exec_driver_sql(
            f"CREATE SCHEMA IF NOT EXISTS {_quote(connection, schema)} AUTHORIZATION CURRENT_USER"
        )
        connection.commit()


def _set_target_schema(connection: Connection, schema: str) -> None:
    connection.exec_driver_sql(f"SET search_path TO {_quote(connection, schema)}")
    connection.commit()
    connection.dialect.default_schema_name = schema


def _table_names(connection: Connection, schema: str) -> set[str]:
    return set(inspect(connection).get_table_names(schema=schema))


def _columns(connection: Connection, schema: str, table: str) -> set[str]:
    if table not in _table_names(connection, schema):
        return set()
    return {column["name"] for column in inspect(connection).get_columns(table, schema=schema)}


def _read_revision(connection: Connection, schema: str) -> str | None:
    if "alembic_version" not in _table_names(connection, schema):
        return None
    rows = connection.exec_driver_sql(
        f"SELECT version_num FROM {_quote(connection, schema)}.{_quote(connection, 'alembic_version')}"
    ).fetchall()
    if not rows:
        return None
    if len(rows) != 1:
        raise ControlPlaneMigrationError(
            "migration_state_invalid", "RoofSpan Mobile Access migration state is inconsistent."
        )
    return str(rows[0][0])


def _row_count(connection: Connection, schema: str, table: str) -> int:
    return int(connection.exec_driver_sql(
        f"SELECT count(*) FROM {_quote(connection, schema)}.{_quote(connection, table)}"
    ).scalar_one())


def _inspect_storage(connection: Connection, schema: str, head: str,
                     report: MigrationReport) -> dict:
    tables = _table_names(connection, schema)
    columns = {table: _columns(connection, schema, table) for table in tables & REQUIRED_TABLES}
    revision = _read_revision(connection, schema)
    missing_tables = sorted(REQUIRED_TABLES - tables)
    missing_columns: list[str] = []
    for table, required in REQUIRED_COLUMNS.items():
        if table in tables:
            missing_columns.extend(
                f"{table}.{column}" for column in sorted(required - columns.get(table, set()))
            )
        else:
            missing_columns.extend(f"{table}.{column}" for column in sorted(required))

    cp_tables = sorted(tables & REQUIRED_TABLES)
    total_rows = 0
    populated_tables = []
    for table in cp_tables:
        count = _row_count(connection, schema, table)
        total_rows += count
        if count:
            populated_tables.append(table)

    misplaced = []
    if schema != "public":
        misplaced = sorted(_table_names(connection, "public") & REQUIRED_TABLES)
        if misplaced:
            report.warnings.append("misplaced_public_control_plane_tables")
            report.misplaced_public_tables = misplaced

    if not cp_tables and revision is None:
        state = "empty"
    elif revision == head and not missing_tables and not missing_columns:
        state = "complete"
    elif revision is None:
        state = "unversioned"
    elif revision == head:
        state = "head_incomplete"
    else:
        state = "versioned_incomplete" if missing_tables or missing_columns else "upgrade_required"
    return {
        "tables": tables,
        "columns": columns,
        "revision": revision,
        "missing_tables": missing_tables,
        "missing_columns": sorted(set(missing_columns)),
        "total_rows": total_rows,
        "populated_tables": populated_tables,
        "state": state,
        "misplaced_public_tables": misplaced,
    }


def _exact_known_revision(state: dict) -> str | None:
    tables: set[str] = state["tables"]
    columns: dict[str, set[str]] = state["columns"]
    if not BASELINE_TABLES.issubset(tables):
        return None
    subscription_fields = REQUIRED_COLUMNS["subscriptions"] - {"provider_subscription_id"}
    present_subscription_fields = subscription_fields & columns.get("subscriptions", set())
    pairing_tables = {"pairing_tokens", "mobile_devices"}
    present_pairing_tables = pairing_tables & tables
    provider_present = "provider_subscription_id" in columns.get("subscriptions", set())
    credential_present = "credential_hash" in columns.get("mobile_devices", set())
    binding_columns = {"expected_user_id", "expected_user_label"}
    mobile_bindings = binding_columns & columns.get("mobile_devices", set())
    token_bindings = binding_columns & columns.get("pairing_tokens", set())

    if "billing_events" not in tables:
        if (present_subscription_fields or present_pairing_tables or provider_present
                or credential_present or mobile_bindings or token_bindings):
            return None
        return REV_BASELINE
    if present_subscription_fields != subscription_fields:
        if (present_subscription_fields or present_pairing_tables or provider_present
                or credential_present or mobile_bindings or token_bindings):
            return None
        return REV_BILLING_EVENTS
    if present_pairing_tables != pairing_tables:
        if present_pairing_tables or provider_present or credential_present or mobile_bindings or token_bindings:
            return None
        return REV_SUBSCRIPTION_FIELDS
    if not provider_present:
        if credential_present or mobile_bindings or token_bindings:
            return None
        return REV_PAIRING_TABLES
    if not credential_present:
        if mobile_bindings or token_bindings:
            return None
        return REV_PROVIDER_SUBSCRIPTION
    if mobile_bindings or token_bindings:
        if mobile_bindings == binding_columns and token_bindings == binding_columns:
            return REV_USER_BINDING
        return None
    return REV_DEVICE_CREDENTIAL


def _infer_known_revision(state: dict) -> str | None:
    return _exact_known_revision(state)


def _schema_matches_revision(state: dict, revision: str) -> bool:
    return _exact_known_revision(state) == revision


def _unique_archive_name(connection: Connection, base: str) -> str:
    suffix = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    max_base = max(1, 63 - len(suffix) - len("_broken_"))
    candidate = f"{base[:max_base]}_broken_{suffix}"
    existing = set(inspect(connection).get_schema_names())
    counter = 1
    while candidate in existing:
        extra = f"_{counter}"
        candidate = f"{base[:max(1, 63 - len(suffix) - len('_broken_') - len(extra))]}_broken_{suffix}{extra}"
        counter += 1
    return _validate_identifier(candidate)


def _archive_zero_data_storage(connection: Connection, schema: str,
                               state: dict, report: MigrationReport) -> None:
    archive = _unique_archive_name(connection, schema if schema != "public" else "roofspan_cp")
    connection.exec_driver_sql(
        f"CREATE SCHEMA {_quote(connection, archive)} AUTHORIZATION CURRENT_USER"
    )
    tables_to_move = sorted(
        (state["tables"] & REQUIRED_TABLES)
        | ({"alembic_version"} if "alembic_version" in state["tables"] else set())
    )
    if schema == "public":
        for table in tables_to_move:
            connection.exec_driver_sql(
                f"ALTER TABLE {_quote(connection, schema)}.{_quote(connection, table)} "
                f"SET SCHEMA {_quote(connection, archive)}"
            )
    else:
        connection.exec_driver_sql(f"DROP SCHEMA {_quote(connection, archive)}")
        connection.exec_driver_sql(
            f"ALTER SCHEMA {_quote(connection, schema)} RENAME TO {_quote(connection, archive)}"
        )
        connection.exec_driver_sql(
            f"CREATE SCHEMA {_quote(connection, schema)} AUTHORIZATION CURRENT_USER"
        )
    connection.commit()
    report.repair_action = "archived_zero_data_storage_and_rebuilt"
    report.archived_schema = archive
    report.warnings.append("damaged_storage_archived")
    logger.warning(
        "Control Plane storage was inconsistent but contained no data; archived it as schema '%s' and rebuilding",
        archive,
    )
    _set_target_schema(connection, schema)


def _prepare_alembic_config(connection: Connection, schema: str) -> Config:
    cfg = _config()
    cfg.attributes["connection"] = connection
    cfg.attributes["target_schema"] = schema
    cfg.attributes["version_table_schema"] = schema
    return cfg


def _validate_complete(connection: Connection, schema: str, head: str,
                       report: MigrationReport) -> dict:
    state = _inspect_storage(connection, schema, head, report)
    report.current_revision = state["revision"]
    report.missing_tables = state["missing_tables"]
    report.missing_columns = state["missing_columns"]
    if state["revision"] != head or state["missing_tables"] or state["missing_columns"]:
        raise ControlPlaneMigrationError(
            "schema_validation_failed",
            "RoofSpan Mobile Access database migration did not complete successfully.",
            report=report,
        )
    return state


def run_cp_migrations() -> dict:
    report = MigrationReport()
    try:
        ensure_database()
        head = get_migration_head()
        schema = target_schema()
        report.migration_head = head
        report.target_schema = schema
        report.storage_mode = storage_mode()
        engine = create_engine(_sync_url(), poolclass=NullPool, future=True)
        try:
            with engine.connect() as connection:
                connection.execute(text("SELECT pg_advisory_lock(:key)"), {"key": _MIGRATION_LOCK_KEY})
                connection.commit()
                try:
                    _create_target_schema(connection, schema)
                    _set_target_schema(connection, schema)
                    cfg = _prepare_alembic_config(connection, schema)
                    script = ScriptDirectory.from_config(cfg)
                    known_revisions = {revision.revision for revision in script.walk_revisions()}
                    state = _inspect_storage(connection, schema, head, report)
                    report.state_before = state["state"]
                    report.current_revision = state["revision"]
                    report.missing_tables = state["missing_tables"]
                    report.missing_columns = state["missing_columns"]
                    logger.info(
                        "Control Plane migration inspection: mode=%s schema=%s state=%s revision=%s "
                        "head=%s missing_tables=%s missing_columns=%s",
                        report.storage_mode, schema, state["state"], state["revision"], head,
                        state["missing_tables"], state["missing_columns"],
                    )
                    _commit_if_needed(connection)

                    if state["state"] == "complete":
                        pass
                    elif state["state"] == "empty":
                        command.upgrade(cfg, "head")
                    elif state["state"] == "unversioned":
                        inferred = _infer_known_revision(state)
                        if inferred:
                            logger.warning(
                                "Adopting unversioned Control Plane storage at known revision %s; "
                                "customer rows are preserved", inferred,
                            )
                            command.stamp(cfg, inferred)
                            command.upgrade(cfg, "head")
                            report.repair_action = "adopted_unversioned_storage"
                        elif state["total_rows"] == 0:
                            _archive_zero_data_storage(connection, schema, state, report)
                            cfg = _prepare_alembic_config(connection, schema)
                            command.upgrade(cfg, "head")
                        else:
                            raise ControlPlaneMigrationError(
                                "manual_repair_required",
                                "RoofSpan Mobile Access storage contains unrecognized data and requires support repair.",
                                report=report,
                            )
                    elif state["revision"] not in known_revisions:
                        if state["total_rows"] == 0:
                            _archive_zero_data_storage(connection, schema, state, report)
                            cfg = _prepare_alembic_config(connection, schema)
                            command.upgrade(cfg, "head")
                        else:
                            raise ControlPlaneMigrationError(
                                "manual_repair_required",
                                "RoofSpan Mobile Access migration history is unrecognized and contains data.",
                                report=report,
                            )
                    elif state["revision"] != head and _schema_matches_revision(state, state["revision"]):
                        command.upgrade(cfg, "head")
                    elif state["state"] in {"head_incomplete", "versioned_incomplete"}:
                        if state["total_rows"] == 0:
                            _archive_zero_data_storage(connection, schema, state, report)
                            cfg = _prepare_alembic_config(connection, schema)
                            command.upgrade(cfg, "head")
                        else:
                            raise ControlPlaneMigrationError(
                                "manual_repair_required",
                                "RoofSpan Mobile Access storage is incomplete and contains data; "
                                "automatic repair was not attempted.",
                                report=report,
                            )
                    else:
                        command.upgrade(cfg, "head")

                    final_state = _validate_complete(connection, schema, head, report)
                    report.ready = True
                    report.current_revision = final_state["revision"]
                    report.missing_tables = []
                    report.missing_columns = []
                finally:
                    try:
                        _commit_if_needed(connection)
                        connection.execute(
                            text("SELECT pg_advisory_unlock(:key)"), {"key": _MIGRATION_LOCK_KEY}
                        )
                        connection.commit()
                    except Exception:
                        logger.exception("Failed to release Control Plane migration advisory lock")
        finally:
            engine.dispose()

        logger.info(
            "Control Plane migrations ready: mode=%s schema=%s revision=%s head=%s repair=%s warnings=%s",
            report.storage_mode, report.target_schema, report.current_revision,
            report.migration_head, report.repair_action, report.warnings,
        )
        return report.to_dict()
    except ControlPlaneMigrationError:
        raise
    except Exception as exc:
        logger.exception("Unexpected Control Plane migration failure")
        raise ControlPlaneMigrationError(
            "migration_failed", "RoofSpan Mobile Access database migration failed.", report=report
        ) from exc
