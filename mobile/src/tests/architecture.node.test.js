/*
 * RoofSpan Mobile — ARCHITECTURE INVARIANT enforcement (run in Node).
 * Run: node src/tests/architecture.node.test.js
 *
 * LOCKED RULE: There is NO centrally hosted RoofSpan customer/billing web app.
 * roofspan.io is marketing/download only. Subscription/seats/billing are managed only
 * in RoofSpan Office (local Windows install). Mobile is a free companion app with NO
 * in-app purchasing and NO external billing portal link.
 */
const assert = require("assert");
const fs = require("fs");
const path = require("path");

const read = (p) => fs.readFileSync(path.join(__dirname, "..", p), "utf8");
const configSrc = read("config.js");
const statusSrc = read("screens/StatusScreens.js");
const moreSrc = read("screens/More.js");
const { COPY, STATES } = require("../connectionState");

let passed = 0;
function ok(name, fn) { fn(); passed++; console.log("  ✓", name); }

console.log("config.js — no hosted billing web target");
ok("WEB_APP_URL is not exported/defined", () => {
  assert.ok(!/export\s+const\s+WEB_APP_URL/.test(configSrc), "WEB_APP_URL export must be removed");
  assert.ok(!/\bWEB_APP_URL\b\s*=/.test(configSrc), "WEB_APP_URL assignment must be removed");
});
ok("EXPO_PUBLIC_WEB_APP_URL is never required for billing (regression)", () => {
  assert.ok(!configSrc.includes("EXPO_PUBLIC_WEB_APP_URL") || /Do NOT reintroduce/.test(configSrc),
    "EXPO_PUBLIC_WEB_APP_URL must not be a live billing config var");
  assert.ok(!/process\.env\.EXPO_PUBLIC_WEB_APP_URL/.test(configSrc),
    "config.js must not read EXPO_PUBLIC_WEB_APP_URL");
});

console.log("SubscriptionLock — points to RoofSpan Office, no web billing action");
ok("no 'Manage Subscription on the Web' button", () => {
  assert.ok(!/Manage Subscription on the Web/i.test(statusSrc));
});
ok("no WEB_APP_URL import or Linking-to-billing action", () => {
  assert.ok(!/WEB_APP_URL/.test(statusSrc), "must not import/use WEB_APP_URL");
  assert.ok(!/openWeb/.test(statusSrc), "must not open a web billing URL");
});
ok("Try Again is the primary retry action", () => {
  assert.ok(/actionLabel="Try Again"/.test(statusSrc));
  assert.ok(/subscription-lock-retry/.test(statusSrc));
});
ok("helper mentions RoofSpan Office + Windows computer + administrator", () => {
  assert.ok(/RoofSpan Office/.test(statusSrc));
  assert.ok(/Windows computer/i.test(statusSrc));
  assert.ok(/administrator/i.test(statusSrc));
});

console.log("SUBSCRIPTION_INACTIVE copy — jargon-free, no 'on the web' billing claim");
ok("copy does not tell users billing is 'on the web'", () => {
  const c = JSON.stringify(COPY[STATES.SUBSCRIPTION_INACTIVE]).toLowerCase();
  assert.ok(!c.includes("on the web"), "must not claim billing lives on the web");
  assert.ok(!c.includes("web app"), "must not call anything a web app");
});

console.log("More.js — Owner/Admin billing card is informational only");
ok("billing card is role-gated to owner/administrator", () => {
  assert.ok(/role === "owner" \|\| user\?\.role === "administrator"/.test(moreSrc));
});
ok("billing card explains billing happens in RoofSpan Office", () => {
  assert.ok(/managed in RoofSpan Office/.test(moreSrc));
  assert.ok(/Windows computer/i.test(moreSrc));
});
ok("no external billing button / web link in More", () => {
  assert.ok(!/Manage on RoofSpan Web/i.test(moreSrc));
  assert.ok(!/openBillingWeb/.test(moreSrc));
  assert.ok(!/WEB_APP_URL/.test(moreSrc));
});

console.log("No Apple/Google in-app purchasing anywhere in mobile");
ok("no IAP / billing SDK references", () => {
  const all = [configSrc, statusSrc, moreSrc].join("\n").toLowerCase();
  ["expo-in-app-purchases", "react-native-iap", "play billing", "storekit", "revenuecat"].forEach((t) =>
    assert.ok(!all.includes(t), `mobile billing surface leaked purchasing SDK term: ${t}`));
});

console.log(`\nPASS ${passed} architecture-invariant assertions`);
