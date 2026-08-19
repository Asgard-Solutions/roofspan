// node --test deploy/vercel/tests/operator_auth.test.mjs
import test from 'node:test';
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
const require = createRequire(import.meta.url);
const lib = require('../api/operator/_lib.js');

test('PKCE produces a URL-safe verifier + S256 challenge', () => {
  const { verifier, challenge } = lib.pkce();
  assert.match(verifier, /^[A-Za-z0-9_-]+$/);
  assert.match(challenge, /^[A-Za-z0-9_-]+$/);
  assert.notEqual(verifier, challenge);
});

test('validateCallback rejects missing state', () => {
  const r = lib.validateCallback({ code: 'abc' }, { op_pkce: 'v' });
  assert.equal(r.ok, false);
});

test('validateCallback rejects mismatched state (CSRF)', () => {
  const r = lib.validateCallback({ code: 'abc', state: 'x' }, { op_state: 'y', op_pkce: 'v' });
  assert.equal(r.ok, false);
});

test('validateCallback rejects missing code', () => {
  const r = lib.validateCallback({ state: 's' }, { op_state: 's', op_pkce: 'v' });
  assert.equal(r.ok, false);
  assert.match(r.message, /code/i);
});

test('validateCallback accepts matching state + code + pkce', () => {
  const r = lib.validateCallback({ code: 'abc', state: 's' }, { op_state: 's', op_pkce: 'v' });
  assert.equal(r.ok, true);
});

test('exchangeCode posts PKCE params to the token endpoint and returns tokens (mocked)', async () => {
  process.env.COGNITO_DOMAIN = 'https://roofspan-ops.auth.us-east-2.amazoncognito.com';
  process.env.COGNITO_CLIENT_ID = 'client123';
  delete process.env.COGNITO_CLIENT_SECRET;
  let captured;
  const fakeFetch = async (url, opts) => {
    captured = { url, opts };
    return { ok: true, json: async () => ({ id_token: 'ID', access_token: 'AC', expires_in: 3600 }) };
  };
  const tokens = await lib.exchangeCode({ code: 'authcode', verifier: 'verifier1' }, { fetch: fakeFetch });
  assert.equal(tokens.id_token, 'ID');
  assert.match(captured.url, /\/oauth2\/token$/);
  assert.match(captured.opts.body, /grant_type=authorization_code/);
  assert.match(captured.opts.body, /code_verifier=verifier1/);
  assert.match(captured.opts.body, /client_id=client123/);
  // public client (no secret) -> no Authorization header
  assert.equal(captured.opts.headers.Authorization, undefined);
});

test('exchangeCode throws a generic error on non-OK (no raw response leaked)', async () => {
  const fakeFetch = async () => ({ ok: false, json: async () => ({ error: 'invalid_grant' }) });
  await assert.rejects(() => lib.exchangeCode({ code: 'x', verifier: 'y' }, { fetch: fakeFetch }),
    /token_exchange_failed/);
});
