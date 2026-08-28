import { SITE_URL } from "../src/config";

// Generates /robots.txt at build. Allows all public pages and points at the canonical sitemap.
export default function robots() {
  return {
    rules: [{ userAgent: "*", allow: "/" }],
    sitemap: `${SITE_URL}/sitemap.xml`,
    host: SITE_URL,
  };
}
