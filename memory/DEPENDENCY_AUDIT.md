# RoofSpan Mobile — Deprecated Transitive Dependency Cleanup (2026-06)

Outcome: **no dependency or lockfile changes made.** Every remaining deprecated transitive is pinned by
Expo SDK 54 or React Native 0.81.5 framework tooling (or by an already-latest RoofSpan devDependency),
so there is NO supported parent upgrade that removes it while staying on Expo 54 / RN 0.81.5. Per the
guardrails, overrides were NOT added (they would require STOP+report and are API-risky here). Removal
would require a forbidden framework-major upgrade.

Guardrails held: Expo 54.0.37, React Native 0.81.5, React 19.1.0, React Navigation 7 — all unchanged.
No RoofSpan ID architecture touched (DB/Measurement/Sketch/queue/photo/pairing identities untouched).

## Findings (npm explain, clean install)

| Package | Exact parent chain | Runtime? | Verdict | Future upgrade to remove |
|---|---|---|---|---|
| inflight@1.0.6 | glob@7.2.3 ← @react-native/codegen@0.81.5 ← @react-native/babel-plugin-codegen ← babel-preset-expo@54 | Build/tooling (Babel codegen) | REMAINS — framework | Future React Native upgrade — exact removal version to be confirmed during that upgrade (current @react-native/codegen@0.81.5 still pins glob ^7.1.1) |
| glob@7.2.3 | @react-native/codegen@0.81.5 (`glob ^7.1.1`) + babel-jest→test-exclude | Build/test tooling | REMAINS — framework | Future React Native upgrade — exact removal version to be confirmed during that upgrade |
| rimraf@3.0.2 | chromium-edge-launcher@0.2.0 (`rimraf ^3.0.2`) ← @react-native/dev-middleware@0.81.5 | Dev-only (JS debugger launcher) | REMAINS — framework | React Native dev-middleware bump (RN major) |
| uuid@3.4.0 | @expo/ngrok@4.1.3 (RoofSpan devDependency; latest, still `uuid ^3.3.2`) | Dev-only (tunnel CLI) | REMAINS — parent already latest | Drop/replace @expo/ngrok (product decision) or override |
| uuid@7.0.3 | xcode@3.0.1 (`uuid ^7.0.3`) ← @expo/config-plugins@54.0.5 ← @expo/config ← @expo/metro-config@54 ← expo@54 | Build/prebuild-only (iOS pbxproj) | REMAINS — framework | Expo SDK bump (config-plugins/xcode) |

Notes:
- `@react-native/codegen` and `@react-native/dev-middleware` are EXACT `0.81.5` pins of React Native 0.81.5 — cannot bump without an RN major upgrade (forbidden).
- `@expo/config-plugins@~54.0.5` is pinned by Expo SDK 54 (via @expo/config / @expo/metro-config). `xcode` stable line tops at 3.0.1 (3.0.2 only exists as -nightly prereleases); it still requires `uuid ^7.0.3`.
- `@expo/ngrok` latest published is 4.1.3 (already installed) and still declares `uuid ^3.3.2` — no newer parent exists. It is a dev-only tunnel helper, never in the shipped bundle. Removing it is a separate product decision (deferred), not a parent upgrade.
- Bumping `@maplibre/maplibre-react-native` (10→11) would NOT remove uuid@7: Expo 54 core independently pulls config-plugins→xcode→uuid@7. So that major bump has zero benefit for this target and was correctly avoided.

## Regression state
No changes were made, so the previously-verified green state from the RN7 lockfile-reproducibility step stands:
clean `npm ci` OK; test:nav/measurements/sketch/transport/pairing/map/canvass/reconcile/resolve green;
expo-doctor 18/18; expo install --check clean; Android export 2.72 MB. `test:sync` remains an
environment-dependent 404 (stale hardcoded preview backend), unrelated to dependencies.

## npm Security + Lockfile Health Closure (2026-06)
Verified the CURRENT committed RN7 root lockfile from a clean state.
- **Clean `npm ci`:** OK — 752 packages, no errors, **no invalid peer dependencies**. Frameworks unchanged (expo 54.0.37, react-native 0.81.5, react 19.1.0). RN Navigation all 7.x (native 7.3.18 / native-stack 7.18.10 / bottom-tabs 7.18.18 / core 7.21.13 / routers 7.6.4 / elements 2.9.40); **no RN6 active, no RN8**. `expo-doctor` 18/18; `expo install --check` up to date.
- **Lockfile:** root `package-lock.json` is the sole npm workspace lockfile (no `mobile/package-lock.json`, no root `yarn.lock`). NOTE: `frontend/yarn.lock` and `packages/roof-sketch-core/yarn.lock` are separate non-npm sub-project lockfiles (Office web app / shared-core), pre-existing and out of scope for the mobile npm workspace.
- **RUNTIME/shipped-app advisories: ZERO.** The only previously runtime-bundled advisory — `@react-navigation/core → query-string → decode-uri-component` (RN6) — is **REMOVED** by the RN7 upgrade: `query-string` and `decode-uri-component` are no longer present anywhere in the graph (RN Navigation 7 core dropped `query-string`). Verified via `npm ls query-string decode-uri-component --all` → not found.
- **`npm audit`: 28 findings (9 high, 19 moderate) — ALL build/development tooling, NONE shipped in the mobile JS bundle.** The `--omit=dev` run still reports 27 (9 high, 18 moderate) only because Expo declares these tools as runtime `dependencies` of the `expo` package; npm's dependency *type* ≠ code shipped in the RN app bundle. Metro, the Expo CLI, PostCSS and image-size execute on the BUILD machine only.
  - HIGH (all build/tooling): `@expo/cli`, `expo` (flagged via its cli/metro/config deps), `@expo/metro`, `@expo/metro-config`, `metro`, `metro-config`, `metro-transform-worker` (Metro JS bundler), `image-size` (asset sizing during bundling — DoS on malformed ICNS/JXL/HEIF), `postcss` (CSS processing in metro-config — XSS/path-traversal in stringify/sourcemap). All are pinned by the Expo SDK 54 / RN 0.81.5 toolchain; removal requires an Expo/RN upgrade (out of scope) and no override is permitted.
  - Moderate: same Expo/Metro/config-plugins/xcode/@expo/ngrok build-and-prebuild chains documented above.
- **No package/lockfile changes made** (guardrails: no removal of accepted debt, no `overrides`, no `npm audit fix --force`). Documentation-only closure.
