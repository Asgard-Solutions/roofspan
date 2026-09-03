"use strict";
// Fetch the seeded L-roof revision from the live API and run the real generator against it.
const { execSync } = require("child_process");
const { generateSketchGeometry } = require("/app/packages/roof-sketch-core");

const API = "https://hip-valley-fix.preview.emergentagent.com";
const REV = "b5a05924-6028-4421-bc22-09c88d944790";
const UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/124.0 Safari/537.36";
const curl = (m, path, token, body) => {
  let c = `curl -s -X ${m} '${API}${path}' -H 'User-Agent: ${UA}' -H 'Content-Type: application/json'`;
  if (token) c += ` -H 'Authorization: Bearer ${token}'`;
  if (body) c += ` -d '${JSON.stringify(body)}'`;
  return JSON.parse(execSync(c, { maxBuffer: 10 * 1024 * 1024 }).toString());
};

const login = curl("POST", "/api/auth/login", null, { email: "pjacobsen@asgardsolution.io", password: "RoofSpan#Owner2026" });
const token = login.token || login.access_token;
const rev = curl("GET", `/api/measurements/${REV}`, token);
const structure = rev.structures[0];
const facets = rev.facets.map((f) => ({ ...f, label: f.facet_label }));
const res = generateSketchGeometry({ structure, facets, edges: rev.edges, penetrations: rev.penetrations || [] });
console.log("readiness:", res.readiness, "| ok:", res.ok, "| facets:", res.document.facets.length,
  "| valley edges:", res.document.edges.filter((e) => e.type === "valley").length,
  "| hip edges:", res.document.edges.filter((e) => e.type === "hip").length);
console.log("framing tag:", (res.diagnostics || []).some((d) => d.code === "roof_framing_solved"));
if (!(res.ok && res.document.facets.length === 4)) { console.error("FAIL: L-roof did not solve end-to-end"); process.exit(1); }
console.log("PASS: seeded L-roof solves through the real API data shape");
