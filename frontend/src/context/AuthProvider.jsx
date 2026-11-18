import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import * as authService from "../services/authService";
import { SESSION_EXPIRED_EVENT } from "../utils/authStorage";
import { AuthContext } from "./authContext";

const SESSION_EXPIRED_MESSAGE =
  "Your session expired. Please sign in again.";
const REFRESH_LEAD_SECONDS = 120;
const REFRESH_CHECK_INTERVAL_MS = 60_000;

function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  const [isInitializing, setIsInitializing] = useState(true);
  const [notice, setNotice] = useState("");

  const expiresAtRef = useRef(0);
  const refreshInFlightRef = useRef(null);

  const applySession = useCallback((tokenResponse) => {
    const lifetimeSeconds = Number(tokenResponse?.expires_in) || 0;
    expiresAtRef.current = Date.now() + lifetimeSeconds * 1000;
    setUser(tokenResponse?.user ?? null);
    setNotice("");
  }, []);

  const refreshSession = useCallback(
    async ({ initial = false } = {}) => {
      if (refreshInFlightRef.current) {
        return refreshInFlightRef.current;
      }

      const task = authService
        .refresh()
        .then((tokenResponse) => {
          applySession(tokenResponse);
          return tokenResponse;
        })
        .catch((error) => {
          if (error?.response?.status === 401) {
            expiresAtRef.current = 0;
            setUser(null);
            if (!initial) {
              setNotice(SESSION_EXPIRED_MESSAGE);
            }
          }
          return null;
        })
        .finally(() => {
          refreshInFlightRef.current = null;
        });

      refreshInFlightRef.current = task;
      return task;
    },
    [applySession],
  );

  // On first load, try to restore the session from the HttpOnly refresh
  // cookie. A 401 simply means the visitor is signed out, not that a session
  // expired during this visit.
  useEffect(() => {
    let cancelled = false;

    refreshSession({ initial: true }).finally(() => {
      if (!cancelled) {
        setIsInitializing(false);
      }
    });

    return () => {
      cancelled = true;
    };
  }, [refreshSession]);

  // Proactively renew the access cookie shortly before it expires. The API
  // client also retries after a 401, so the user is covered even if a timer is
  // delayed by a suspended laptop or a background tab.
  useEffect(() => {
    if (!user) {
      return undefined;
    }

    const maybeRefresh = () => {
      if (
        document.visibilityState === "hidden" ||
        !expiresAtRef.current
      ) {
        return;
      }
      const remaining = expiresAtRef.current - Date.now();
      if (remaining <= REFRESH_LEAD_SECONDS * 1000) {
        refreshSession();
      }
    };

    const intervalId = window.setInterval(
      maybeRefresh,
      REFRESH_CHECK_INTERVAL_MS,
    );
    document.addEventListener("visibilitychange", maybeRefresh);

    return () => {
      window.clearInterval(intervalId);
      document.removeEventListener("visibilitychange", maybeRefresh);
    };
  }, [user, refreshSession]);

  useEffect(() => {
    const handleExpired = () => {
      expiresAtRef.current = 0;
      setUser(null);
      setNotice(SESSION_EXPIRED_MESSAGE);
    };

    window.addEventListener(SESSION_EXPIRED_EVENT, handleExpired);
    return () => {
      window.removeEventListener(SESSION_EXPIRED_EVENT, handleExpired);
    };
  }, []);

  const signIn = useCallback(
    (tokenResponse) => {
      applySession(tokenResponse);
      return tokenResponse?.user ?? null;
    },
    [applySession],
  );

  const signOut = useCallback(async () => {
    try {
      await authService.logout();
    } catch {
      // Cookies may already be gone; local state must still be cleared.
    } finally {
      expiresAtRef.current = 0;
      setUser(null);
      setNotice("");
    }
  }, []);

  const clearNotice = useCallback(() => setNotice(""), []);

  const value = useMemo(
    () => ({
      user,
      isAdmin: user?.role === "admin",
      isAuthenticated: Boolean(user),
      isInitializing,
      notice,
      signIn,
      signOut,
      clearNotice,
    }),
    [
      user,
      isInitializing,
      notice,
      signIn,
      signOut,
      clearNotice,
    ],
  );

  return (
    <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
  );
}

export default AuthProvider;
