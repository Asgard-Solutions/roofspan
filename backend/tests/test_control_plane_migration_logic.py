"""Pure migration-state classification regressions."""
from control_plane import migrations_runner as runner


def _state(tables, columns=None):
    return {"tables": set(tables), "columns": {k: set(v) for k, v in (columns or {}).items()}}


def test_valid_baseline_with_data_can_upgrade_even_when_head_tables_are_absent():
    state = _state(runner.BASELINE_TABLES, {"subscriptions": set()})
    assert runner._schema_matches_revision(state, runner.REV_BASELINE) is True
    assert runner._infer_known_revision(state) == runner.REV_BASELINE


def test_known_revision_requires_its_own_markers_not_future_markers():
    tables = set(runner.BASELINE_TABLES) | {"billing_events"}
    state = _state(tables, {"subscriptions": set()})
    assert runner._schema_matches_revision(state, runner.REV_BILLING_EVENTS) is True
    assert runner._schema_matches_revision(state, runner.REV_SUBSCRIPTION_FIELDS) is False


def test_head_requires_pairing_binding_columns():
    tables = set(runner.REQUIRED_TABLES)
    columns = {
        "subscriptions": set(runner.REQUIRED_COLUMNS["subscriptions"]),
        "mobile_devices": {"credential_hash"},
        "pairing_tokens": set(),
    }
    state = _state(tables, columns)
    assert runner._schema_matches_revision(state, runner.REV_DEVICE_CREDENTIAL) is True
    assert runner._schema_matches_revision(state, runner.REV_USER_BINDING) is False


def test_partial_future_migration_markers_are_not_adopted_or_replayed():
    tables = set(runner.BASELINE_TABLES) | {"billing_events"}
    columns = {"subscriptions": {"pending_seats"}}
    state = _state(tables, columns)
    assert runner._infer_known_revision(state) is None
    assert runner._schema_matches_revision(state, runner.REV_BILLING_EVENTS) is False


def test_recorded_old_revision_with_later_table_is_drift_not_safe_upgrade():
    tables = set(runner.BASELINE_TABLES) | {"billing_events", "pairing_tokens"}
    state = _state(tables, {"subscriptions": set(), "pairing_tokens": set()})
    assert runner._schema_matches_revision(state, runner.REV_BILLING_EVENTS) is False
