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
