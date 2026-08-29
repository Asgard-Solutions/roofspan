// Expo monorepo Metro config. The mobile app depends on the shared workspace package
// `@roofspan/roof-sketch-core` at `../packages/roof-sketch-core`. Metro's default config only watches
// the project root, so it cannot follow the workspace symlink out to a sibling package — that is why a
// production EAS bundle failed with "Unable to resolve module @roofspan/roof-sketch-core". Watching the
// monorepo root and resolving from both node_modules locations fixes it deterministically on Windows,
// GitHub Actions Linux, and EAS Linux builders (no machine-specific paths, package exports left intact).
const { getDefaultConfig } = require("expo/metro-config");
const path = require("path");

const projectRoot = __dirname;
const monorepoRoot = path.resolve(projectRoot, "..");

const config = getDefaultConfig(projectRoot);

// 1. Watch the whole monorepo (in ADDITION to Expo's defaults) so edits to packages/roof-sketch-core
//    are picked up. Preserving the defaults keeps expo-doctor's Metro-config check green.
config.watchFolders = Array.from(new Set([...(config.watchFolders || []), monorepoRoot]));

// 2. Resolve modules from the app's own node_modules first, then the hoisted workspace root node_modules.
config.resolver.nodeModulesPaths = [
  path.resolve(projectRoot, "node_modules"),
  path.resolve(monorepoRoot, "node_modules"),
];

module.exports = config;
