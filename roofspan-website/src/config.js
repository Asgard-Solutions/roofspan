// Public website configuration (CRA REACT_APP_*). PUBLIC values only — never secrets.
// The Windows installer/update URLs are PUBLIC CloudFront delivery endpoints. This is the single
// authoritative source for the public download link on roofspan.io.

const CLOUDFRONT_INSTALLER = "https://downloads.roofspan.io/latest/RoofSpanSetup.exe";
const CLOUDFRONT_UPDATE_MANIFEST = "https://downloads.roofspan.io/update/windows/latest.json";

export function resolveInstaller(env = process.env) {
  const url = env.REACT_APP_WINDOWS_INSTALLER_URL || CLOUDFRONT_INSTALLER;
  const available = String(env.REACT_APP_WINDOWS_INSTALLER_AVAILABLE || "false").toLowerCase() === "true";
  const updateManifestUrl = env.REACT_APP_WINDOWS_UPDATE_MANIFEST_URL || CLOUDFRONT_UPDATE_MANIFEST;
  return { url, available, updateManifestUrl };
}

const _installer = resolveInstaller();

// Public CloudFront installer URL (direct browser download — never proxied through any backend).
export const WINDOWS_INSTALLER_URL = _installer.url;
// Availability flag: the WiX/MSI binary may not be published yet, so show a graceful "coming soon".
export const WINDOWS_INSTALLER_AVAILABLE = _installer.available;
export const WINDOWS_UPDATE_MANIFEST_URL = _installer.updateManifestUrl;
