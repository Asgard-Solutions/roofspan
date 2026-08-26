# RoofSpan Office Mobile Access — Control Plane Readiness Runbook

## Purpose

This runbook covers the embedded Control Plane used by **Users → Mobile Access → Connect Mobile Device**.
Ordinary Office workflows remain available if the Control Plane is unavailable, but activation and pairing
must fail closed until storage migration and readiness validation succeed.

## Supported storage modes

| Mode | Database | Schema | Used by |
|---|---|---|---|
| `database` | `roofspan_control_plane` | `public` | Fresh Windows installs and hosted Control Plane |
| `schema` | `roofspan` | `roofspan_control_plane` | Legacy Windows installs without retained `pg_super.bin` |

The runtime `roofspan` PostgreSQL role remains `NOSUPERUSER NOCREATEDB` in both modes.

## Safe diagnostics

The running Office service exposes:

- `GET /api/version` — Office version, build Git SHA, and Control Plane migration identity.
- `GET /api/health/control-plane` — safe readiness state; HTTP 200 when ready, HTTP 503 otherwise.
- `GET /api/control-plane/ready` — embedded Control Plane readiness; HTTP 200/503.

The authoritative service log is:

```text
C:\ProgramData\RoofSpan\logs\backend-service.log
```

Readiness responses and Office toasts never include database URLs, credentials, private keys, raw SQL, or
tracebacks. Full exceptions remain in the service log.

## Read-only PostgreSQL forensic queries

Run these only through an authorized support session. They do not mutate data.

```sql
SELECT table_schema, table_name
FROM information_schema.tables
WHERE table_name IN (
    'alembic_version', 'companies', 'installations', 'licenses', 'subscriptions',
    'signing_keys', 'version_policy', 'billing_events', 'pairing_tokens',
    'mobile_devices', 'request_nonces', 'cp_audit_logs', 'entitlement_issuances'
)
ORDER BY table_schema, table_name;
```

```sql
SELECT version_num
FROM roofspan_control_plane.alembic_version;
```

The `public.alembic_version` table in the business database belongs to the Office business schema and must
not be mistaken for the Control Plane version table.

## Automated damaged-state handling

At startup the Control Plane migration runner classifies the target storage:

- Empty storage: migrate from base to head.
- Complete storage at head: no mutation.
- Recognizable unversioned storage: stamp the highest proven migration milestone, then upgrade.
- Incomplete/incorrect storage with **zero Control Plane rows**: archive the damaged schema/objects under a
  timestamped `*_broken_*` schema, create clean storage, migrate, and validate.
- Incomplete/incorrect storage containing Control Plane rows: do not drop, move, or rewrite customer data;
  report `manual_repair_required` and keep Mobile Access unavailable.

Control Plane-looking tables accidentally left in `public` by a historical faulty migration are reported as
a warning and preserved for forensics. They are not automatically deleted.

## Release acceptance

A customer release is blocked unless CI proves both packaged Windows paths:

1. Fresh install with retained PostgreSQL superuser secret and a dedicated Control Plane database.
2. Legacy upgrade without `pg_super.bin`, using the isolated schema fallback.

Each path must prove migration head, required tables/columns, activation, signed user-bound pairing, device
resolution/listing/revocation, restart idempotency, least-privilege PostgreSQL role, packaged migration
assets, and a non-development build Git SHA.
