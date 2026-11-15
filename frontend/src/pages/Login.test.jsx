import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AuthContext } from "../context/authContext";
import * as authService from "../services/authService";
import Login from "./Login";

vi.mock("../services/authService", () => ({
  login: vi.fn(),
  getCurrentUser: vi.fn(),
  logout: vi.fn(),
}));

function renderLogin(overrides = {}) {
  const auth = {
    user: null,
    isAuthenticated: false,
    isInitializing: false,
    notice: "",
    signIn: vi.fn(),
    signOut: vi.fn(),
    clearNotice: vi.fn(),
    ...overrides,
  };

  return render(
    <MemoryRouter initialEntries={["/login"]}>
      <AuthContext.Provider value={auth}>
        <Routes>
          <Route path="/login" element={<Login />} />
          <Route path="/" element={<div>Chat home</div>} />
        </Routes>
      </AuthContext.Provider>
    </MemoryRouter>,
  );
}

beforeEach(() => {
  vi.resetAllMocks();
});

describe("Login", () => {
  it("rejects an empty form before calling the API", async () => {
    const user = userEvent.setup();
    renderLogin();

    await user.click(screen.getByRole("button", { name: "Sign in" }));

    expect(screen.getByRole("alert")).toHaveTextContent(
      "Enter your email and password.",
    );
    expect(authService.login).not.toHaveBeenCalled();
  });

  it("shows the backend error when credentials are rejected", async () => {
    const user = userEvent.setup();
    authService.login.mockRejectedValue({
      response: {
        status: 401,
        data: { detail: "Invalid email or password" },
      },
    });

    renderLogin();

    await user.type(
      screen.getByLabelText("Email address"),
      "alice.morgan@example.com",
    );
    await user.type(screen.getByLabelText("Password"), "wrong-password");
    await user.click(screen.getByRole("button", { name: "Sign in" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Invalid email or password",
    );
  });

  it("fills the demo account and navigates after a successful login", async () => {
    const user = userEvent.setup();
    const signIn = vi.fn();
    const response = {
      access_token: "signed-token",
      token_type: "bearer",
      expires_in: 1800,
      user: {
        id: "user-1",
        name: "Alice Morgan",
        email: "alice.morgan@example.com",
        role: "customer",
      },
    };
    authService.login.mockResolvedValue(response);

    renderLogin({ signIn });

    await user.click(screen.getByRole("button", { name: "Use demo" }));
    await user.click(screen.getByRole("button", { name: "Sign in" }));

    expect(authService.login).toHaveBeenCalledWith(
      "alice.morgan@example.com",
      "Customer123!",
    );
    expect(signIn).toHaveBeenCalledWith(response);
    expect(await screen.findByText("Chat home")).toBeInTheDocument();
  });

  it("shows a session-expired notice from auth state", () => {
    renderLogin({ notice: "Your session expired. Please sign in again." });

    expect(screen.getByRole("alert")).toHaveTextContent(
      "Your session expired. Please sign in again.",
    );
  });
});
