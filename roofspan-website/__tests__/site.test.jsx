import { render, screen, within, fireEvent } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import Header from "../components/Header";
import Pricing from "../components/Pricing";
import EarlyAccessForm from "../components/EarlyAccessForm";
import Home from "../app/page";
import {
  seatCost, assertApprovedHost, resolveInstaller, productStatus,
  MIN_SEATS, PRICE_PER_SEAT, STARTING_PRICE,
} from "../src/config";

describe("installer config: single source of truth + host validation", () => {
  test("defaults to unavailable -> Join Early Access primary CTA", () => {
    const s = productStatus();
    expect(s.available).toBe(false);
    expect(s.primaryCtaLabel).toBe("Join Early Access");
    expect(s.primaryCtaHref).toBe("#early-access");
  });
  test("available env -> Download for Windows on approved host", () => {
    const inst = resolveInstaller({ NEXT_PUBLIC_WINDOWS_INSTALLER_AVAILABLE: "true" });
    expect(inst.available).toBe(true);
    expect(new URL(inst.url).hostname).toBe("downloads.roofspan.io");
  });
  test("rejects unapproved installer host", () => {
    expect(() => assertApprovedHost("https://evil.example.com/x.exe")).toThrow(/non-approved installer host/);
    expect(() => resolveInstaller({ NEXT_PUBLIC_WINDOWS_INSTALLER_URL: "https://cdn.hacker.io/x.exe" })).toThrow(/non-approved/);
  });
  test("accepts approved CloudFront host", () => {
    expect(assertApprovedHost("https://downloads.roofspan.io/latest/RoofSpanSetup.exe")).toMatch(/downloads.roofspan.io/);
  });
});

describe("seat calculator", () => {
  test("enforces 5-user minimum and computes cost", () => {
    expect(seatCost(1)).toEqual({ seats: MIN_SEATS, monthly: STARTING_PRICE, atMinimum: true });
    expect(seatCost(10).monthly).toBe(10 * PRICE_PER_SEAT);
    expect(seatCost(10).atMinimum).toBe(false);
  });
  test("UI updates total when seats change", async () => {
    render(<Pricing />);
    expect(screen.getByTestId("seat-total")).toHaveTextContent(`$${STARTING_PRICE}`);
    fireEvent.change(screen.getByTestId("seat-number"), { target: { value: "12" } });
    expect(screen.getByTestId("seat-total")).toHaveTextContent(`$${12 * PRICE_PER_SEAT}`);
  });
});

describe("mobile navigation accessibility", () => {
  test("toggles aria-expanded and controls the mobile nav", async () => {
    const user = userEvent.setup();
    render(<Header />);
    const btn = screen.getByTestId("mobile-menu-button");
    expect(btn).toHaveAttribute("aria-expanded", "false");
    expect(btn).toHaveAttribute("aria-controls", "mobile-nav");
    await user.click(btn);
    expect(btn).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByTestId("mobile-nav")).toBeVisible();
  });
});

describe("early-access form", () => {
  test("shows validation errors and does not fake success", async () => {
    const user = userEvent.setup();
    render(<EarlyAccessForm />);
    await user.click(screen.getByTestId("form-submit"));
    expect(await screen.findByText(/enter your name/i)).toBeInTheDocument();
    expect(screen.getByText(/valid work email/i)).toBeInTheDocument();
    expect(screen.queryByTestId("form-success")).toBeNull();
  });
  test("valid submit with no endpoint uses transparent mailto fallback (no fake success)", async () => {
    const user = userEvent.setup();
    delete window.location;
    window.location = { href: "" };
    render(<EarlyAccessForm />);
    await user.type(screen.getByTestId("field-name"), "Jane Roofer");
    await user.type(screen.getByTestId("field-email"), "jane@example.com");
    await user.type(screen.getByTestId("field-company"), "Example Roofing");
    await user.click(screen.getByTestId("field-consent"));
    await user.click(screen.getByTestId("form-submit"));
    expect(window.location.href).toMatch(/^mailto:support@roofspan\.io/);
    expect(await screen.findByTestId("form-mailto")).toBeInTheDocument();
    expect(screen.queryByTestId("form-success")).toBeNull();
  });
});

describe("homepage integrity", () => {
  test("renders one h1 and the key sections", () => {
    const { container } = render(<Home />);
    expect(container.querySelectorAll("h1")).toHaveLength(1);
    ["product", "how-it-works", "pricing", "data", "early-access"].forEach((id) => {
      expect(container.querySelector(`#${id}`)).toBeInTheDocument();
    });
  });
  test("has NO login / dashboard / web-app links", () => {
    const { container } = render(<Home />);
    const links = Array.from(container.querySelectorAll("a")).map((a) => (a.getAttribute("href") || "") + " " + a.textContent.toLowerCase());
    const banned = /(login|log in|sign in|sign-in|dashboard|\/app\b|web app|web-app|account)/i;
    links.forEach((l) => expect(l).not.toMatch(banned));
  });
  test("pricing reflects approved numbers", () => {
    render(<Home />);
    expect(screen.getAllByText(/\$49/).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/\$245\/month|from \$245|\$245/).length).toBeGreaterThan(0);
  });
});
