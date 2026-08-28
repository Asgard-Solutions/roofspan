import { SITE_URL } from "../src/config";
import { PAGE_SLUGS } from "../src/pages";
import { ARTICLE_SLUGS } from "../src/resources";

// Generates /sitemap.xml at build (static export). Only public, indexable pages — no API/internal/404.
export default function sitemap() {
  const now = new Date();
  const staticPaths = ["/", "/roofing-software-pricing/", "/about/", "/contact/", "/resources/"];
  const productPaths = PAGE_SLUGS.map((s) => `/${s}/`);
  const articlePaths = ARTICLE_SLUGS.map((s) => `/resources/${s}/`);
  const all = [...staticPaths, ...productPaths, ...articlePaths];
  return all.map((path) => ({
    url: `${SITE_URL}${path}`,
    lastModified: now,
    changeFrequency: path === "/" ? "weekly" : "monthly",
    priority: path === "/" ? 1.0 : path.startsWith("/resources/") && path !== "/resources/" ? 0.6 : 0.8,
  }));
}
