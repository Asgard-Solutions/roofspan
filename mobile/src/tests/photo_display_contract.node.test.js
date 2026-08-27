const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

function read(rel) {
  return fs.readFileSync(path.join(__dirname, "..", rel), "utf8");
}

function backend(rel) {
  return fs.readFileSync(path.join(__dirname, "..", "..", "..", "backend", rel), "utf8");
}

test("paired synced photos render through Relay, never the Control Plane base", () => {
  const src = read("components/PhotoSection.js");
  const helper = read("photoContent.js");
  assert.match(src, /usePairing/);
  assert.match(src, /mintPhotoTicket/);
  assert.match(src, /photoContentSource/);
  assert.doesNotMatch(src, /\$\{API_BASE\}\$\{p\.content_url\}/);
  assert.match(helper, /\/api\/relay\/photo-ticket/);
  assert.match(helper, /\/api\/relay\/photos\//);
  assert.match(helper, /X-RoofSpan-Photo-Ticket/);
});

test("Relay provides a ticketed HTTPS passthrough for Office photo bytes", () => {
  const proxy = backend("relay/photo_proxy.py");
  const app = backend("server.py");
  assert.match(proxy, /@router\.post\("\/photo-ticket"\)/);
  assert.match(proxy, /@router\.get\("\/photos\/\{photo_id\}"\)/);
  assert.match(proxy, /\/api\/mobile\/photos\/\{safe_photo_id\}\/content/);
  assert.match(proxy, /photo_timeout/);
  assert.match(proxy, /X-RoofSpan-Photo-Ticket|x_roofspan_photo_ticket/);
  assert.match(app, /relay\.photo_proxy/);
  assert.match(app, /include_router\(relay_photo_router\)/);
});
