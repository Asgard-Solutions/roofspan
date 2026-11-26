#!/usr/bin/env node
// Builds the installed RoofSpan Office frontend with the installed-Office configuration, whatever is
// left on the build machine (preview .env files, global REACT_APP_* variables, PowerShell 5.1 which
// cannot set an empty variable). The installed UI is served by its own local backend, so every API
// call must be relative (REACT_APP_BACKEND_URL empty).
//
//   node build-office-frontend.js <frontendDir>           build + stamp + validate <frontendDir>/build
//   node build-office-frontend.js --check <builtDir>      validate an existing build (e.g. _stage/frontend)
"use strict";
const fs = require("fs");
const path = require("path");
const { spawnSync } = require("child_process");

const HOLD = ".roofspan-build-hold";
const ENV_FILE = /^\.env(\..+)?$/;
const FORBIDDEN = [/emergentagent\.com/i, /emergent\.host/i, /emergentcf\.cloud/i, /emergent\.sh/i];
// Preview-only tooling in public/index.html (preview editor script + analytics/session recording).
const PREVIEW_TAGS = [
  /<script[^>]*src="https:\/\/assets\.emergent\.sh\/[^"]*"[^>]*>\s*<\/script>/gi,
  /<script>(?:(?!<\/script>)[\s\S])*?posthog\.init\((?:(?!<\/script>)[\s\S])*<\/script>/gi,
];
const SCANNED = new Set([".js", ".html", ".json", ".css", ".txt", ".map"]);

function envFiles(dir) {
  return fs.readdirSync(dir).filter((f) => ENV_FILE.test(f) && !f.endsWith(HOLD) && !f.endsWith(".example"));
}

function configuredUrls(dir, files) {
  const urls = new Set();
  const add = (v) => { v = String(v || "").trim().replace(/^["']|["']$/g, ""); if (/^https?:\/\//i.test(v)) urls.add(v.replace(/\/+$/, "")); };
  add(process.env.REACT_APP_BACKEND_URL);
  for (const f of files) {
    for (const line of fs.readFileSync(path.join(dir, f), "utf8").split(/\r?\n/)) {
      const m = line.match(/^\s*REACT_APP_BACKEND_URL\s*=\s*(.*)$/);
      if (m) add(m[1]);
    }
  }
  return [...urls];
}

function walk(dir, out = []) {
  for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
    const p = path.join(dir, e.name);
    if (e.isDirectory()) walk(p, out);
    else if (SCANNED.has(path.extname(e.name).toLowerCase())) out.push(p);
  }
  return out;
}

// Reject packaged output that points at a preview / hosted server instead of the local Office backend.
function check(builtDir, extraUrls = []) {
  if (!fs.existsSync(path.join(builtDir, "index.html"))) return [`${builtDir}: index.html missing`];
  const problems = [];
  for (const file of walk(builtDir)) {
    const text = fs.readFileSync(file, "utf8");
    for (const re of FORBIDDEN) {
      const m = text.match(re);
      if (m) problems.push(`${path.relative(builtDir, file)}: contains "${m[0]}"`);
    }
    for (const url of extraUrls) if (text.includes(url)) problems.push(`${path.relative(builtDir, file)}: contains ${url}`);
  }
  return problems;
}

function gitSha(repoRoot) {
  const r = spawnSync("git", ["-C", repoRoot, "rev-parse", "HEAD"], { encoding: "utf8" });
  return r.status === 0 ? r.stdout.trim() : "unknown";
}

function build(frontendDir) {
  const repoRoot = path.resolve(frontendDir, "..");
  const stale = fs.readdirSync(frontendDir).filter((f) => f.endsWith(HOLD));
  if (stale.length) throw new Error(`Restore ${stale.join(", ")} in ${frontendDir} (left by an interrupted build) and run again.`);
  const held = envFiles(frontendDir);
  const urls = configuredUrls(frontendDir, held);
  const generated = path.join(frontendDir, ".env");
  for (const f of held) fs.renameSync(path.join(frontendDir, f), path.join(frontendDir, f + HOLD));
  if (held.length) console.log(`==> Set aside for this build: ${held.join(", ")}`);
  let status;
  try {
    fs.writeFileSync(generated, "REACT_APP_BACKEND_URL=\n");
    const env = {};
    for (const [k, v] of Object.entries(process.env)) if (!/^REACT_APP_/i.test(k)) env[k] = v;
    env.REACT_APP_BACKEND_URL = "";
    env.NODE_ENV = "production";
    const r = spawnSync("yarn", ["build"], { cwd: frontendDir, env, stdio: "inherit", shell: process.platform === "win32" });
    status = r.status;
  } finally {
    fs.rmSync(generated, { force: true });
    for (const f of held) fs.renameSync(path.join(frontendDir, f + HOLD), path.join(frontendDir, f));
  }
  if (status !== 0) throw new Error(`frontend yarn build failed (exit ${status}).`);
  const out = path.join(frontendDir, "build");
  const indexPath = path.join(out, "index.html");
  let html = fs.readFileSync(indexPath, "utf8");
  for (const re of PREVIEW_TAGS) html = html.replace(re, "");
  fs.writeFileSync(indexPath, html);
  const version = fs.readFileSync(path.join(repoRoot, "windows", "VERSION"), "utf8").trim();
  fs.writeFileSync(path.join(out, "roofspan-build.json"), JSON.stringify({ component: "roofspan-office-frontend", version, git_sha: gitSha(repoRoot) }) + "\n");
  return { out, urls };
}

function main(argv) {
  try {
    let dir, urls = [];
    if (argv[0] === "--check") dir = path.resolve(argv[1] || "");
    else ({ out: dir, urls } = build(path.resolve(argv[0] || "")));
    const problems = check(dir, urls);
    if (problems.length) {
      console.error("RoofSpan Office frontend build REJECTED - it points at a non-local server:\n  " + problems.slice(0, 20).join("\n  "));
      return 2;
    }
    console.log(`==> Office frontend validated (local /api only): ${dir}`);
    return 0;
  } catch (e) {
    console.error(String(e.message || e));
    return 1;
  }
}

if (require.main === module) process.exit(main(process.argv.slice(2)));
module.exports = { check, build, FORBIDDEN };
