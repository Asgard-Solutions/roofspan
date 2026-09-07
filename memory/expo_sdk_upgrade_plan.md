# Expo SDK 54 → 57 Upgrade — EXECUTED & HEADLESS-VERIFIED (2026-09)

## Result
- Expo **54 → 57.0.20**, React Native **0.81.5 → 0.86.3**, React **19.1 → 19.2.3**, react-navigation stays v7.
- Done incrementally with `expo install expo@<sdk>` + `expo install --fix` at each step (55 → 56 → 57).
- **`expo-doctor`: 21/21 checks pass.**
- **46/46 mobile node test suites pass** at every checkpoint.
- **Metro bundle clean at every step** (55: 1275, 56: 1278, 57: **1293** modules; the only failure is the
  in-container `hermesc` bytecode step = known env limit, NOT a resolution error).

## Deprecation warnings — 3 of 5 ELIMINATED at the source
- `inflight@1`: GONE ✓   `rimraf@3`: GONE ✓   `glob@7`: GONE ✓ (only modern glob@13 remains)
- REMAINING (2): `uuid@3.4.0` (via `@expo/ngrok`, dev tunneling) and `uuid@7.0.3` (via `xcode`, iOS
  prebuild tooling). Both are DEV/BUILD-only, never in the app runtime. npm `overrides`
  (`@expo/ngrok@^4`, nested `xcode.uuid@^11`) would NOT take effect (buried under `@expo/cli`), and
  `@expo/ngrok@3` uses the removed `uuid/v4` subpath so it can't be force-bumped safely. Accepted as
  harmless residual until Expo updates its bundled tooling.

## Migration fixes applied (SDK 56/57 breaking changes)
- Added explicit dep **`@expo/vector-icons@^15`** — SDK 56 stopped bundling it transitively but `App.js`
  imports it (was causing `Unable to resolve module @expo/vector-icons`).
- Added **`expo-splash-screen`** and migrated the old top-level `expo.splash` in `app.json` into the
  `["expo-splash-screen", { image, resizeMode, backgroundColor }]` plugin (SDK 57 schema).

## STILL REQUIRED (user side — cannot run headless here)
- EAS **dev build for Android AND iOS**, launch on real devices.
- On-device regression matrix: online / offline / reconnect / background / force-stop / restart /
  session refresh / Office lock / conflict / **app-upgrade-from-the-previously-stuck-build**.
- Watch New Architecture (default in this range) + reanimated behavior on device specifically.
- Do this on a dedicated branch; `main` stays releasable. Big diff (mobile/package.json + root
  package-lock.json) — review before merge.
