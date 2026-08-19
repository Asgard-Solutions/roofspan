import { render, screen, waitFor, act } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Routes, Route } from "react-router-dom";
import axios from "axios";
import SetupGate from "./SetupGate";

// Manual axios mock: default export supports .get (used by SetupGate) and .create()/interceptors
// (used by src/lib/api.js which SetupGate imports transitively).
jest.mock("axios", () => {
  const instance = {
    get: jest.fn(),
    interceptors: { request: { use: jest.fn() }, response: { use: jest.fn() } },
  };
  const mock = {
    get: jest.fn(),
    create: jest.fn(() => instance),
    interceptors: instance.interceptors,
  };
  return { __esModule: true, default: mock };
});

function renderGate({ initialPath = "/login", retryIntervalMs = 5, maxAttempts = 3 } = {}) {
  return render(
    <MemoryRouter initialEntries={[initialPath]}>
      <SetupGate retryIntervalMs={retryIntervalMs} maxAttempts={maxAttempts}>
        <Routes>
          <Route path="/login" element={<div data-testid="page-login">LOGIN</div>} />
          <Route path="/setup" element={<div data-testid="page-setup">SETUP</div>} />
          <Route path="/" element={<div data-testid="page-home">HOME</div>} />
        </Routes>
      </SetupGate>
    </MemoryRouter>
  );
}

beforeEach(() => {
  axios.get.mockReset();
});

describe("SetupGate — RoofSpan Office first-run routing", () => {
  // A. Fresh install: /login must redirect to /setup, login never rendered.
  test("A: fresh install redirects /login -> /setup and never shows login", async () => {
    axios.get.mockResolvedValue({ data: { state: "setup_required" } });
    renderGate({ initialPath: "/login" });

    expect(await screen.findByTestId("page-setup")).toBeInTheDocument();
    expect(screen.queryByTestId("page-login")).not.toBeInTheDocument();
    expect(axios.get).toHaveBeenCalledWith(expect.stringContaining("/setup/status"));
  });

  // "any non-initialized onboarding state -> /setup"
  test("A2: payment_required (mid-onboarding) also routes to /setup", async () => {
    axios.get.mockResolvedValue({ data: { state: "payment_required" } });
    renderGate({ initialPath: "/login" });
    expect(await screen.findByTestId("page-setup")).toBeInTheDocument();
    expect(screen.queryByTestId("page-login")).not.toBeInTheDocument();
  });

  // B. Slow backend start: first requests fail, later succeeds; loading stays; login never flashes.
  test("B: slow startup retries behind loading, then lands on /setup without flashing login", async () => {
    axios.get
      .mockRejectedValueOnce(new Error("ECONNREFUSED"))
      .mockRejectedValueOnce(new Error("ECONNREFUSED"))
      .mockResolvedValue({ data: { state: "setup_required" } });

    renderGate({ initialPath: "/login", retryIntervalMs: 5, maxAttempts: 5 });

    // Startup/loading UI is shown immediately; children (router) are NOT rendered yet.
    expect(screen.getByTestId("setup-gate-loading")).toBeInTheDocument();
    expect(screen.queryByTestId("page-login")).not.toBeInTheDocument();

    expect(await screen.findByTestId("page-setup")).toBeInTheDocument();
    expect(screen.queryByTestId("page-login")).not.toBeInTheDocument();
    expect(axios.get.mock.calls.length).toBeGreaterThanOrEqual(3); // failed twice, then succeeded
  });

  // C. Initialized install: /login stays; /setup redirects out to normal app.
  test("C1: initialized install keeps /login available", async () => {
    axios.get.mockResolvedValue({ data: { state: "initialized" } });
    renderGate({ initialPath: "/login" });
    expect(await screen.findByTestId("page-login")).toBeInTheDocument();
    expect(screen.queryByTestId("page-setup")).not.toBeInTheDocument();
  });

  test("C2: initialized install visiting /setup is redirected to the app", async () => {
    axios.get.mockResolvedValue({ data: { state: "initialized" } });
    renderGate({ initialPath: "/setup" });
    expect(await screen.findByTestId("page-home")).toBeInTheDocument();
    expect(screen.queryByTestId("page-setup")).not.toBeInTheDocument();
  });

  // D. Backend unavailable: retries exhaust -> retryable error UI, no silent fall-through to /login.
  test("D: exhausted retries show a retryable startup error (never login)", async () => {
    axios.get.mockRejectedValue(new Error("ECONNREFUSED"));
    renderGate({ initialPath: "/login", retryIntervalMs: 5, maxAttempts: 3 });

    expect(await screen.findByTestId("setup-gate-error")).toBeInTheDocument();
    expect(screen.getByTestId("setup-gate-retry-button")).toBeInTheDocument();
    expect(screen.queryByTestId("page-login")).not.toBeInTheDocument();

    // User-triggered retry: backend now responds -> routes to /setup.
    axios.get.mockReset();
    axios.get.mockResolvedValue({ data: { state: "setup_required" } });
    await act(async () => {
      await userEvent.click(screen.getByTestId("setup-gate-retry-button"));
    });
    expect(await screen.findByTestId("page-setup")).toBeInTheDocument();
    expect(screen.queryByTestId("page-login")).not.toBeInTheDocument();
  });

  // E. Setup wizard reachability is preserved (the onboarding flow itself is unchanged; its full
  // company+owner+payment+dev-pay path is covered by backend tests/test_onboarding.py).
  test("E: uninitialized install renders the setup route (wizard entry preserved)", async () => {
    axios.get.mockResolvedValue({ data: { state: "setup_required" } });
    renderGate({ initialPath: "/setup" });
    expect(await screen.findByTestId("page-setup")).toBeInTheDocument();
  });
});
