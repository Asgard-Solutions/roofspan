# npm deprecation warnings (inflight, glob@7, rimraf@3, uuid@3, uuid@7) — investigation (2026-09)

## Where they come from (root npm workspace: `mobile` + `packages/*`)
Traced via root `package-lock.json`:
- `inflight@1.0.6` ← ONLY via `glob@7.2.3`
- `glob@7.2.3` ← `rimraf@3`, `@react-native/codegen`, `react-native`, `test-exclude`
- `rimraf@3.0.2` ← `chromium-edge-launcher`
- `uuid@3.4.0` ← `@expo/ngrok`; `uuid@7.0.3` ← `xcode`

All are DEEP transitive DEV/BUILD-tooling deps of Expo / React Native / xcode / ngrok. NONE are runtime
deps of the shipped app → the warnings are cosmetic, build-time only, no runtime/security impact.

## Why npm `overrides` (glob^11, rimraf^6, uuid^11) did NOT work cleanly
- npm applies overrides ONLY on a FROM-SCRATCH lock resolution (delete node_modules + lock). That
  successfully removed all 5 deprecated packages (verified: inflight gone, rimraf 6.1.3, glob 11.1.0,
  uuid 11.1.1) BUT drifted the ENTIRE Expo/RN tree (748 pkgs) and BROKE the Metro build:
  `Unable to resolve module use-latest-callback from @react-navigation/native` (dep dropped by the
  re-resolve). Bundle aborted at 1200/1261 modules.
- On any INCREMENTAL install (existing lock or existing node_modules), npm honors the committed lock and
  keeps the OLD deprecated versions — overrides ignored. There is no clean "apply overrides as a minimal
  delta" in npm here.
- Note: even glob@11.1.0 / uuid@9 are themselves registry-"deprecated" (isaacs/uuid nags), so it's whack-a-mole.

## Decision
Reverted to the committed `package.json` + `package-lock.json` (known-good; Metro bundles 1261 modules).
Do NOT force these via overrides on this production tree. The CORRECT fix is an upstream Expo SDK / RN
upgrade (brings modern glob/rimraf/uuid), done deliberately as its own task. Also removed a corrupt
control-char file `mobile/*@@*` that reappeared untracked during the Expo/Metro runs.
