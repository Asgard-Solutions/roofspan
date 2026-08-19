import { render, screen, act } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Routes, Route } from "react-router-dom";
import Login from "./Login";
import { AuthProvider } from "@/context/AuthContext";

// axios is imported transitively via src/lib/api.js (AuthContext). Mock it so the module loads.
jest.mock("axios", () => {
  const instance = { interceptors: { request: { use: jest.fn() }, response: { use: jest.fn() } } };
  return {
    __esModule: true,
    default: { create: jest.fn(() => instance), interceptors: instance.interceptors, post: jest.fn() },
  };
});

function renderLogin() {
  return render(
    <MemoryRouter initialEntries={["/login"]}>
      <AuthProvider>
        <Routes>
          <Route path="/login" element={<Login />} />
          <Route path="/setup" element={<div data-testid="page-setup">SETUP</div>} />
        </Routes>
      </AuthProvider>
    </MemoryRouter>
  );
}

describe("Login — dual entry for existing and new customers", () => {
  test("Sign in remains the primary action", () => {
    renderLogin();
    expect(screen.getByTestId("login-submit-button")).toHaveTextContent(/sign in/i);
    expect(screen.getByTestId("login-email-input")).toBeInTheDocument();
    expect(screen.getByTestId("login-password-input")).toBeInTheDocument();
  });

  test("shows a visible Create Account action for new customers", () => {
    renderLogin();
    const link = screen.getByTestId("login-register-link");
    expect(link).toBeInTheDocument();
    expect(link).toHaveTextContent(/create your company account/i);
  });

  test("Create Account navigates into the existing /setup onboarding flow", async () => {
    renderLogin();
    await act(async () => {
      await userEvent.click(screen.getByTestId("login-register-link"));
    });
    expect(await screen.findByTestId("page-setup")).toBeInTheDocument();
  });
});
