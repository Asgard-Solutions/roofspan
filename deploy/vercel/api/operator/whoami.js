// GET /api/operator/whoami -> proof action. Forwards the HttpOnly operator id_token as
// `Authorization: Bearer` to the Control Plane's protected GET /operator/me. Returns only {authenticated}.
'use strict';
const { parseCookies, cfg } = require('./_lib');

module.exports = async function handler(req, res) {
  const token = parseCookies(req).op_token;
  res.setHeader('Content-Type', 'application/json');
  if (!token) { res.statusCode = 401; return res.end(JSON.stringify({ authenticated: false })); }
  try {
    const r = await fetch(`${cfg().cpBase}/api/control-plane/operator/me`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    res.statusCode = r.ok ? 200 : 401;
    res.end(JSON.stringify({ authenticated: r.ok }));
  } catch (_e) {
    res.statusCode = 502;
    res.end(JSON.stringify({ authenticated: false }));
  }
};
