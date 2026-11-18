import api from "./api";

export async function login(email, password) {
  const { data } = await api.post("/auth/login", { email, password });
  return data;
}

/**
 * Restore or extend the browser session using the HttpOnly refresh cookie.
 * Resolves with a new access token payload and user; rejects with 401 when no
 * valid refresh session exists.
 */
export async function refresh() {
  const { data } = await api.post("/auth/refresh");
  return data;
}

export async function getCurrentUser() {
  const { data } = await api.get("/auth/me");
  return data;
}

export async function logout() {
  await api.post("/auth/logout");
}
