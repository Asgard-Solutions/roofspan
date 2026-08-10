# RoofSpan Office — Windows Installer & Updater Foundations

Target: **Windows 10/11 x64**. Installer tech: **WiX v4** (MSI wrapped by a Burn bundle → `RoofSpanSetup.exe`).
RoofSpan Office stays a **local** system: local FastAPI, local PostgreSQL, local UI, installation identity,
licensing client, outbound Relay tunnel, updater. This is NOT a cloud-hosted rewrite.

> Status: cross-platform **logic + tests are implemented and green in-container**. The actual MSI/EXE
> build, service execution, DB migration on a real box, and Authenticode signing are **HUMAN REQUIRED**
> (Windows + certificate). This folder provides the scaffolding, scripts, schema, and test plan.

## Layout
```
windows/
  updater/manifest.py      manifest schema, parse/validate, sha256, version compare, update decision
  updater/signing.py       Ed25519 UPDATE signing/verify (SEPARATE trust domain from entitlements)
  updater/orchestrator.py  check→verify→backup→migrate→healthcheck→complete/rollback + health logic
  release/publish.py       stable/versioned filenames, sha256, SIGNED manifest builder (no AWS upload)
  release/make_manifest.py CLI to emit signed latest.json
  installer/RoofSpan.wxs    WiX product (files, 3 services, preserved data, major-upgrade, first-run)
  installer/build.ps1       Windows build + sign + manifest (HUMAN REQUIRED to run)
  tests/test_updater.py     21 in-container tests (no native Windows)
```

## Installer components & Windows services
Binaries under `C:\Program Files\RoofSpan Office`; **mutable customer data under `C:\ProgramData\RoofSpan`**
(`pgdata`, `identity`, `logs`, `config`). Three minimal auto-start services, each under a restricted
`NT SERVICE\*` virtual account (not LocalSystem), with restart-on-failure:
- **RoofSpanBackend** — local FastAPI, binds `127.0.0.1` only (no inbound WAN ports).
- **RoofSpanRelayConnector** — outbound-only Secure Relay tunnel (the approved remote-Mobile path).
- **RoofSpanUpdateService** — periodic signed-update checks + safe apply.

## PostgreSQL strategy
Local, customer-owned data in `ProgramData\RoofSpan\pgdata`. The Burn bundle installs a pinned
PostgreSQL as a Windows service if not already present (EDB silent install), creates the RoofSpan role
+ database on first run, and stores the generated local DB password in `config` (machine-scoped, DPAPI).
**Data is preserved on upgrade and on uninstall by default** — the `pgdata` component is `Permanent`/
`NeverOverwrite`. A destructive "remove all RoofSpan data" is a separate, explicitly-confirmed bundle
option only. Upgrades never drop/recreate the DB.

## First-run / activation (no secrets in the installer)
Install → services start → browser opens `http://127.0.0.1:8001/` → the existing setup/login UI →
installation identity generated if absent → customer activates/connects the organization → signed
entitlement received → RoofSpan usable. The installer embeds **no** AWS/Stripe/RevenueCat/entitlement
private keys and **no** per-customer license. Activation is fully separate from installation.

## Update manifest (`downloads.roofspan.io/update/windows/latest.json`, manifest_version 1)
`version, minimum_supported_version, required, release_date, installer_url, sha256, signature,
release_notes`. CloudFront remains the only download layer (installer_url must be under
`downloads.roofspan.io`). The Control Plane `version_policy` stays the **commercial** min/recommended
authority; this manifest describes the **distributable artifact**. The updater reconciles both.

## Update signing & verification (separate trust domain)
Ed25519 over the domain-separated canonical manifest (`roofspan-windows-update-v1`). The updater embeds
**only the update public key**; the **update-signing private key is a distinct hierarchy from the
licensing entitlement key** and stays offline / out of installations and source control (HUMAN REQUIRED).
The updater never trusts URL/version alone — signature + SHA-256 are both required; tampered package,
tampered manifest, or wrong-key signatures are rejected (tested).

## Update apply, backup, migration, rollback, health
`orchestrator.run()`: verify manifest signature → version policy (required/optional/current) → download
from CloudFront → verify SHA-256 → **backup (DB + config + identity)** → quiesce → install files →
`alembic upgrade` → **resume + health-check** → complete. On install/migration/health failure →
**restore from the pre-update backup** and report `rolled_back` (never leaves a broken box, never
destroys customer data). Health = backend running, API responsive, PostgreSQL reachable, migrations at
head, licensing initializes, relay connector startable, UI reachable — success is NOT exit-code-0 alone.
DB schema rollback that isn't safely reversible is handled by restoring the backup, not by faking a
reverse migration.

## Required vs optional updates
`decide_update`: below `minimum_supported_version` → **required** (enforced per policy); newer flagged
`required` → **required**; newer non-required → **optional** (notify Owner/Admin, install at a practical
time). Background cadence for checks (not per request); a manual "Check for Updates" is planned.

## Upgrade / uninstall
WiX `MajorUpgrade` (stable `UpgradeCode`) upgrades in place — no second instance — preserving local DB,
installation identity, company/license binding, logs/config, and Mobile pairing records; **no
reactivation after a normal upgrade**. Uninstall removes binaries/services but keeps business data by
default.

## Logs
Install / update-check / download / verification / migration / service-restart / rollback logs under
`ProgramData\RoofSpan\logs`. Never log passwords, private keys, JWTs, device credentials, or
Stripe/RevenueCat secrets.

## HUMAN REQUIRED
- Run `build.ps1` on Windows with WiX v4 to produce the MSI/EXE; validate services/DB on a real box.
- Provision the **production update-signing keypair** (offline) + embed the public key in the updater.
- **Authenticode code-signing certificate** (EV/OV) for the EXE/MSI; build SmartScreen reputation.
- Upload artifacts to the approved private S3 behind CloudFront (`/latest/`, `/releases/`, `/update/windows/`).
- Native-Windows E2E: install, upgrade-preserves-data, service recovery, first-run activation, real
  update apply + rollback.
