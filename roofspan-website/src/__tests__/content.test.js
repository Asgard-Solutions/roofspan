import { PRICE_PER_SEAT, MIN_SEATS, STARTING_PRICE, FEATURES, STEPS, INCLUSIONS, SITE_NAV } from "../content";

describe("public website content", () => {
  test("approved pricing: $49/seat, 5-seat minimum, starting at $245", () => {
    expect(PRICE_PER_SEAT).toBe(49);
    expect(MIN_SEATS).toBe(5);
    expect(STARTING_PRICE).toBe(245);
  });

  test("has the six approved feature blocks", () => {
    expect(FEATURES).toHaveLength(6);
    expect(FEATURES.map((f) => f.title)).toContain("Local Company Data");
  });

  test("has the four how-it-works steps", () => {
    expect(STEPS).toHaveLength(4);
  });

  test("nav does not expose a Sign In / Web App link", () => {
    const labels = SITE_NAV.map((n) => n.label.toLowerCase()).join(" ");
    expect(labels).not.toMatch(/sign in|web app|dashboard|login/);
    expect(SITE_NAV).toHaveLength(5);
  });

  test("inclusions describe real, supported functionality", () => {
    expect(INCLUSIONS.length).toBeGreaterThan(0);
    expect(INCLUSIONS.join(" ")).toMatch(/Windows/);
  });
});
