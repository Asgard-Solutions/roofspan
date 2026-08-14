// GET /operator/callback -> validate state, exchange code (PKCE, server-side), store the Cognito
// id_token in an HttpOnly cookie (this is the bearer the Control Plane's operator_auth accepts, since it
// validates audience=app client id which is present on the id_token). Never exposes tokens to the browser.
'use strict';
const { parseCookies, cookie, clearCookie, validateCallback, exchangeCode } = require('./_lib');

function fail(res, message) {
  // Safe user-facing error only: no tokens, secrets, raw Cognito response, or server diagnostics.
  res.statusCode = 400;
  res.setHeader('Content-Type', 'text/html; charset=utf-8');
  res.end(`<!doctype html><meta charset="utf-8"><title>RoofSpan Operator</title>` +
    `<body style="font-family:system-ui;background:#0f172a;color:#e2e8f0;padding:48px">` +
    `<h1>RoofSpan Operator sign-in</h1><p>${message}</p>` +
    `<p><a style="color:#fb923c" href="/operator/login">Try again</a></p></body>`);
}

module.exports = async function handler(req, res) {
  try {
    const query = req.query || Object.fromEntries(new URL(req.url, 'http://x').searchParams);
    const cookies = parseCookies(req);
    const v = validateCallback(query, cookies);
    if (!v.ok) return fail(res, v.message);

    let tokens;
    try {
      tokens = await exchangeCode({ code: String(query.code), verifier: cookies.op_pkce });
    } catch (_e) {
      return fail(res, 'Operator sign-in failed. Please try again.');
    }
    if (!tokens || !tokens.id_token) return fail(res, 'Operator sign-in failed. Please try again.');

    const maxAge = Math.min(Number(tokens.expires_in) || 3600, 3600);
    res.setHeader('Set-Cookie', [
      cookie('op_token', tokens.id_token, maxAge), // id_token = operator bearer for the Control Plane
      clearCookie('op_state'),
      clearCookie('op_pkce'),
    ]);
    res.statusCode = 302;
    res.setHeader('Location', '/operator');
    res.end();
  } catch (_e) {
    return fail(res, 'Operator sign-in failed. Please try again.');
  }
};
