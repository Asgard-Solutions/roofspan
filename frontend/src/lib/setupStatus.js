// First-run routing decision + startup retry policy for RoofSpan Office (LOCAL Windows app).
// The local backend is AUTHORITATIVE for first-run state — never inferred from localStorage, tokens, or
// browser state. Only the "initialized" state allows normal login/authenticated routing; every other
// onboarding state (setup_required, owner_created, payment_required, or anything unexpected) routes to
// the first-run setup wizard.

export const SETUP_STATUS_PATH = "/setup/status";

export const isInitialized = (state) => state === "initialized";

// Returns the path SetupGate should redirect to for the given server state + current pathname, or null
// when the current location is already correct (no redirect needed).
export function targetForStatus(state, pathname) {
  if (isInitialized(state)) {
    // Initialized installs must not sit on the first-run wizard; everything else is allowed.
    return pathname === "/setup" ? "/" : null;
  }
  // Uninitialized (any non-initialized onboarding state): force the setup wizard.
  return pathname === "/setup" ? null : "/setup";
}

// Bounded retry while the local backend/service + PostgreSQL are still starting. A fresh Windows install
// starts three services + a local PostgreSQL, so allow a generous-but-bounded window before surfacing a
// startup error. 1s interval keeps the retry responsive without hammering; 20 attempts (~20s total) covers
// a cold service/DB start yet still fails fast enough to show an actionable error instead of hanging.
export const STARTUP_RETRY_INTERVAL_MS = 1000;
export const STARTUP_MAX_ATTEMPTS = 20;
