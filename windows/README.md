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

## Runtime model (audit of what RoofSpan Office actually needs)
Packaged into the install (customer installs nothing manually):
- **Local backend** — FastAPI (`server:app`), bound to **127.0.0.1:8001** only. No public exposure, no
  inbound router/firewall rules; remote Mobile uses the **outbound Relay** only. Ships as a bundled
  Python runtime (e.g., embeddable CPython or a PyInstaller `roofspan-backend.exe`) — the customer does
  NOT install Python.
- **Frontend** — the **production build** of `/app/frontend` (`yarn build` → static assets). Served by the
  local backend at `http://127.0.0.1:8001/` (add a `StaticFiles` mount in the packaged backend; API stays
  under `/api`). The public `roofspan-website` is NOT included. No Node/yarn at runtime.
- **PostgreSQL** — local service (see below). **Relay connector** (outbound tunnel) and **update service**
  (signed-update checks). Config + installation identity under ProgramData.
- **Local browser URL** = **`http://127.0.0.1:8001/`** (existing configured port — not reinvented). The
  Start Menu/Desktop shortcut ensures services are up, then opens the default browser to that URL. The
  browser is not the app; the local services are.

## Authoritative version (single source)
`windows/VERSION` = **`0.1.0`** (numeric, MSI-compatible) with channel **`dev`** → display **`0.1.0-dev`**.
`windows/version.py` reads it and exposes `ROOFSPAN_VERSION` / `CHANNEL` / `DISPLAY_VERSION` +
`parse_version`/`is_valid_version`/`is_dev`. Consumers: `RoofSpan.wxs` `Version="$(var.Version)"`,
`build.ps1` defaults `-Version` from `VERSION`, `make_manifest.py` defaults `--version`/`--min-supported`
from it. The installed backend's `ROOFSPAN_VERSION` env is written from this file at install time (keeps
app / installer / updater / release artifacts on ONE version). This is a **DEV** version — not a claimed
1.0.0 production release. Responsibility boundary: **Control Plane `version_policy`** = supported/minimum/
recommended authority; the **CloudFront manifest** = downloadable-artifact metadata; the updater reconciles both.

## Update state machine (`updater/orchestrator.py`)
Terminal gates: **NOOP** (already current), **BLOCKED** (bad manifest signature or SHA-256 mismatch —
never proceeds). Apply path: **DOWNLOADED → VERIFIED → BACKED_UP → INSTALLING → MIGRATING →
HEALTH_CHECKING → COMPLETE**. Any failure after backup → **ROLLED_BACK** (backup restored) or **FAILED**
(restore also failed). `UpdateResult.final_state` + ordered `UpdateResult.states` are asserted in tests.
Success is never exit-code-0 alone: health = backend/api/pg/migrations/licensing/relay/ui.

## Automated tests (in-container, no native Windows) — `tests/test_updater.py` (30)
version parse/validate + DEV-channel; manifest parse/validate incl. CloudFront-only URL + **semver
validation** + `published_at` (with `release_date` alias); version compare; required/optional/current
decision; SHA-256 verify; signature valid/wrong-key/tampered-manifest/tampered-sha256; separate signing
domain; health all-pass/failures; orchestrator happy/noop/bad-sig-blocked/hash-mismatch-blocked/
migration-rollback/health-rollback; **explicit state-machine sequence** (COMPLETE order, ROLLED_BACK,
FAILED-when-restore-fails, BLOCKED, NOOP); release naming/URLs; signed-manifest roundtrip;
upload-is-HUMAN-REQUIRED.

## Windows-native test checklist (HUMAN REQUIRED — cannot run in this Linux container)
Clean **Windows 11 x64** (and Windows 10 x64 if practical): install → first-run browser launch →
PostgreSQL up + RoofSpan DB initialized → service restart → machine reboot (auto-start) → Relay connector
starts → **upgrade preserves DB + installation identity + license/company binding + Mobile pairing** →
uninstall preserves business data → reinstall → **tampered update rejected** → successful update →
**failed update rolls back** (data recoverable).

## Security (verified in logic; enforced by design)
No AWS/Stripe/RevenueCat/Control-Plane/update private keys, no per-customer license or static credentials
in the installer or release artifacts. Update-signing key is a distinct hierarchy from entitlement +
identity + Mobile credentials; installer embeds only the update **public** key. Sanitized logs (never
passwords, JWTs, installation private key, or Mobile credentials).

## Installer build path (now complete in committed code; native execution HUMAN REQUIRED)
Producing the installer on Windows is `stage.ps1` → `build.ps1`:
```
installer\stage.ps1 -StageDir ..\..\_stage -UpdatePublicKey <update_public_key.pem>
installer\build.ps1 -StageDir ..\..\_stage -PostgresInstaller <edb-postgresql-x64.exe> `
                    [-SignCertThumbprint <t>] [-UpdateSigningPrivateKey <priv.pem>]
```
- **`constants.wxi`** — PERMANENT product-family GUIDs (`RoofSpanUpgradeCode`, `BundleUpgradeCode`), shared
  by MSI + bundle. Never regenerate. Validated by `tests/test_installer_static.py`.
- **`RoofSpan.wxs`** (MSI) — valid `$(var.RoofSpanUpgradeCode)`; payload **harvested** via WiX v4 `<Files>`
  from the staged `frontend\ / runtime\ / config-templates\` trees; three restricted services keyed on the
  staged `services\*.exe`; ProgramData data dirs Permanent/NeverOverwrite; first-run opens
  `http://127.0.0.1:8001/`.
- **`bundle.wxs`** (Burn → `RoofSpanSetup.exe`) — bundle identity + `$(var.BundleUpgradeCode)`; chain =
  **EDB PostgreSQL silent prereq** (installed only when not already present via `PgPresent` registry
  detect; `Permanent` so uninstall never removes the customer DB) → **RoofSpan MSI**. No committed secrets
  (`PostgresInstaller`/`PgSuperPassword` are overridable install-time variables).
- **`winbuild\`** — PyInstaller specs + entry scripts producing `roofspan-backend.exe` /
  `roofspan-relay-connector.exe` / `roofspan-update-service.exe` (names come from `winbuild/targets.py`,
  cross-checked against the WiX authoring by the static tests). Backend exe serves the packaged Office
  frontend build via `ROOFSPAN_STATIC_DIR` (backend `static_serve.mount_frontend`, guarded — no-op in dev).
- **PostgreSQL**: EDB silent Burn prerequisite; detect-existing (no reinstall); RoofSpan first-run creates
  its own least-privilege role + DB with generated creds; data preserved on upgrade AND uninstall.
- **Update cadence**: 12h (`updater/service.CHECK_INTERVAL_SECONDS`) + a `plan_update()` foundation for a
  future in-Office "Check for Updates".
- **Fail-fast**: `build.ps1` throws if WiX/staged exes/frontend build/runtime/config/EDB installer are
  missing — no silent partial builds. `build_exes.ps1`/`stage.ps1` fail if PyInstaller/frontend build fail.
- **Version stays `0.1.0-dev`** — no stable 1.0.0 and the website download stays disabled until native
  build/install/upgrade/uninstall/update/rollback pass + Authenticode signing + verified CloudFront upload.

## Tests (in-container): `tests/` = **42** (`test_updater.py` 30 + `test_installer_static.py` 12)
Static suite asserts: bundle/installer files exist; WiX GUIDs valid + no `RS0FSPAN` placeholder; permanent
UpgradeCode + `$(var.Version)`; payload harvested (not empty scaffold); WiX service exes == build outputs
(+ entry script + spec per exe); bundle chains PostgreSQL prereq + MSI; build.ps1 fail-fast + builds
bundle; release filenames consistent; VERSION valid semver + display `0.1.0-dev`; CloudFront URLs correct;
12h cadence; public-website download disabled.
