// Single source of truth for public site configuration. PUBLIC values only — never secrets.
// Windows installer/update URLs are PUBLIC CloudFront endpoints delivered DIRECTLY to the browser
// (never proxied through any backend). Availability drives every CTA/status on the page.

export const APPROVED_INSTALLER_HOST = "downloads.roofspan.io";

const CLOUDFRONT_INSTALLER = "https://downloads.roofspan.io/latest/RoofSpanSetup.exe";
const CLOUDFRONT_RELEASES_BASE = "https://downloads.roofspan.io/releases";
const CLOUDFRONT_UPDATE_MANIFEST = "https://downloads.roofspan.io/update/windows/latest.json";

export const SITE_URL = process.env.NEXT_PUBLIC_SITE_URL || "https://roofspan.io";
export const CONTACT_EMAIL = process.env.NEXT_PUBLIC_CONTACT_EMAIL || "support@roofspan.io";
// Public lead destination. When unset, the early-access form falls back to a transparent mailto:
// (it NEVER fakes a success). Point this at your form provider/webhook before launch.
export const LEAD_ENDPOINT = process.env.NEXT_PUBLIC_LEAD_ENDPOINT || "";

// Reject any installer/release URL that isn't on the approved CloudFront host so a misconfigured
// env var can never silently point downloads at an unrelated hostname.
export function assertApprovedHost(url) {
  let host;
  try {
    host = new URL(url).hostname.toLowerCase();
  } catch (e) {
    throw new Error(`Invalid installer URL: ${url}`);
  }
  if (host !== APPROVED_INSTALLER_HOST) {
    throw new Error(`Refusing non-approved installer host "${host}" (expected ${APPROVED_INSTALLER_HOST})`);
  }
  return url;
}

export function resolveInstaller(env = process.env) {
  const url = env.NEXT_PUBLIC_WINDOWS_INSTALLER_URL || CLOUDFRONT_INSTALLER;
  const releasesBaseUrl = (env.NEXT_PUBLIC_WINDOWS_RELEASES_BASE_URL || CLOUDFRONT_RELEASES_BASE).replace(/\/+$/, "");
  const updateManifestUrl = env.NEXT_PUBLIC_WINDOWS_UPDATE_MANIFEST_URL || CLOUDFRONT_UPDATE_MANIFEST;
  const available = String(env.NEXT_PUBLIC_WINDOWS_INSTALLER_AVAILABLE || "false").toLowerCase() === "true";
  assertApprovedHost(url);
  assertApprovedHost(releasesBaseUrl);
  return { url, releasesBaseUrl, updateManifestUrl, available };
}

export function versionedInstallerUrl(version, env = process.env) {
  return `${resolveInstaller(env).releasesBaseUrl}/RoofSpanSetup-${version}.exe`;
}

const _installer = resolveInstaller();
export const WINDOWS_INSTALLER_URL = _installer.url;
export const WINDOWS_INSTALLER_AVAILABLE = _installer.available;
export const WINDOWS_RELEASES_BASE_URL = _installer.releasesBaseUrl;
export const WINDOWS_UPDATE_MANIFEST_URL = _installer.updateManifestUrl;

// Pricing (public, approved): one product, per-seat, 5-seat minimum.
export const PRICE_PER_SEAT = 49;
export const MIN_SEATS = 5;
export const STARTING_PRICE = PRICE_PER_SEAT * MIN_SEATS; // 245

export function seatCost(seats) {
  const n = Math.max(MIN_SEATS, Math.floor(Number(seats) || 0));
  return { seats: n, monthly: n * PRICE_PER_SEAT, atMinimum: n === MIN_SEATS };
}

// One status object consumed by header, hero, pricing, and download sections so they never disagree.
export function productStatus() {
  return WINDOWS_INSTALLER_AVAILABLE
    ? { available: true, label: "Available for Windows", primaryCtaLabel: "Download for Windows", primaryCtaHref: WINDOWS_INSTALLER_URL, primaryIsDownload: true }
    : { available: false, label: "Early access — launching soon", primaryCtaLabel: "Join Early Access", primaryCtaHref: "#early-access", primaryIsDownload: false };
}

export const SITE_NAV = [
  { href: "#product", label: "Product", testid: "site-nav-product" },
  { href: "#how-it-works", label: "How It Works", testid: "site-nav-how" },
  { href: "#why", label: "Why RoofSpan", testid: "site-nav-why" },
  { href: "#pricing", label: "Pricing", testid: "site-nav-pricing" },
  { href: "#data", label: "Security & Data", testid: "site-nav-data" },
];
