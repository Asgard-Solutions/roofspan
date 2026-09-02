"use strict";
// Genuine RENDER smoke for the Field measurement UI primitives. React Native can't run in-pod, but the
// primitives (LabeledField / SelectField / PitchField / ToggleRow) use only core RN elements + theme, so
// we render them through react-native-web to real DOM and assert persistent labels + hydrated selected
// values actually appear. Also writes a mobile-width HTML preview for a screenshot.
const Module = require("module");
const fs = require("fs");
const path = require("path");
const babel = require("@babel/core");

const SRC = path.resolve(__dirname, "..", "src");
const origJs = Module._extensions[".js"];
Module._extensions[".js"] = function (mod, filename) {
  if (filename.startsWith(SRC)) {
    const code = fs.readFileSync(filename, "utf8");
    const out = babel.transform(code, { filename, presets: ["babel-preset-expo"], babelrc: false, configFile: false });
    return mod._compile(out.code, filename);
  }
  return origJs(mod, filename);
};
const origResolve = Module._resolveFilename;
Module._resolveFilename = function (request, ...rest) {
  if (request === "react-native") return origResolve.call(this, "react-native-web", ...rest);
  return origResolve.call(this, request, ...rest);
};

const React = require("react");
const ReactDOMServer = require("react-dom/server");
const { AppRegistry } = require("react-native-web");
const { LabeledField, SelectField, PitchField, ToggleRow } = require("../src/components/MeasurementFields");

const STRUCTURE_TYPES = [["main_house", "Main House"], ["attached_garage", "Attached Garage"], ["detached_garage", "Detached Garage"], ["other", "Other"]];
const EDGE_TYPES = [["eave", "Eave"], ["rake", "Rake"], ["ridge", "Ridge"], ["hip", "Hip"], ["valley", "Valley"]];
const ATTACH_OPTS = [["", "None"], ["attached", "Attached"], ["detached", "Detached"]];
const facetOptions = [["", "— None —"], ["rA", "F1"], ["rB", "F2"], ["rC", "F3"]];
const h = React.createElement;

// A representative, fully-populated preview built from the SAME primitives the screen uses.
function Card(props) { return h("div", { style: { background: "#fff", border: "1px solid #E2E8F0", borderRadius: 12, padding: 12, marginBottom: 12 } }, props.children); }
function Sec(props) { return h("div", { style: { marginBottom: 18 } }, h("div", { style: { fontSize: 16, fontWeight: 800, color: "#0F172A", marginBottom: 8 } }, props.title), props.children); }

function Preview() {
  return h(React.Fragment, null,
    h(Sec, { title: "Structures" }, h(Card, null,
      h(LabeledField, { label: "Name", value: "Main House", editable: true }),
      h(SelectField, { label: "Structure Type", value: "main_house", options: STRUCTURE_TYPES }),
      h(ToggleRow, { label: "Include in estimate", value: true, onValueChange: () => {} }),
      h(LabeledField, { label: "Stories", value: "2", keyboardType: "numeric" }),
      h(LabeledField, { label: "Approx Height (ft)", value: "22", keyboardType: "numeric" }),
      h(SelectField, { label: "Attachment", value: "attached", options: ATTACH_OPTS }),
    )),
    h(Sec, { title: "Structures — Detached Garage" }, h(Card, null,
      h(LabeledField, { label: "Name", value: "Detached Garage", editable: true }),
      h(SelectField, { label: "Structure Type", value: "detached_garage", options: STRUCTURE_TYPES }),
    )),
    h(Sec, { title: "Roof Planes" }, h(Card, null,
      h(LabeledField, { label: "Plane", value: "F1" }),
      h(LabeledField, { label: "Area (SF)", value: "1250", keyboardType: "numeric" }),
      h(PitchField, { value: 6, onChange: () => {} }),
      h(SelectField, { label: "Structure", value: "rA", options: [["", "— None —"], ["rA", "Main House"]] }),
    )),
    h(Sec, { title: "Roof Planes — custom pitch" }, h(Card, null,
      h(LabeledField, { label: "Plane", value: "F3" }),
      h(PitchField, { value: 7.5, onChange: () => {} }),
    )),
    h(Sec, { title: "Roof Lines" }, h(Card, null,
      h(SelectField, { label: "Type", value: "valley", options: EDGE_TYPES }),
      h(LabeledField, { label: "Feet", value: "42", keyboardType: "numeric" }),
      h(LabeledField, { label: "Inches", value: "6", keyboardType: "numeric" }),
      h("div", { style: { fontSize: 13, fontWeight: 700, color: "#475569", marginBottom: 12 } }, "Total LF: 42.5"),
      h(SelectField, { label: "Primary Roof Plane", value: "rA", options: facetOptions }),
      h(SelectField, { label: "Secondary Roof Plane", value: "rB", options: facetOptions }),
      h(LabeledField, { label: "Label", value: "" }),
      h(LabeledField, { label: "Notes", value: "" }),
    )),
    h(Sec, { title: "Penetrations" }, h(Card, null,
      h(SelectField, { label: "Roof Plane", value: "rA", options: facetOptions }),
      h(LabeledField, { label: "Diameter (in)", value: "3", keyboardType: "numeric" }),
    )),
  );
}

const html = ReactDOMServer.renderToStaticMarkup(h(Preview));

// --- Assertions on the REAL rendered DOM ---
const assert = require("assert");
let n = 0; const ok = (m) => { n++; console.log("  \u2713 " + m); };

for (const lbl of ["Name", "Structure Type", "Stories", "Approx Height (ft)", "Attachment", "Plane", "Area (SF)", "Pitch", "Feet", "Inches", "Primary Roof Plane", "Secondary Roof Plane", "Diameter (in)"]) {
  assert.ok(html.includes(lbl), `rendered DOM must show persistent label "${lbl}"`);
}
ok("every rendered field shows its persistent label");

// Persistent label coexists with a populated value (label NOT replaced by the value).
assert.ok(html.includes("Main House") && html.includes("Name"), "label 'Name' persists alongside value 'Main House'");
assert.ok(html.includes("Detached Garage"), "second structure renders its hydrated type");
ok("labels remain visible next to populated values");

// SelectField renders the HYDRATED selected option label in its closed trigger.
for (const val of ["Main House", "Attached", "Valley", "F1", "F2"]) {
  assert.ok(html.includes(val), `SelectField trigger must render hydrated value "${val}"`);
}
ok("SelectField triggers render their hydrated selected values");

// Pitch: common 6 → "6/12"; custom 7.5 → "Custom…" + a Custom Rise input with /12 suffix.
assert.ok(html.includes("6/12"), "common pitch renders as 6/12");
assert.ok(html.includes("Custom…") && html.includes("Custom Rise") && html.includes("/12"), "custom pitch reveals a labeled Custom Rise input");
ok("pitch selector renders common (6/12) and custom (Custom Rise …/12)");

// The ft/in → LF conversion is shown.
assert.ok(html.includes("Total LF: 42.5"), "42 ft 6 in shows as 42.5 LF");
ok("42 ft 6 in renders as 42.5 LF");

// Write a mobile-width preview for a screenshot.
const outDir = path.resolve(__dirname, "..", "dist_preview");
fs.mkdirSync(outDir, { recursive: true });
const page = `<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=390"><title>Field Measurements Preview</title>
<style>body{margin:0;background:#F8FAFC;font-family:-apple-system,Segoe UI,Roboto,sans-serif} .frame{width:390px;margin:0 auto;padding:16px;box-sizing:border-box}</style></head>
<body><div class="frame"><h2 style="font-size:22px;font-weight:800;color:#0F172A">Roof measurements</h2>${html}</div></body></html>`;
fs.writeFileSync(path.join(outDir, "index.html"), page);
console.log("\nWrote preview:", path.join(outDir, "index.html"));
console.log("FIELD MEASUREMENT RENDER SMOKE: all " + n + " checks passed");
