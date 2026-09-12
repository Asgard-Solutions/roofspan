// Real webpack regression: native worker + shared module must ship together without URL contexts.
const assert = require("node:assert/strict");
const fs = require("node:fs/promises");
const os = require("node:os");
const path = require("node:path");
const test = require("node:test");
const webpack = require("webpack");

process.env.NODE_ENV = "production";
const craco = require("../craco.config");

test("MapLibre worker is configured and both native modules are packaged locally", async () => {
  const work = await fs.mkdtemp(path.join(os.tmpdir(), "roofspan-maplibre-"));
  try {
    const entry = path.join(work, "entry.js");
    const modulePath = path.resolve(__dirname, "../src/lib/maplibre.js").replaceAll("\\", "/");
    await fs.writeFile(entry, `export { getWorkerUrl } from ${JSON.stringify(modulePath)};`);
    const config = craco.webpack.configure({
      mode: "production", entry,
      output: { path: path.join(work, "out"), filename: "test.cjs", library: { type: "commonjs2" } },
      module: { rules: [] },
      plugins: [new webpack.DefinePlugin({ "process.env.PUBLIC_URL": JSON.stringify("/office") })],
      optimization: { minimize: true },
      performance: false,
    });
    const compiler = webpack(config);
    const stats = await new Promise((resolve, reject) => {
      compiler.run((error, result) => {
        compiler.close((closeError) => error || closeError ? reject(error || closeError) : resolve(result));
      });
    });
    assert.equal(stats.hasErrors(), false, stats.toString({ all: false, errors: true }));
    assert.equal(stats.hasWarnings(), false, stats.toString({ all: false, warnings: true }));
    const built = require(path.join(work, "out/test.cjs"));
    assert.equal(built.getWorkerUrl(), "/office/static/maplibre/maplibre-gl-worker.mjs");
    for (const file of ["maplibre-gl-worker.mjs", "maplibre-gl-shared.mjs"]) {
      const vendor = await fs.readFile(require.resolve(`maplibre-gl/dist/${file}`));
      const outputs = [path.join(work, "out"), process.env.ROOFSPAN_FRONTEND_BUILD].filter(Boolean);
      for (const output of outputs) {
        const emitted = await fs.readFile(path.join(output, "static/maplibre", file));
        assert.ok(emitted.equals(vendor), `${output}/${file} must match the unmodified vendor module`);
      }
    }
  } finally {
    await fs.rm(work, { recursive: true, force: true });
  }
});
