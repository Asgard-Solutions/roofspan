// SEO helpers — single source for per-page metadata, canonical URLs, and structured data.
// Canonical host is driven by SITE_URL (https://roofspan.io by default). Every page produces an
// absolute canonical + Open Graph URL from this host so canonicals never disagree.
import { SITE_URL } from "./config";

export const absUrl = (path = "/") => `${SITE_URL}${path.startsWith("/") ? path : `/${path}`}`;

// Build a Next.js metadata object for a page. `path` must include a trailing slash to match export.
export function pageMeta({ title, description, path, image = "/brand/og.png", keywords }) {
  const url = absUrl(path);
  return {
    title,
    description,
    ...(keywords ? { keywords } : {}),
    alternates: { canonical: url },
    openGraph: {
      type: "website", url, siteName: "RoofSpan", title, description,
      images: [{ url: image, width: 1200, height: 630, alt: title }],
    },
    twitter: { card: "summary_large_image", title, description, images: [image] },
    robots: { index: true, follow: true },
  };
}

// BreadcrumbList JSON-LD. items: [{ name, path }] (Home first, current page last).
export function breadcrumbLd(items) {
  return {
    "@context": "https://schema.org", "@type": "BreadcrumbList",
    itemListElement: items.map((it, i) => ({
      "@type": "ListItem", position: i + 1, name: it.name, item: absUrl(it.path),
    })),
  };
}

// WebPage JSON-LD tied to the WebSite entity.
export function webPageLd({ title, description, path }) {
  return {
    "@context": "https://schema.org", "@type": "WebPage",
    name: title, description, url: absUrl(path),
    isPartOf: { "@type": "WebSite", name: "RoofSpan", url: SITE_URL },
    publisher: { "@type": "Organization", name: "RoofSpan", url: SITE_URL },
  };
}

// Article JSON-LD for resources.
export function articleLd({ title, description, path, datePublished }) {
  return {
    "@context": "https://schema.org", "@type": "Article",
    headline: title, description, url: absUrl(path),
    ...(datePublished ? { datePublished } : {}),
    author: { "@type": "Organization", name: "RoofSpan", url: SITE_URL },
    publisher: { "@type": "Organization", name: "RoofSpan", url: SITE_URL, logo: { "@type": "ImageObject", url: absUrl("/brand/favicon.png") } },
    mainEntityOfPage: { "@type": "WebPage", "@id": absUrl(path) },
    isPartOf: { "@type": "WebSite", name: "RoofSpan", url: SITE_URL },
  };
}

export function JsonLd({ data }) {
  return <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: JSON.stringify(data) }} />;
}
