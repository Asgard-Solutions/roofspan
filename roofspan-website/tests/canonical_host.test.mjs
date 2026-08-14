// Canonical-host (apex -> www) redirect tests for the operator flow.
// Proves apex operator routes 308-redirect to www (path+query preserved), www routes do NOT redirect,
// and authenticated www whoami still reads op_token. Cookie stays host-only on www (unchanged).
// Run: node --test roofspan-website/tests/canonical_host.test.mjs
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';
import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);
const ROOT = dirname(dirname(fileURLToPath(import.meta.url)));
const lib = require('../api/operator/_lib.js');

// Minimal Node http res double with a settable statusCode + captured headers/body.
function fakeRes() {
  return {
    statusCode: undefined, headers: {}, body: undefined,
    setHeader(k, v) { this.headers[k] = v; },
    end(b) { this.body = b; },
  };
}

test('canonicalRedirect: apex /operator -> www', () => {
  assert.equal(lib.canonicalRedirect('roofspan.io', '/operator'), 'https://www.roofspan.io/operator');
});

test('canonicalRedirect: apex /operator/login -> www', () => {
  assert.equal(lib.canonicalRedirect('roofspan.io', '/operator/login'), 'https://www.roofspan.io/operator/login');
});

test('canonicalRedirect: apex /operator/callback preserves query string', () => {
  assert.equal(
    lib.canonicalRedirect('roofspan.io', '/operator/callback?code=abc&state=xyz'),
    'https://www.roofspan.io/operator/callback?code=abc&state=xyz');
});

test('canonicalRedirect: apex /api/operator/whoami -> www', () => {
  assert.equal(lib.canonicalRedirect('roofspan.io', '/api/operator/whoami'),
    'https://www.roofspan.io/api/operator/whoami');
});

test('canonicalRedirect: www host is already canonical (no redirect)', () => {
  assert.equal(lib.canonicalRedirect('www.roofspan.io', '/operator'), null);
  assert.equal(lib.canonicalRedirect('www.roofspan.io:443', '/api/operator/whoami'), null);
});

test('apex login handler 308-redirects to www BEFORE setting PKCE cookies', () => {
  const login = require('../api/operator/login.js');
  const res = fakeRes();
  login({ headers: { host: 'roofspan.io' }, url: '/operator/login' }, res);
  assert.equal(res.statusCode, 308);
  assert.equal(res.headers['Location'], 'https://www.roofspan.io/operator/login');
  assert.equal(res.headers['Set-Cookie'], undefined); // no session started on apex
});

test('apex callback handler 308-redirects to www (query preserved) BEFORE token exchange', async () => {
  const cb = require('../api/operator/callback.js');
  const res = fakeRes();
  await cb({ headers: { host: 'roofspan.io' }, url: '/operator/callback?code=abc&state=xyz' }, res);
  assert.equal(res.statusCode, 308);
  assert.equal(res.headers['Location'], 'https://www.roofspan.io/operator/callback?code=abc&state=xyz');
});

test('apex whoami handler 308-redirects to www BEFORE reading the cookie', async () => {
  const whoami = require('../api/operator/whoami.js');
  const res = fakeRes();
  await whoami({ headers: { host: 'roofspan.io', cookie: 'op_token=X' }, url: '/api/operator/whoami' }, res);
  assert.equal(res.statusCode, 308);
  assert.equal(res.headers['Location'], 'https://www.roofspan.io/api/operator/whoami');
});

test('www whoami does NOT redirect and reads op_token -> authenticated:true', async () => {
  const whoami = require('../api/operator/whoami.js');
  const orig = globalThis.fetch;
  let hit;
  globalThis.fetch = async (u, opts) => {
    hit = { u, auth: opts.headers.Authorization };
    return { ok: true };
  };
  const res = fakeRes();
  try {
    await whoami({ headers: { host: 'www.roofspan.io', cookie: 'op_token=THETOKEN' }, url: '/api/operator/whoami' }, res);
  } finally {
    globalThis.fetch = orig;
  }
  assert.equal(res.statusCode, 200);
  assert.deepEqual(JSON.parse(res.body), { authenticated: true });
  assert.match(hit.u, /\/api\/control-plane\/operator\/me$/);
  assert.equal(hit.auth, 'Bearer THETOKEN');
});

test('vercel.json edge-redirects apex operator routes to www (308) with host condition', () => {
  const vj = JSON.parse(readFileSync(join(ROOT, 'vercel.json'), 'utf8'));
  const redirects = vj.redirects || [];
  const apexHost = (r) => (r.has || []).some((h) => h.type === 'host' && h.value === 'roofspan.io');
  const sources = ['/operator', '/operator/:path*', '/api/operator/:path*'];
  for (const s of sources) {
    const r = redirects.find((x) => x.source === s);
    assert.ok(r, `missing apex redirect for ${s}`);
    assert.ok(apexHost(r), `${s} redirect must be gated on the apex host`);
    assert.equal(r.permanent, true); // 308
    assert.match(r.destination, /^https:\/\/www\.roofspan\.io/);
  }
});

test('op_token cookie stays host-only on www (no Domain attribute)', () => {
  const c = lib.cookie('op_token', 'v', 3600);
  assert.ok(!/Domain=/i.test(c), 'op_token must remain host-only');
  assert.match(c, /HttpOnly/);
  assert.match(c, /Secure/);
  assert.match(c, /SameSite=Lax/);
  assert.match(c, /Path=\//);
});
