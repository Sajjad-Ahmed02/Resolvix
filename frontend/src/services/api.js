import axios from "axios";

import { SESSION_EXPIRED_EVENT } from "../utils/authStorage";

const baseURL =
  import.meta.env.VITE_API_BASE_URL ||
  `${window.location.protocol}//${window.location.hostname}:8000`;

// Tokens are HttpOnly cookies set by the backend. `withCredentials` lets the
// browser attach them on every request; JavaScript never sees or stores them.
const api = axios.create({
  baseURL,
  timeout: 20000,
  withCredentials: true,
  headers: {
    "Content-Type": "application/json",
  },
});

// A separate client prevents the refresh call itself from re-entering the
// 401 interceptor.
const refreshClient = axios.create({
  baseURL,
  timeout: 20000,
  withCredentials: true,
  headers: {
    "Content-Type": "application/json",
  },
});

let refreshPromise = null;

function isAuthEndpoint(url) {
  if (typeof url !== "string") {
    return false;
  }
  return url.includes("/auth/login") || url.includes("/auth/refresh");
}

/**
 * Ask the backend to exchange the HttpOnly refresh cookie for a fresh access
 * cookie. Concurrent 401s share a single request so a burst of API calls does
 * not create a burst of refresh calls.
 */
export function refreshAccessToken() {
  if (!refreshPromise) {
    refreshPromise = refreshClient
      .post("/auth/refresh")
      .then((response) => response.data)
      .finally(() => {
        refreshPromise = null;
      });
  }
  return refreshPromise;
}

api.interceptors.response.use(
  (response) => response,
  async (error) => {
    const original = error.config;
    const status = error.response?.status;

    if (
      status !== 401 ||
      !original ||
      original._retriedAfterRefresh ||
      isAuthEndpoint(original.url)
    ) {
      return Promise.reject(error);
    }

    original._retriedAfterRefresh = true;

    try {
      await refreshAccessToken();
      return api.request(original);
    } catch {
      window.dispatchEvent(new Event(SESSION_EXPIRED_EVENT));
      return Promise.reject(error);
    }
  },
);

export default api;
