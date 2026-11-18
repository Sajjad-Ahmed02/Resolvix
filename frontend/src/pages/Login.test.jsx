import { useState } from "react";
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

const customer = {
  id: "user-1",
  name: "Alice Morgan",
  email: "alice.morgan@example.com",
  role: "customer",
};

const administrator = {
  id: "user-2",
  name: "Avery Admin",
  email: "admin@resolvix.local",
  role: "admin",
};

function tokenResponse(user) {
  return {
    access_token: "signed-token",
    token_type: "bearer",
    expires_in: 1800,
    user,
  };
}

function renderLogin({
  initialEntries = ["/login"],
  overrides = {},
} = {}) {
  const signInSpy = vi.fn();

  function Harness() {
    const [currentUser, setCurrentUser] = useState(null);

    const auth = {
      user: currentUser,
      isAdmin: currentUser?.role === "admin",
      isAuthenticated: Boolean(currentUser),
      isInitializing: false,
      notice: "",
      signIn: (response) => {
        signInSpy(response);
        setCurrentUser(response.user);
        return response.user;
      },
      signOut: vi.fn(),
      clearNotice: vi.fn(),
      ...overrides,
    };

    return (
      <AuthContext.Provider value={auth}>
        <Routes>
          <Route path="/login" element={<Login />} />
          <Route path="/" element={<div>Chat home</div>} />
          <Route path="/admin" element={<div>Admin home</div>} />
          <Route path="/admin/orders" element={<div>Admin orders</div>} />
        </Routes>
      </AuthContext.Provider>
    );
  }

  return {
    signInSpy,
    ...render(
      <MemoryRouter initialEntries={initialEntries}>
        <Harness />
      </MemoryRouter>,
    ),
  };
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

  it("fills the customer demo account and opens the chat", async () => {
    const user = userEvent.setup();
    const response = tokenResponse(customer);
    authService.login.mockResolvedValue(response);

    const { signInSpy } = renderLogin();

    await user.click(screen.getByRole("button", { name: "Use demo" }));
    await user.click(screen.getByRole("button", { name: "Sign in" }));

    expect(authService.login).toHaveBeenCalledWith(
      "alice.morgan@example.com",
      "Customer123!",
    );
    expect(signInSpy).toHaveBeenCalledWith(response);
    expect(await screen.findByText("Chat home")).toBeInTheDocument();
  });

  it("sends an administrator to the dashboard after a root redirect", async () => {
    const user = userEvent.setup();
    authService.login.mockResolvedValue(tokenResponse(administrator));

    renderLogin({
      initialEntries: [{ pathname: "/login", state: { from: "/" } }],
    });

    await user.click(screen.getByRole("button", { name: "Use admin" }));
    await user.click(screen.getByRole("button", { name: "Sign in" }));

    expect(await screen.findByText("Admin home")).toBeInTheDocument();
    expect(screen.queryByText("Chat home")).not.toBeInTheDocument();
  });

  it("keeps an administrator's admin deep link", async () => {
    const user = userEvent.setup();
    authService.login.mockResolvedValue(tokenResponse(administrator));

    renderLogin({
      initialEntries: [
        { pathname: "/login", state: { from: "/admin/orders" } },
      ],
    });

    await user.click(screen.getByRole("button", { name: "Use admin" }));
    await user.click(screen.getByRole("button", { name: "Sign in" }));

    expect(await screen.findByText("Admin orders")).toBeInTheDocument();
  });

  it("sends a customer away from an admin deep link", async () => {
    const user = userEvent.setup();
    authService.login.mockResolvedValue(tokenResponse(customer));

    renderLogin({
      initialEntries: [
        { pathname: "/login", state: { from: "/admin/orders" } },
      ],
    });

    await user.click(screen.getByRole("button", { name: "Use demo" }));
    await user.click(screen.getByRole("button", { name: "Sign in" }));

    expect(await screen.findByText("Chat home")).toBeInTheDocument();
  });

  it("shows a session-expired notice from auth state", () => {
    renderLogin({
      overrides: { notice: "Your session expired. Please sign in again." },
    });

    expect(screen.getByRole("alert")).toHaveTextContent(
      "Your session expired. Please sign in again.",
    );
  });
});
