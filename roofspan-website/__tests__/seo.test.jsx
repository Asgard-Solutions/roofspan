import { render } from "@testing-library/react";
import fs from "fs";
import path from "path";

import CommercialPage from "../components/CommercialPage";
import ArticlePage from "../components/ArticlePage";
import NotFound from "../app/not-found";
import sitemap from "../app/sitemap";
import robots from "../app/robots";
import { PAGES, PAGE_SLUGS } from "../src/pages";
import { ARTICLES, ARTICLE_SLUGS } from "../src/resources";
import { pageMeta, breadcrumbLd, webPageLd, articleLd, absUrl } from "../src/seo";
import { ANALYTICS_ENABLED, trackEvent } from "../src/analytics";
import { SITE_URL } from "../src/config";

// Import per-route exported metadata for the static pages.
import { metadata as crmMeta } from "../app/roofing-crm-software/page";
import { metadata as canvassMeta } from "../app/roofing-canvassing-software/page";
import { metadata as territoryMeta } from "../app/roofing-territory-management/page";
import { metadata as fieldMeta } from "../app/roofing-field-sales-software/page";
import { metadata as propMeta } from "../app/roofing-property-intelligence/page";
import { metadata as abcMeta } from "../app/abc-supply-integration/page";
import { metadata as jobMeta } from "../app/roofing-job-management-software/page";
import { metadata as pricingMeta } from "../app/roofing-software-pricing/page";
import { metadata as aboutMeta } from "../app/about/page";
import { metadata as contactMeta } from "../app/contact/page";
import { metadata as resourcesMeta } from "../app/resources/page";
import { metadata as rootMeta } from "../app/layout";

const ALL_META = {
  "/roofing-crm-software/": crmMeta,
  "/roofing-canvassing-software/": canvassMeta,
  "/roofing-territory-management/": territoryMeta,
  "/roofing-field-sales-software/": fieldMeta,
  "/roofing-property-intelligence/": propMeta,
  "/abc-supply-integration/": abcMeta,
  "/roofing-job-management-software/": jobMeta,
  "/roofing-software-pricing/": pricingMeta,
  "/about/": aboutMeta,
  "/contact/": contactMeta,
  "/resources/": resourcesMeta,
};

describe("canonical host + per-page metadata", () => {
  test("SITE_URL is the canonical https://roofspan.io host (no www)", () => {
    expect(SITE_URL).toBe("https://roofspan.io");
  });

  test.each(Object.entries(ALL_META))("%s has unique title, description, canonical + OG on the canonical host", (pathKey, meta) => {
    expect(typeof meta.title).toBe("string");
    expect(meta.title.length).toBeGreaterThan(10);
    expect(typeof meta.description).toBe("string");
    expect(meta.description.length).toBeGreaterThan(40);
    const canonical = meta.alternates.canonical;
    expect(canonical).toBe(`https://roofspan.io${pathKey}`);
    expect(canonical.endsWith("/")).toBe(true);
    expect(canonical.includes("www.")).toBe(false);
    expect(meta.openGraph.url).toBe(canonical);
    expect(meta.robots.index).toBe(true);
  });

  test("titles and descriptions are unique across pages", () => {
    const titles = Object.values(ALL_META).map((m) => m.title);
    const descs = Object.values(ALL_META).map((m) => m.description);
    expect(new Set(titles).size).toBe(titles.length);
    expect(new Set(descs).size).toBe(descs.length);
  });

  test("homepage title & description match the required strings", () => {
    expect(rootMeta.title).toBe("Roofing CRM & Canvassing Software | RoofSpan");
    expect(rootMeta.description).toMatch(/property intelligence, territory canvassing, field sales, jobs, and ABC Supply/i);
    expect(rootMeta.alternates.canonical).toBe("https://roofspan.io/");
  });
});

describe("commercial pages render", () => {
  test.each(PAGE_SLUGS)("%s renders exactly one H1, breadcrumbs, and related links", (slug) => {
    const { container, unmount } = render(<CommercialPage slug={slug} />);
    expect(container.querySelectorAll("h1")).toHaveLength(1);
    expect(container.querySelector('[data-testid="breadcrumbs"]')).toBeInTheDocument();
    const p = PAGES[slug];
    (p.related || []).forEach((r) => {
      expect(container.querySelector(`[data-testid="related-${r}"]`)).toBeInTheDocument();
    });
    // BreadcrumbList + WebPage JSON-LD present and valid JSON.
    const ld = Array.from(container.querySelectorAll('script[type="application/ld+json"]')).map((s) => JSON.parse(s.textContent));
    expect(ld.some((d) => d["@type"] === "BreadcrumbList")).toBe(true);
    expect(ld.some((d) => d["@type"] === "WebPage")).toBe(true);
    unmount();
  });

  test("ABC page carries FAQPage schema and an honest partnership disclaimer", () => {
    const { container, unmount } = render(<CommercialPage slug="abc-supply-integration" />);
    const ld = Array.from(container.querySelectorAll('script[type="application/ld+json"]')).map((s) => JSON.parse(s.textContent));
    expect(ld.some((d) => d["@type"] === "FAQPage")).toBe(true);
    const text = container.textContent.toLowerCase();
    expect(text).toContain("does not claim to be an official or certified abc supply partner");
    unmount();
  });
});

describe("resources articles render", () => {
  test.each(ARTICLE_SLUGS)("%s renders one H1 and links to product pages", (slug) => {
    const { container, unmount } = render(<ArticlePage slug={slug} />);
    expect(container.querySelectorAll("h1")).toHaveLength(1);
    const a = ARTICLES[slug];
    expect((a.related || []).length).toBeGreaterThan(0);
    (a.related || []).forEach((r) => {
      expect(container.querySelector(`[data-testid="article-link-${r}"]`)).toBeInTheDocument();
    });
    const ld = Array.from(container.querySelectorAll('script[type="application/ld+json"]')).map((s) => JSON.parse(s.textContent));
    expect(ld.some((d) => d["@type"] === "Article")).toBe(true);
    unmount();
  });
});

describe("404", () => {
  test("NotFound is noindex and offers a route home", () => {
    const NotFoundMeta = require("../app/not-found").metadata;
    expect(NotFoundMeta.robots.index).toBe(false);
    const { getByTestId } = render(<NotFound />);
    expect(getByTestId("not-found")).toBeInTheDocument();
    expect(getByTestId("notfound-home")).toHaveAttribute("href", "/");
  });
});

describe("sitemap + robots", () => {
  const entries = sitemap();
  test("includes every public page, absolute + canonical host, no duplicates", () => {
    const urls = entries.map((e) => e.url);
    expect(new Set(urls).size).toBe(urls.length);
    urls.forEach((u) => { expect(u.startsWith("https://roofspan.io/")).toBe(true); expect(u.includes("www.")).toBe(false); });
    const expected = [
      "https://roofspan.io/",
      ...PAGE_SLUGS.map((s) => `https://roofspan.io/${s}/`),
      "https://roofspan.io/roofing-software-pricing/",
      "https://roofspan.io/about/",
      "https://roofspan.io/contact/",
      "https://roofspan.io/resources/",
      ...ARTICLE_SLUGS.map((s) => `https://roofspan.io/resources/${s}/`),
    ];
    expected.forEach((u) => expect(urls).toContain(u));
  });
  test("does not include API/internal/404 routes", () => {
    const urls = entries.map((e) => e.url);
    urls.forEach((u) => { expect(u).not.toMatch(/\/api\//); expect(u).not.toMatch(/404/); });
  });
  test("robots allows all and references the canonical sitemap", () => {
    const r = robots();
    expect(r.rules[0].allow).toBe("/");
    expect(r.sitemap).toBe("https://roofspan.io/sitemap.xml");
  });
});

describe("structured data helpers", () => {
  test("breadcrumbLd / webPageLd / articleLd produce valid schema objects", () => {
    const bc = breadcrumbLd([{ name: "Home", path: "/" }, { name: "CRM", path: "/roofing-crm-software/" }]);
    expect(bc["@type"]).toBe("BreadcrumbList");
    expect(bc.itemListElement[0].item).toBe("https://roofspan.io/");
    expect(JSON.parse(JSON.stringify(bc))).toBeTruthy();
    const wp = webPageLd({ title: "t", description: "d", path: "/about/" });
    expect(wp["@type"]).toBe("WebPage");
    expect(wp.url).toBe("https://roofspan.io/about/");
    const art = articleLd({ title: "t", description: "d", path: "/resources/x/", datePublished: "2026-06-01" });
    expect(art["@type"]).toBe("Article");
    expect(art.datePublished).toBe("2026-06-01");
  });
  test("no fake rating/review schema anywhere in helpers or page content", () => {
    const dumps = [
      JSON.stringify(PAGES), JSON.stringify(ARTICLES),
      ...PAGE_SLUGS.map((s) => JSON.stringify(webPageLd({ title: PAGES[s].title, description: PAGES[s].description, path: `/${s}/` }))),
    ].join(" ");
    expect(dumps).not.toMatch(/aggregateRating|"@type":\s*"Review"|ratingValue/i);
  });
});

describe("favicon + brand assets exist", () => {
  test.each(["favicon.ico", "brand/favicon.png", "brand/apple-touch-icon.png", "brand/og.png"])("public/%s exists", (rel) => {
    expect(fs.existsSync(path.join(process.cwd(), "public", rel))).toBe(true);
  });
});

describe("content integrity", () => {
  test("every page screenshot references a real file in public/screenshots", () => {
    PAGE_SLUGS.forEach((s) => {
      const src = PAGES[s].screenshot.src;
      expect(fs.existsSync(path.join(process.cwd(), "public", src.replace(/^\//, "")))).toBe(true);
    });
  });
  test("every related link points at a real page slug or pricing", () => {
    const valid = new Set([...PAGE_SLUGS, "roofing-software-pricing"]);
    PAGE_SLUGS.forEach((s) => (PAGES[s].related || []).forEach((r) => expect(valid.has(r)).toBe(true)));
    ARTICLE_SLUGS.forEach((s) => (ARTICLES[s].related || []).forEach((r) => expect(valid.has(r)).toBe(true)));
  });
});

describe("analytics safety", () => {
  test("disabled by default and trackEvent never throws", () => {
    expect(ANALYTICS_ENABLED).toBe(false);
    expect(() => trackEvent("test_event", { a: 1 })).not.toThrow();
  });
});
