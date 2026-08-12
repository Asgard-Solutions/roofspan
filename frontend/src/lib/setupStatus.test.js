import {
  isInitialized,
  targetForStatus,
  SETUP_STATUS_PATH,
  STARTUP_RETRY_INTERVAL_MS,
  STARTUP_MAX_ATTEMPTS,
} from "./setupStatus";

describe("first-run routing decision (server authoritative)", () => {
  test("only 'initialized' counts as initialized", () => {
    expect(isInitialized("initialized")).toBe(true);
    for (const s of ["setup_required", "owner_created", "payment_required", undefined, null, ""]) {
      expect(isInitialized(s)).toBe(false);
    }
  });

  test("uninitialized states route to /setup from anywhere (incl. /login)", () => {
    for (const s of ["setup_required", "owner_created", "payment_required", "unexpected", undefined]) {
      expect(targetForStatus(s, "/login")).toBe("/setup");
      expect(targetForStatus(s, "/")).toBe("/setup");
      // already on /setup -> no redirect needed
      expect(targetForStatus(s, "/setup")).toBeNull();
    }
  });

  test("initialized stays put unless sitting on /setup (then leaves it)", () => {
    expect(targetForStatus("initialized", "/login")).toBeNull();
    expect(targetForStatus("initialized", "/")).toBeNull();
    expect(targetForStatus("initialized", "/setup")).toBe("/");
  });

  test("retry policy is bounded and reasonable", () => {
    expect(SETUP_STATUS_PATH).toBe("/setup/status");
    expect(STARTUP_RETRY_INTERVAL_MS).toBeGreaterThan(0);
    expect(STARTUP_MAX_ATTEMPTS).toBeGreaterThanOrEqual(5);
    expect(STARTUP_RETRY_INTERVAL_MS * STARTUP_MAX_ATTEMPTS).toBeLessThanOrEqual(60000);
  });
});
