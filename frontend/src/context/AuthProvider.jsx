import { useCallback, useEffect, useMemo, useState } from "react";

import * as authService from "../services/authService";
import {
  clearStoredSession,
  readStoredSession,
  SESSION_EXPIRED_EVENT,
  writeStoredSession,
} from "../utils/authStorage";
import { AuthContext } from "./authContext";

const SESSION_EXPIRED_MESSAGE =
  "Your session expired. Please sign in again.";

function AuthProvider({ children }) {
  const [session, setSession] = useState(() => readStoredSession());
  const [isInitializing, setIsInitializing] = useState(
    () => Boolean(readStoredSession()),
  );
  const [notice, setNotice] = useState("");

  useEffect(() => {
    const handleExpired = () => {
      setSession(null);
      setNotice(SESSION_EXPIRED_MESSAGE);
    };

    window.addEventListener(SESSION_EXPIRED_EVENT, handleExpired);
    return () => {
      window.removeEventListener(SESSION_EXPIRED_EVENT, handleExpired);
    };
  }, []);

  useEffect(() => {
    const stored = readStoredSession();
    if (!stored) {
      return undefined;
    }

    let cancelled = false;

    authService
      .getCurrentUser()
      .then((user) => {
        if (cancelled) {
          return;
        }
        const refreshed = { ...stored, user };
        writeStoredSession(refreshed);
        setSession(refreshed);
      })
      .catch((error) => {
        if (cancelled || error?.response?.status !== 401) {
          return;
        }
        clearStoredSession();
        setSession(null);
        setNotice(SESSION_EXPIRED_MESSAGE);
      })
      .finally(() => {
        if (!cancelled) {
          setIsInitializing(false);
        }
      });

    return () => {
      cancelled = true;
    };
  }, []);

  const signIn = useCallback((tokenResponse) => {
    const nextSession = {
      accessToken: tokenResponse.access_token,
      user: tokenResponse.user,
      expiresAt: Date.now() + tokenResponse.expires_in * 1000,
    };
    writeStoredSession(nextSession);
    setSession(nextSession);
    setNotice("");
    return nextSession;
  }, []);

  const signOut = useCallback(async () => {
    try {
      await authService.logout();
    } catch {
      // Logout is client-side for stateless JWTs; clear local state even if
      // the server call fails.
    } finally {
      clearStoredSession();
      setSession(null);
      setNotice("");
    }
  }, []);

  const clearNotice = useCallback(() => setNotice(""), []);

  const value = useMemo(
    () => ({
      user: session?.user ?? null,
      isAuthenticated: Boolean(session?.accessToken && session?.user),
      isInitializing,
      notice,
      signIn,
      signOut,
      clearNotice,
    }),
    [
      session,
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
