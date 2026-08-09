/*
 * RoofSpan Mobile — Relay transport framing tests (Node). Run: node src/tests/transport.node.test.js
 */
const assert = require("assert");
const T = require("../transportCore");

let passed = 0;
function ok(name, fn) { fn(); passed++; console.log("  ✓", name); }

console.log("header sanitize + query");
ok("drops hop-by-hop headers, keeps app headers", () => {
  const h = T.sanitizeHeaders({ Authorization: "Bearer x", Host: "y", "content-length": "5", "X-Thing": "z" });
  assert.strictEqual(h.Authorization, "Bearer x");
  assert.strictEqual(h["X-Thing"], "z");
  assert.ok(!("Host" in h) && !("content-length" in h));
});
ok("builds query strings", () => {
  assert.strictEqual(T.toQuery({ record_type: "lead", record_id: "a b" }), "record_type=lead&record_id=a%20b");
  assert.strictEqual(T.toQuery("?x=1"), "x=1");
  assert.strictEqual(T.toQuery({ a: null, b: 2 }), "b=2");
});

console.log("utf-8 base64 round-trip");
ok("round-trips unicode JSON", () => {
  const s = JSON.stringify({ name: "José Muñoz — Roof ✓", n: 12 });
  assert.strictEqual(T.b64decodeUtf8(T.b64encodeUtf8(s)), s);
});

console.log("request frame building");
ok("json request frame", () => {
  const f = T.buildRequestFrame({ rid: "r1", method: "post", path: "/api/leads", data: { a: 1 }, headers: { Authorization: "Bearer t" } });
  assert.strictEqual(f.type, "request");
  assert.strictEqual(f.method, "POST");
  assert.strictEqual(f.headers["content-type"], "application/json");
  assert.deepStrictEqual(JSON.parse(T.b64decodeUtf8(f.body)), { a: 1 });
});
ok("get frame with params has empty body", () => {
  const f = T.buildRequestFrame({ rid: "r2", method: "GET", path: "/api/mobile/photos", params: { record_type: "lead", record_id: "x" } });
  assert.strictEqual(f.query, "record_type=lead&record_id=x");
  assert.strictEqual(f.body, "");
});
ok("multipart frame carries descriptor, empty body", () => {
  const mp = { data: { record_type: "lead", record_id: "1" }, file: { field: "file", name: "p.jpg", type: "image/jpeg", b64: "AAAA" } };
  const f = T.buildRequestFrame({ rid: "r3", method: "POST", path: "/api/mobile/photos", multipart: mp });
  assert.deepStrictEqual(f.multipart, mp);
  assert.strictEqual(f.body, "");
});

console.log("response frame parsing");
ok("parses json response", () => {
  const r = T.parseResponseFrame({ status: 200, headers: { "content-type": "application/json" }, body: T.b64encodeUtf8(JSON.stringify({ ok: true })) });
  assert.strictEqual(r.status, 200);
  assert.deepStrictEqual(r.data, { ok: true });
});
ok("parses text response", () => {
  const r = T.parseResponseFrame({ status: 404, headers: { "content-type": "text/plain" }, body: T.b64encodeUtf8("nope") });
  assert.strictEqual(r.status, 404);
  assert.strictEqual(r.data, "nope");
});

console.log(`\nPASS ${passed} transport framing assertions`);
