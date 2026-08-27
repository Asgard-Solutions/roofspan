import { test, expect } from "@playwright/test";

// Primary conversion journey: land -> navigate -> use calculator -> submit early-access form.
test("visitor can reach and complete the early-access conversion flow", async ({ page }) => {
  await page.goto("/");
  await expect(page.locator("h1")).toContainText(/finished roof/i);
  await expect(page.getByTestId("status-badge")).toContainText(/early access/i);
  await expect(page.getByTestId("hero-primary-cta")).toContainText(/Join Early Access/i);

  // No login/dashboard links anywhere.
  const banned = page.locator("a", { hasText: /login|sign in|dashboard/i });
  await expect(banned).toHaveCount(0);

  // Seat calculator.
  await page.getByTestId("site-nav-pricing").click();
  await page.getByTestId("seat-number").fill("10");
  await expect(page.getByTestId("seat-total")).toContainText("$490");

  // Early-access form validation then successful submit (mailto fallback path).
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
