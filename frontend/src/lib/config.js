// Centralized public frontend configuration (CRA / REACT_APP_*). Values here are safe to ship in the
// browser bundle. The Windows installer/update URLs are PUBLIC delivery endpoints (CloudFront) — never
// AWS/S3/signing secrets. This is the single authoritative source for the installer download.

const CLOUDFRONT_INSTALLER = "https://downloads.roofspan.io/latest/RoofSpanSetup.exe";
const CLOUDFRONT_UPDATE_MANIFEST = "https://downloads.roofspan.io/update/windows/latest.json";

export function resolveInstaller(env = process.env) {
  const url = env.REACT_APP_WINDOWS_INSTALLER_URL || CLOUDFRONT_INSTALLER;
  const available = String(env.REACT_APP_WINDOWS_INSTALLER_AVAILABLE || "false").toLowerCase() === "true";
  const updateManifestUrl = env.REACT_APP_WINDOWS_UPDATE_MANIFEST_URL || CLOUDFRONT_UPDATE_MANIFEST;
  return { url, available, updateManifestUrl };
}

const _installer = resolveInstaller();

// Public CloudFront installer URL (direct browser download — never proxied through the backend).
export const WINDOWS_INSTALLER_URL = _installer.url;
// Explicit availability flag: the WiX/MSI binary may not be published yet, so fail gracefully.
export const WINDOWS_INSTALLER_AVAILABLE = _installer.available;
// Reserved for the future Windows Update Service (not consumed by the web UI in this phase).
export const WINDOWS_UPDATE_MANIFEST_URL = _installer.updateManifestUrl;
