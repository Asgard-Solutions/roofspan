// GET /operator/login -> start Cognito PKCE Authorization Code flow (redirect to Hosted UI).
'use strict';
const { pkce, randomState, cfg, cookie } = require('./_lib');

module.exports = function handler(req, res) {
  const c = cfg();
  if (!c.domain || !c.clientId) { res.statusCode = 500; return res.end('Operator auth not configured.'); }
  const { verifier, challenge } = pkce();
  const state = randomState();
  res.setHeader('Set-Cookie', [cookie('op_pkce', verifier, 600), cookie('op_state', state, 600)]);
  const u = new URL(`${c.domain}/oauth2/authorize`);
  u.searchParams.set('response_type', 'code');
  u.searchParams.set('client_id', c.clientId);
  u.searchParams.set('redirect_uri', c.redirectUri);
  u.searchParams.set('scope', 'openid email profile');
  u.searchParams.set('state', state);
  u.searchParams.set('code_challenge', challenge);
  u.searchParams.set('code_challenge_method', 'S256');
  res.statusCode = 302;
  res.setHeader('Location', u.toString());
  res.end();
};
