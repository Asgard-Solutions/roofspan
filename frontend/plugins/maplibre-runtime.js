const fs = require("fs");
const path = require("path");

// MapLibre 6 loads a native module worker with a relative import of the shared module.
// Keep the vendor files together and unchanged, inside the Office frontend payload.
class MapLibreRuntimePlugin {
  apply(compiler) {
    const name = "MapLibreRuntimePlugin";
    compiler.hooks.thisCompilation.tap(name, (compilation) => {
      compilation.hooks.processAssets.tap(
        { name, stage: compiler.webpack.Compilation.PROCESS_ASSETS_STAGE_ADDITIONAL },
        () => {
          for (const file of ["maplibre-gl-worker.mjs", "maplibre-gl-shared.mjs"]) {
            const source = require.resolve(`maplibre-gl/dist/${file}`);
            compilation.fileDependencies.add(source);
            compilation.emitAsset(
              path.posix.join("static/maplibre", file),
              new compiler.webpack.sources.RawSource(fs.readFileSync(source)),
              // These vendor modules are already minified; preserve their shared export contract.
              { minimized: true },
            );
          }
        },
      );
    });
  }
}

module.exports = MapLibreRuntimePlugin;
