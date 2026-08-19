// Deployment-integration wiring tests: prove the operator auth is part of THIS Vercel project
// (roofspan-website) and resolves to serverless functions, not the marketing SPA.
// Run: node --test roofspan-website/tests/deployment_wiring.test.mjs
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync, existsSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';
import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);
const ROOT = dirname(dirname(fileURLToPath(import.meta.url))); // /app/roofspan-website
const read = (p) => readFileSync(join(ROOT, p), 'utf8');

test('operator serverless functions exist in the Vercel project root api/', () => {
  for (const f of ['_lib.js', 'login.js', 'callback.js', 'whoami.js']) {
    assert.ok(existsSync(join(ROOT, 'api', 'operator', f)), `api/operator/${f} missing`);
  }
});

test('functions are real Node serverless handlers (module.exports), not the marketing SPA', () => {
  for (const f of ['login.js', 'callback.js', 'whoami.js']) {
    const src = read(`api/operator/${f}`);
    assert.match(src, /module\.exports\s*=/, `${f} must export a handler`);
    assert.ok(!/id="root"/.test(src), `${f} must not be the CRA SPA index.html`);
  }
});

test('/operator/login -> serverless function: redirects (302) to the Cognito Hosted UI', () => {
  const login = read('api/operator/login.js');
  assert.match(login, /statusCode\s*=\s*302/);
  assert.match(login, /oauth2\/authorize/);
  assert.match(login, /code_challenge_method/); // PKCE, proves the function (not SPA) runs
});

test('/api/operator/whoami -> JSON serverless response, not SPA HTML', () => {
  const who = read('api/operator/whoami.js');
  assert.match(who, /application\/json/);
  assert.match(who, /authenticated/);
  assert.ok(!/text\/html/.test(who), 'whoami must not return HTML');
});

test('/operator/callback -> serverless callback function (server-side token exchange)', () => {
  const cb = read('api/operator/callback.js');
  assert.match(cb, /exchangeCode/);
  assert.match(cb, /op_token/); // sets HttpOnly bearer cookie
});

test('/operator -> operator console page shipped in public/', () => {
  assert.ok(existsSync(join(ROOT, 'public', 'operator', 'index.html')));
  assert.match(read('public/operator/index.html'), /\/api\/operator\/whoami/);
});

test('vercel.json wires the operator rewrites (login+callback to functions, /operator to the page)', () => {
  const vj = JSON.parse(read('vercel.json'));
  const map = Object.fromEntries((vj.rewrites || []).map((r) => [r.source, r.destination]));
  assert.equal(map['/operator/login'], '/api/operator/login');
  assert.equal(map['/operator/callback'], '/api/operator/callback');
  assert.equal(map['/operator'], '/operator/index.html');
  // whoami is served directly by the filesystem function (/api/operator/whoami) — must NOT be
  // rewritten to the SPA. No rewrite entry should point any /api/* to index.html.
  for (const [src, dest] of Object.entries(map)) {
    if (src.startsWith('/api/')) assert.ok(!/index\.html$/.test(dest), 'api routes must not fall back to SPA');
  }
});

test('canonical production host is www.roofspan.io (matches Vercel apex->www redirect)', () => {
  const lib = read('api/operator/_lib.js');
  assert.match(lib, /https:\/\/www\.roofspan\.io\/operator\/callback/);
});

test('marketing SPA is preserved (CRA entry + build script untouched)', () => {
  assert.ok(existsSync(join(ROOT, 'public', 'index.html')));
  assert.ok(existsSync(join(ROOT, 'src', 'App.js')));
  const pkg = JSON.parse(read('package.json'));
  assert.equal(pkg.scripts.build, 'react-scripts build');
});
