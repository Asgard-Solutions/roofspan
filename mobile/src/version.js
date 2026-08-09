// Pure semantic-version gate (CommonJS). Decides must_update / update_available / ok.
function parse(v) {
  return String(v || "0").split(".").map((x) => parseInt(x, 10) || 0);
}
function compareVersions(a, b) {
  const A = parse(a), B = parse(b);
  for (let i = 0; i < 3; i++) {
    const x = A[i] || 0, y = B[i] || 0;
    if (x !== y) return x < y ? -1 : 1;
  }
  return 0;
}
// current: installed app version; min: hard minimum (block); latest: recommended (soft prompt).
function versionGate(current, min, latest) {
  if (min && compareVersions(current, min) < 0) return "must_update";
  if (latest && compareVersions(current, latest) < 0) return "update_available";
  return "ok";
}
module.exports = { compareVersions, versionGate };
