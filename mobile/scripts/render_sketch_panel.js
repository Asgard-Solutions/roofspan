"use strict";
// Real react-native-web render of the Roof Sketch Measurements reference panel (expanded), proving the
// scoped, entered measurements actually appear in the DOM for the structure being sketched.
const Module = require("module");
const fs = require("fs");
const path = require("path");
const babel = require("@babel/core");
const SRC = path.resolve(__dirname, "..", "src");
const origJs = Module._extensions[".js"];
Module._extensions[".js"] = function (mod, filename) {
  if (filename.startsWith(SRC)) {
    const out = babel.transform(fs.readFileSync(filename, "utf8"), { filename, presets: ["babel-preset-expo"], babelrc: false, configFile: false });
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
const Panel = require("../src/components/SketchMeasurementsPanel").default;
const h = React.createElement;

const detail = {
  facets: [
    { id: "F1", structure_id: "S1", facet_label: "Front", pitch_rise: 6, area_sqft: 1250, width_ft: 25, length_ft: 50 },
    { id: "F2", structure_id: "S1", facet_label: "Back", pitch_rise: "", area_sqft: 310 },
    { id: "G1", structure_id: "S2", facet_label: "Garage", pitch_rise: 4, area_sqft: 400 },
  ],
  edges: [
    { id: "E1", facet_id: "F1", edge_type: "eave", length_ft: 25 },
    { id: "E2", facet_id: "F2", edge_type: "eave", length_ft: 17.5 },
    { id: "E3", facet_id: "F1", facet_id_secondary: "F2", edge_type: "valley", length_ft: 20 },
  ],
  penetrations: [
    { id: "P1", facet_id: "F1", pen_type: "pipe_boot", quantity: 3 },
    { id: "P2", facet_id: "F1", pen_type: "pipe_boot", quantity: 2 },
  ],
};

const html = ReactDOMServer.renderToStaticMarkup(h(Panel, { measDetail: detail, structureId: "S1", defaultOpen: true }));
const assert = require("assert");
let n = 0; const ok = (m) => { n++; console.log("  \u2713 " + m); };

for (const t of ["Measurements", "Roof planes", "Front", "6/12", "1250 SF", "(25×50)", "Back", "Roof lines", "Eave", "42.5 LF", "Valley", "Penetrations", "Pipe Boot", "× 5"]) {
  assert.ok(html.includes(t), `panel DOM must render "${t}"`);
}
ok("expanded panel renders scoped planes (pitch/area/W×L), grouped roof lines (LF) and penetrations (× qty)");
assert.ok(!html.includes("Garage") && !html.includes("400 SF"), "other structure's plane must not appear");
ok("other-structure measurements are excluded from the panel");
assert.ok(html.includes("1560 SF") && html.includes("planes"), "toggle header shows the structure total");
ok("panel header shows the structure total (area · squares · planes)");
console.log("\nSKETCH MEASUREMENTS PANEL RENDER: all " + n + " checks passed");
