// RoofSpan Office UI — public config (CRA REACT_APP_*). PUBLIC values only, never secrets.
// The Windows installer URLs are PUBLIC CloudFront delivery endpoints (downloads.roofspan.io).
// Direct browser download only — never fetched into JS memory, never proxied through any backend/S3.

const CLOUDFRONT_INSTALLER = "https://downloads.roofspan.io/latest/RoofSpanSetup.exe";
const CLOUDFRONT_RELEASES_BASE = "https://downloads.roofspan.io/releases";
const CLOUDFRONT_UPDATE_MANIFEST = "https://downloads.roofspan.io/update/windows/latest.json";

export function resolveInstaller(env = process.env) {
  const url = env.REACT_APP_WINDOWS_INSTALLER_URL || CLOUDFRONT_INSTALLER;
  const available = String(env.REACT_APP_WINDOWS_INSTALLER_AVAILABLE || "false").toLowerCase() === "true";
  const releasesBaseUrl = (env.REACT_APP_WINDOWS_RELEASES_BASE_URL || CLOUDFRONT_RELEASES_BASE).replace(/\/+$/, "");
  const updateManifestUrl = env.REACT_APP_WINDOWS_UPDATE_MANIFEST_URL || CLOUDFRONT_UPDATE_MANIFEST;
  return { url, available, releasesBaseUrl, updateManifestUrl };
}

export function versionedInstallerUrl(version, env = process.env) {
  const { releasesBaseUrl } = resolveInstaller(env);
  return `${releasesBaseUrl}/RoofSpanSetup-${version}.exe`;
}

const _installer = resolveInstaller();
export const WINDOWS_INSTALLER_URL = _installer.url;
export const WINDOWS_INSTALLER_AVAILABLE = _installer.available;
export const WINDOWS_RELEASES_BASE_URL = _installer.releasesBaseUrl;
export const WINDOWS_UPDATE_MANIFEST_URL = _installer.updateManifestUrl;
