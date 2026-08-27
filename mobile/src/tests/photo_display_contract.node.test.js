const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

function read(rel) {
  return fs.readFileSync(path.join(__dirname, "..", rel), "utf8");
}

test("paired synced photos render through Relay, never the Control Plane base", () => {
  const src = read("components/PhotoSection.js");
  assert.match(src, /usePairing/);
  assert.match(src, /mintPhotoTicket/);
  assert.match(src, /photoContentSource/);
  assert.doesNotMatch(src, /\$\{API_BASE\}\$\{p\.content_url\}/);
});

test("Relay provides a ticketed HTTPS passthrough for Office photo bytes", () => {
  const server = fs.readFileSync(path.join(__dirname, "..", "..", "..", "backend", "relay", "server.py"), "utf8");
  assert.match(server, /@router\.post\("\/photo-ticket"\)/);
  assert.match(server, /@router\.get\("\/photos\/\{photo_id\}"\)/);
  assert.match(server, /\/api\/mobile\/photos\/\{photo_id\}\/content/);
  assert.match(server, /photo_timeout/);
});
