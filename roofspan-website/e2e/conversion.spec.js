import { test, expect } from "@playwright/test";

test("homepage: hero, no login links, and early-access conversion (mailto fallback)", async ({ page }) => {
  await page.goto("/");
  await expect(page.locator("h1")).toContainText(/finished roof/i);
  await expect(page.getByTestId("status-badge")).toContainText(/early access/i);
  await expect(page.getByTestId("hero-primary-cta")).toContainText(/Join Early Access/i);

  const banned = page.locator("a", { hasText: /login|sign in|dashboard/i });
  await expect(banned).toHaveCount(0);

  await page.getByTestId("hero-primary-cta").click();
  await page.getByTestId("form-submit").click();
  await expect(page.getByText(/enter your name/i)).toBeVisible();
  await page.getByTestId("field-name").fill("Jane Roofer");
  await page.getByTestId("field-email").fill("jane@example.com");
  await page.getByTestId("field-company").fill("Example Roofing Co");
  await page.getByTestId("field-consent").check();
  await page.getByTestId("form-submit").click();
  await expect(page.getByTestId("form-mailto")).toBeVisible();
});

test("primary nav links to real crawlable pages", async ({ page }) => {
  await page.goto("/");
  await page.getByTestId("site-nav-pricing").click();
  await expect(page).toHaveURL(/\/roofing-software-pricing\/?$/);
  await expect(page.locator("h1")).toContainText(/pricing/i);
  await page.getByTestId("seat-number").fill("10");
  await expect(page.getByTestId("seat-total")).toContainText("$490");
});

test("commercial page has one h1, breadcrumbs, canonical, and JSON-LD", async ({ page }) => {
  await page.goto("/abc-supply-integration/");
  await expect(page.locator("h1")).toHaveCount(1);
  await expect(page.getByTestId("breadcrumbs")).toBeVisible();
  const canonical = await page.locator('link[rel="canonical"]').getAttribute("href");
  expect(canonical).toBe("https://roofspan.io/abc-supply-integration/");
  const types = await page.locator('script[type="application/ld+json"]').allTextContents();
  const parsed = types.map((t) => JSON.parse(t));
  expect(parsed.some((d) => d["@type"] === "BreadcrumbList")).toBeTruthy();
  expect(parsed.some((d) => d["@type"] === "FAQPage")).toBeTruthy();
});

test("resources hub links to an article that links back to product pages", async ({ page }) => {
  await page.goto("/resources/");
  await expect(page.locator("h1")).toContainText(/resources/i);
  await page.getByTestId("resource-roofing-crm-software-buyers-guide").click();
  await expect(page).toHaveURL(/\/resources\/roofing-crm-software-buyers-guide\/?$/);
  await expect(page.locator("h1")).toBeVisible();
  await expect(page.getByTestId("article-link-roofing-crm-software")).toBeVisible();
});

test("sitemap, robots and favicon assets are served", async ({ request }) => {
  const sm = await request.get("/sitemap.xml");
  expect(sm.status()).toBe(200);
  const smText = await sm.text();
  expect(smText).toContain("https://roofspan.io/roofing-crm-software/");
  expect(smText).not.toContain("www.roofspan.io");

  const rb = await request.get("/robots.txt");
  expect(rb.status()).toBe(200);
  expect(await rb.text()).toContain("https://roofspan.io/sitemap.xml");

  const ico = await request.get("/favicon.ico");
  expect(ico.status()).toBe(200);
});

test("unknown route returns a real 404", async ({ request }) => {
  const res = await request.get("/this-page-does-not-exist/");
  expect(res.status()).toBe(404);
});
