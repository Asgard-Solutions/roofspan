// Shared helpers for the RoofSpan operator (internal admin) Cognito auth flow on Vercel.
// PKCE Authorization Code flow. All secrets/token exchange are SERVER-SIDE only (serverless functions);
// nothing sensitive is ever sent to the browser and tokens live only in HttpOnly cookies.
'use strict';
const crypto = require('crypto');

const b64url = (buf) => Buffer.from(buf).toString('base64')
  .replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');

function pkce() {
  const verifier = b64url(crypto.randomBytes(32));
  const challenge = b64url(crypto.createHash('sha256').update(verifier).digest());
  return { verifier, challenge };
}
const randomState = () => b64url(crypto.randomBytes(24));

function cfg() {
  return {
    domain: (process.env.COGNITO_DOMAIN || '').replace(/\/$/, ''),      // e.g. https://roofspan-ops.auth.us-east-2.amazoncognito.com
    clientId: process.env.COGNITO_CLIENT_ID || '',
    clientSecret: process.env.COGNITO_CLIENT_SECRET || '',              // optional (confidential client); SERVER ONLY
    redirectUri: process.env.OPERATOR_REDIRECT_URI || 'https://www.roofspan.io/operator/callback',
    logoutUri: process.env.COGNITO_LOGOUT_URI || 'https://www.roofspan.io/operator/login',
    cpBase: (process.env.CONTROL_PLANE_BASE_URL || 'https://cp.roofspan.io').replace(/\/$/, ''),
  };
}

// Canonical operator host. op_token is host-only on www.roofspan.io, so every operator route must be on
// www to avoid apex/www session splitting (a host-only www cookie is not sent to the apex host).
const CANONICAL_HOST = 'www.roofspan.io';
const APEX_HOST = 'roofspan.io';

// Returns the absolute canonical https://www.roofspan.io URL (path + query preserved) when the request
// is on the apex host; otherwise null. Defense-in-depth alongside the vercel.json edge redirects.
function canonicalRedirect(host, url) {
  const h = String(host || '').split(':')[0].toLowerCase();
  if (h !== APEX_HOST) return null;
  const path = url && url.startsWith('/') ? url : `/${url || ''}`;
  return `https://${CANONICAL_HOST}${path}`;
}

// 308-redirect to the canonical www host BEFORE any auth/session handling. Returns true if it redirected.
function redirectToCanonical(req, res) {
  const loc = canonicalRedirect(req.headers && req.headers.host, req.url);
  if (!loc) return false;
  res.statusCode = 308;
  res.setHeader('Location', loc);
  res.end();
  return true;
}

function parseCookies(req) {
  const out = {};
  (req.headers.cookie || '').split(';').forEach((p) => {
    const i = p.indexOf('='); if (i < 0) return;
    out[p.slice(0, i).trim()] = decodeURIComponent(p.slice(i + 1).trim());
  });
  return out;
}
const cookie = (name, val, maxAge) =>
  `${name}=${encodeURIComponent(val)}; Path=/; HttpOnly; Secure; SameSite=Lax; Max-Age=${maxAge}`;
const clearCookie = (name) => `${name}=; Path=/; HttpOnly; Secure; SameSite=Lax; Max-Age=0`;

// Pure, unit-testable callback validation. Rejects missing/mismatched state and missing code.
function validateCallback(query, cookies) {
  if (query.error) return { ok: false, message: 'Sign-in was cancelled or failed.' };
  if (!query.state || !cookies.op_state || query.state !== cookies.op_state)
    return { ok: false, message: 'Invalid or expired sign-in state.' };
  if (!cookies.op_pkce) return { ok: false, message: 'Invalid or expired sign-in session.' };
  if (!query.code) return { ok: false, message: 'Missing authorization code.' };
  return { ok: true };
}

// Server-side authorization-code -> token exchange (PKCE). Returns Cognito's token JSON.
async function exchangeCode({ code, verifier }, deps = {}) {
  const c = cfg();
  const doFetch = deps.fetch || fetch;
  const body = new URLSearchParams({
    grant_type: 'authorization_code',
    client_id: c.clientId,
    code,
    redirect_uri: c.redirectUri,
    code_verifier: verifier,
  });
  const headers = { 'Content-Type': 'application/x-www-form-urlencoded' };
  if (c.clientSecret) // confidential client: HTTP Basic, SERVER-SIDE only
    headers.Authorization = 'Basic ' + Buffer.from(`${c.clientId}:${c.clientSecret}`).toString('base64');
  const resp = await doFetch(`${c.domain}/oauth2/token`, { method: 'POST', headers, body: body.toString() });
  if (!resp.ok) throw new Error('token_exchange_failed');
  return resp.json();
}

module.exports = { b64url, pkce, randomState, cfg, parseCookies, cookie, clearCookie, validateCallback, exchangeCode, canonicalRedirect, redirectToCanonical, CANONICAL_HOST, APEX_HOST };
