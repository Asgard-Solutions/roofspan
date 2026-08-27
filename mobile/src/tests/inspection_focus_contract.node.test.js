const assert = require("assert");
const fs = require("fs");
const path = require("path");

const source = fs.readFileSync(path.join(__dirname, "..", "screens", "Inspection.js"), "utf8");

console.log("inspection input focus contract");

const screenIndex = source.indexOf("export default function Inspection");
const fieldIndex = source.indexOf("function InspectionField");

assert.ok(screenIndex >= 0, "Inspection screen export must exist");
assert.ok(
  fieldIndex >= 0 && fieldIndex < screenIndex,
  "InspectionField must be declared at module scope so typing does not remount TextInput and dismiss the keyboard"
);

const screenBody = source.slice(screenIndex);
assert.ok(
  !/\n\s+const\s+[A-Z][A-Za-z0-9_]*\s*=\s*\([^)]*\)\s*=>\s*\(/.test(screenBody),
  "Inspection must not declare JSX component types inside the screen render function"
);

assert.strictEqual(
  (source.match(/<InspectionField\b/g) || []).length,
  5,
  "all five inspection text fields must use the stable module-scope field component"
);

console.log("PASS inspection fields keep a stable component identity across keystrokes");
