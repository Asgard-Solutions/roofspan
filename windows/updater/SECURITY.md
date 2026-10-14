# RoofSpan Office automatic updates: security design (Phase 1)

Status: **NOT OPERATIONAL.** The code, the broker service and the tests are in place, but the end-to-end
Windows workflow has never run on Windows. The Windows-only broker security tests
(`windows/tests/test_update_broker_windows.py`, run with skips treated as failures in the `bundle-compile` job of
`.github/workflows/windows-build-scripts.yml`) must pass, and an end-to-end install on a Windows machine must be
proven, before automatic installation is enabled. The broker rejects every request (`AUTO_UPDATE_DISABLED`) while the install-owned `config-templates\update_policy.json` has `"auto_install_enabled": false` (the shipped default), and any policy without a publisher subject and at least one approved thumbprint disables automatic download and install entirely.

## Components and privilege boundary
| Component | Identity | Network | Can install? |
|---|---|---|---|
| RoofSpanUpdateService (checker) | `NT SERVICE\RoofSpanUpdateService` (virtual account, not admin) | HTTPS to the manifest host and the approved download domain | No |
| RoofSpanUpdateBroker | LocalSystem, demand-start, outbound blocked by a Windows Firewall program rule | None (loopback health checks only; revocation retrieval delegated, see below) | Yes, only RoofSpanSetup.exe from its own staging folder |
| RoofSpanSetup.exe -> roofspan-upgrade.exe | Started by the broker (SYSTEM) | n/a | The single existing transactional upgrade (preflight, verified backup, MSI, migration, health, restore) |

The checker never gets elevated. The only thing that crosses the boundary is a **request file**, and the broker
trusts nothing in it except bytes it can verify again by itself.

## Fixed locations and ACLs (all under `C:\ProgramData\RoofSpan\update`)
| Path | Writer | Reader | ACL |
|---|---|---|---|
| `downloads\<version>\RoofSpanSetup.exe.partial|.exe` | checker | checker, broker | SYSTEM, Administrators F; RoofSpanUpdateService Modify; no Users |
| `requests\request.json` | checker (atomic replace) | broker | as above |
| `broker\staging\<version>\RoofSpanSetup.exe` | broker only | broker | SYSTEM, Administrators F only (inheritance removed) |
| `state\update-state.json`, `state\journal.log` | broker for install states; checker for pre-install states, under the global lock | both | SYSTEM, Administrators F; RoofSpanUpdateService Modify |
| `state\failed-versions.json` | broker only | both | SYSTEM, Administrators F; RoofSpanUpdateService Read |
| `C:\Program Files\RoofSpan Office\config-templates\update_public_key*.pem`, `update_policy.json` | MSI only | both | Program Files default (Users read-only) |

The broker derives every path itself from the constants `C:\ProgramData\RoofSpan` and
`C:\Program Files\RoofSpan Office` and the **verified** manifest version; it rejects a version string that is
not `MAJOR.MINOR.PATCH`, so no path segment can come from the caller. It reads no environment variable and no
`roofspan.env` for these roots (only its own log file location follows the machine-level `ROOFSPAN_DATA_ROOT`).
Before using any folder it checks that the folder is not a reparse point (junction or symlink); it re-owns its
staging tree to SYSTEM and removes inherited ACEs before every copy.

## Caller authorization
The broker cannot see who started it, so it authorizes the **request**, not the start: it opens
`requests\request.json` once with a write-denying handle and reads the owner and DACL through that same handle
before reading the bytes. The file and its folder must be owned by SYSTEM, Administrators or
`NT SERVICE\RoofSpanUpdateService` (S-1-5-80-2241140877-...), and no other SID may hold any write-capable right
(write/append, EA, delete, WRITE_DAC, WRITE_OWNER, generic write/all; a NULL DACL counts as Everyone). Otherwise
`REQUEST_NOT_AUTHORIZED` / `REQUEST_ACL_TOO_BROAD`. The request must also carry the `request_id` recorded in the
SCHEDULED state, and requests found in any other state are consumed and ignored.

## Request format (the only allowed operation is "install this signed release")
```json
{"request_version": 1, "operation": "install", "request_id": "<32 hex>",
 "manifest": { ...the exact signed manifest object, including "signature"... },
 "expected_version": "1.2.4", "created_utc": "2026-06-01T00:00:00Z"}
```
Any other key, any other operation, a non-hex request id, a manifest that differs from what the signature covers,
or a request older than 24 h is rejected with a stable reason code. There are no path, URL, executable or
argument fields; the command line is exactly `<broker staging copy> /quiet /norestart /log <broker log path>`,
checked by `assert_fixed_argv` in the broker logic and again immediately before `CreateProcess` (`shell=False`).

## Checks done by the checker AND repeated independently by the broker
1. Ed25519 signature over the canonical manifest (`roofspan-windows-update-v1` domain), checked against the
   active public key **or** a listed next key (rotation). This happens before any other field is read.
2. Schema: required fields, semver, `manifest_version == 1`, `channel` equal to the configured channel,
   `expires_at` in the future, `published_at` not in the future.
3. Version policy: newer than the installed build identity (so no downgrade or reinstall), the installed version
   >= `minimum_supported_version` (otherwise BLOCKED: it needs a manual upgrade), and not on the machine's
   failed-version list.
4. `installer_url`: https, host exactly in the allow-list (`downloads.roofspan.io`), no userinfo, port,
   query or fragment, path `/releases/RoofSpanSetup-<version>.exe` (the path `release/publish.py` writes).
5. SHA-256 of the exact bytes (the broker computes it on its locked staging copy).
6. Authenticode: WinVerifyTrust with whole-chain revocation; a trusted RFC3161/Authenticode timestamp must be
   present; signer subject must equal the policy subject AND the signer thumbprint must be in the allow-list.
   A matching subject alone is never enough.

## Signing, revocation and rotation policy
- `update_policy.json`: `publisher_subject`, `publisher_thumbprints` (SHA-1, upper hex), `channel`,
  `allowed_hosts`. To rotate a certificate, ship a client release that ADDS the new thumbprint before any
  package is signed with it. Remove the old thumbprint one release later.
- Manifest key rotation: `update_public_key.pem` is the active key and `update_public_key.next.pem` is optional.
  A manifest is accepted if either key verifies it. Rotation = ship the next key, start signing with it, then
  promote it and drop the old key in a later release. Both keys are shipped by the MSI only.
- Revocation: the broker's own process has no network. It runs `certutil.exe -urlfetch -verify` on the
  extracted signer and timestamp certificates (an OS binary that fetches only the CDP/AIA/OCSP URLs embedded in
  those certificates; the firewall rule applies to the broker image only). That fills the SYSTEM CryptoAPI cache.
  Then WinVerifyTrust runs with `WTD_REVOKE_WHOLECHAIN | WTD_CACHE_ONLY_URL_RETRIEVAL`. If revocation status
  cannot be established, the result is `AUTHENTICODE_REVOCATION_UNKNOWN`: rejected, fail closed, retried at
  the next check, never bypassed.
- Expired signing certificate: accepted only if the signature carries a valid trusted timestamp made while the
  certificate was valid (standard Authenticode timestamp semantics). A revoked certificate is always rejected.

## Threat model (STRIDE summary)
| Threat | Mitigation |
|---|---|
| Malicious or compromised CDN or MITM serves a different manifest or package | Ed25519 manifest signature checked first; SHA-256 + Authenticode + thumbprint pin on the package |
| Downgrade or replay of an old signed manifest | Strictly-newer rule, `expires_at`, failed-version list |
| Local non-admin user plants a request or replaces a download | ACLs (Users cannot write); the broker re-verifies everything; the request has no paths or arguments |
| TOCTOU: file swapped between check and run | The broker copies into a SYSTEM-only folder, keeps the file open with `FILE_SHARE_READ` only (no write or delete sharing) through the hash, signature check and process start, and runs that same path |
| Junction or symlink redirection of the update folders | Reparse-point and owner checks on every folder the broker touches; the staging folder is created by the broker |
| Command or argument injection | No caller-supplied arguments; fixed argv list passed without a shell |
| Compromised checker service | The worst it can do is ask for a correctly signed, newer, allow-listed RoofSpan release, which is the intended operation |
| Concurrent installs | A global named mutex plus an exclusive lock file; state transitions are compare-and-set on the recorded state |
| Crash or reboot mid-update | Durable state with fsync + atomic replace. The broker reconciles with the coordinator's state.json. It waits while setup is still running; otherwise missing, stale (same attempt as before launch), mismatched or non-terminal evidence, a FAILED coordinator, or a build identity that matches neither version -> FAILED_SUPPORT_REQUIRED, and that version is never retried automatically |
| Information disclosure in logs | Only reason codes, versions, hashes and state names are logged; exception text goes through the redactor |
| Denial of service by repeatedly failing an update | Failed-version list; FAILED_SUPPORT_REQUIRED stops all automatic retries until an administrator clears it |

## State machine
Defined in `windows/updater/states.py` (`SPEC`). That one table is the source for the transitions, durable
data, retry, reboot, cleanup, user-visible status, admin actions and logging rules, and the unit tests check it.
The install states PREFLIGHT, BACKING_UP, INSTALLING, MIGRATING, HEALTH_CHECKING and RECOVERING mirror the
transactional coordinator. They are derived from the coordinator's own state.json and are never guessed.

## Phase 2 (not implemented)
Administrator UI and API (check now, install now, defer, clear failure), maintenance windows, active-use
warnings, deferral deadlines for required updates, and release publication and pause tooling.

## Build provenance of the broker executable
`winbuild\build_exes.ps1` builds every target in `winbuild\targets.py` (including `roofspan-update-broker`) from
source, fails if any executable is missing, and writes `services\services-build-manifest.json` (SHA-256 of each
PyInstaller output). `installer\build.ps1` refuses to run WiX unless every staged executable matches that manifest
for the same Git SHA and version, and records the hashes in `build-metadata.json`; `Test-InstallerArtifact.ps1`
extracts the MSI and checks that the packaged executables have exactly those hashes.
