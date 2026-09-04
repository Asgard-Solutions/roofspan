# GOTCHA: `@roofspan/roof-sketch-core` symlink gets clobbered by `yarn add`

`frontend/package.json` depends on the shared engine via `file:../packages/roof-sketch-core`.
In the preview pod this is a SYMLINK (`frontend/node_modules/@roofspan/roof-sketch-core -> /app/packages/roof-sketch-core`),
so edits to the core package are picked up by webpack.

**Problem:** running `yarn add <anything>` (or `yarn install`) in `frontend/` re-materializes this
dependency as a one-time COPY, freezing the core files at that moment. Subsequent edits to
`/app/packages/roof-sketch-core/*.js` are then IGNORED by the frontend build, and webpack's persistent
cache (`frontend/node_modules/.cache`) hides it further. This looks like "my core fix didn't take effect".

**Fix / after any `yarn add` in frontend:**
```
cd /app/frontend/node_modules/@roofspan && rm -rf roof-sketch-core && ln -s /app/packages/roof-sketch-core roof-sketch-core
rm -rf /app/frontend/node_modules/.cache
sudo supervisorctl restart frontend
```
Verify: `[ -L /app/frontend/node_modules/@roofspan/roof-sketch-core ] && echo SYMLINK`
and `diff -q node_modules/@roofspan/roof-sketch-core/<file>.js /app/packages/roof-sketch-core/<file>.js`.

Symptom seen (iteration_79): overlap-guard fix was green in `node` unit tests but the live UI still
showed the pre-fix behavior because the frontend loaded the stale copy.

---

# GOTCHA 2 (Sep 2026): "RoofSpan Field crashes on open" == `mobile/node_modules` wiped / expo missing

This is an **npm workspace monorepo** (root `/app/package.json` has `workspaces: ["mobile","packages/*"]`,
installed with npm — root `/app/package-lock.json`, NOT yarn). Deps are **hoisted to `/app/node_modules`**.
`mobile/node_modules` normally holds only a few non-hoistable dirs + the `@roofspan` and `expo` symlinks.

**Symptom:** Field crashes on open / expo-tunnel supervisor is FATAL with
`Cannot find module '/app/mobile/node_modules/expo/bin/cli'`. Checking `ls mobile/node_modules` shows only ~3 dirs;
`expo`, `react`, `react-native`, `metro`, `react-native-svg`, `expo-sqlite` all MISSING from mobile (they are at root).

**Fix:**
```
cd /app && npm install                 # restores hoisted deps per package-lock.json (~4 min, run in bg)
cd /app/mobile/node_modules && ln -sf ../../node_modules/expo expo   # supervisor command needs expo/bin/cli here
node -e "require.resolve('@roofspan/roof-sketch-core')"              # ensure workspace link intact
sudo supervisorctl restart expo-tunnel
```
Do NOT run `yarn install` in mobile — it errors `Workspaces can only be enabled in private projects`
(root package.json intentionally has no `private:true`; use npm).

**Verify (Metro is monorepo-rooted at `/app`, so entry is `/mobile/index.bundle`, NOT `/index.bundle`):**
```
curl "http://localhost:8081/" -H "expo-platform: android"                                  # manifest 200
curl "http://localhost:8081/.expo/.virtual-metro-entry.bundle?platform=android&dev=true"    # bundle 200 (~8MB)
```
A `/index.bundle` 404 with `Unable to resolve ./index from /app/.` is EXPECTED (wrong path), not a real failure.

Note: `expo export` fails at the very end on `hermesc` (`ELF: not found`) — that's a prod-only bytecode step that
can't run in this x86 container; it does NOT affect the dev/Expo Go tunnel, which serves plain JS.
