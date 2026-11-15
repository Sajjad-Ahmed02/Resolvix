import { useState } from "react";
import { Navigate, useLocation, useNavigate } from "react-router-dom";

import FullPageLoader from "../components/FullPageLoader";
import { BrandMark } from "../components/icons";
import { useAuth } from "../context/useAuth";
import * as authService from "../services/authService";
import { getErrorMessage } from "../utils/apiError";

const DEMO_EMAIL = "alice.morgan@example.com";
const DEMO_PASSWORD = "Customer123!";

const PORTAL_NOTES = [
  ["01", "Sign in with your customer account."],
  ["02", "Open any conversation from your history."],
  ["03", "Send a message and return to it later."],
];

function Login() {
  const {
    isAuthenticated,
    isInitializing,
    notice,
    signIn,
    clearNotice,
  } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [error, setError] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);

  const destination = location.state?.from || "/";
  const displayedError = error || notice;

  if (isInitializing) {
    return <FullPageLoader label="Checking your session…" />;
  }

  if (isAuthenticated) {
    return <Navigate to={destination} replace />;
  }

  const handleSubmit = async (event) => {
    event.preventDefault();
    const normalizedEmail = email.trim();

    if (!normalizedEmail || !password) {
      setError("Enter your email and password.");
      return;
    }

    if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(normalizedEmail)) {
      setError("Enter a valid email address.");
      return;
    }

    setError("");
    clearNotice();
    setIsSubmitting(true);

    try {
      const response = await authService.login(normalizedEmail, password);
      signIn(response);
      navigate(destination, { replace: true });
    } catch (requestError) {
      setError(
        getErrorMessage(
          requestError,
          "We could not sign you in. Please try again.",
        ),
      );
    } finally {
      setIsSubmitting(false);
    }
  };

  const fillDemoAccount = () => {
    setEmail(DEMO_EMAIL);
    setPassword(DEMO_PASSWORD);
    setError("");
    clearNotice();
  };

  return (
    <div className="min-h-dvh bg-stone-100 text-stone-900">
      <div className="mx-auto flex min-h-dvh w-full max-w-6xl flex-col px-5 sm:px-8">
        <header className="flex items-center justify-between border-b border-stone-200 py-5">
          <div className="flex items-center gap-2.5">
            <BrandMark className="h-8 w-8 text-sm" />
            <span className="text-sm font-semibold tracking-tight">
              Resolvix
            </span>
          </div>
          <span className="text-xs text-stone-500">Customer support</span>
        </header>

        <main className="grid flex-1 items-center gap-12 py-10 lg:grid-cols-[minmax(0,1fr)_24rem] lg:gap-20 lg:py-16">
          <section className="hidden lg:block">
            <p className="text-xs font-medium uppercase tracking-[0.14em] text-green-800">
              Customer portal
            </p>
            <h1 className="mt-5 max-w-xl font-serif text-5xl leading-[1.08] tracking-tight text-stone-950">
              Your conversations, kept in one place.
            </h1>
            <p className="mt-6 max-w-md text-[15px] leading-7 text-stone-600">
              Sign in to continue an existing conversation or start a new one.
              Every message is saved to your account, so you can pick it up
              later.
            </p>

            <dl className="mt-10 max-w-md divide-y divide-stone-200 border-y border-stone-200">
              {PORTAL_NOTES.map(([number, note]) => (
                <div key={number} className="flex gap-4 py-3.5">
                  <dt className="w-5 shrink-0 font-mono text-[11px] leading-5 text-stone-400">
                    {number}
                  </dt>
                  <dd className="text-sm leading-5 text-stone-700">{note}</dd>
                </div>
              ))}
            </dl>
          </section>

          <section className="w-full max-w-md justify-self-center lg:justify-self-end">
            <div className="rounded-lg border border-stone-200 bg-white p-6 sm:p-8">
              <p className="text-xs font-medium uppercase tracking-[0.14em] text-green-800">
                Sign in
              </p>
              <h2 className="mt-3 text-2xl font-semibold tracking-tight text-stone-950">
                Welcome back
              </h2>
              <p className="mt-2 text-sm leading-6 text-stone-500">
                Use your customer account to open your conversations.
              </p>

              {displayedError ? (
                <div
                  className="mt-5 rounded-md border border-red-200 bg-red-50 px-3.5 py-3 text-sm leading-5 text-red-800"
                  role="alert"
                >
                  {displayedError}
                </div>
              ) : null}

              <form
                className="mt-6 space-y-4"
                onSubmit={handleSubmit}
                noValidate
              >
                <div>
                  <label
                    htmlFor="email"
                    className="mb-1.5 block text-[13px] font-medium text-stone-700"
                  >
                    Email address
                  </label>
                  <input
                    id="email"
                    name="email"
                    type="email"
                    autoComplete="email"
                    value={email}
                    onChange={(event) => setEmail(event.target.value)}
                    placeholder="you@example.com"
                    className="w-full rounded-md border border-stone-300 bg-white px-3 py-2.5 text-sm text-stone-900 outline-none transition placeholder:text-stone-400 focus:border-green-800 focus:ring-2 focus:ring-green-800/10"
                  />
                </div>

                <div>
                  <label
                    htmlFor="password"
                    className="mb-1.5 block text-[13px] font-medium text-stone-700"
                  >
                    Password
                  </label>
                  <div className="relative">
                    <input
                      id="password"
                      name="password"
                      type={showPassword ? "text" : "password"}
                      autoComplete="current-password"
                      value={password}
                      onChange={(event) => setPassword(event.target.value)}
                      placeholder="Enter your password"
                      className="w-full rounded-md border border-stone-300 bg-white px-3 py-2.5 pr-14 text-sm text-stone-900 outline-none transition placeholder:text-stone-400 focus:border-green-800 focus:ring-2 focus:ring-green-800/10"
                    />
                    <button
                      type="button"
                      onClick={() => setShowPassword((visible) => !visible)}
                      className="absolute inset-y-0 right-0 px-3 text-xs font-medium text-stone-500 transition hover:text-stone-900 focus:outline-none focus-visible:text-stone-900 focus-visible:underline"
                      aria-label={
                        showPassword ? "Hide password" : "Show password"
                      }
                    >
                      {showPassword ? "Hide" : "Show"}
                    </button>
                  </div>
                </div>

                <button
                  type="submit"
                  disabled={isSubmitting}
                  className="flex w-full items-center justify-center gap-2 rounded-md bg-stone-950 px-4 py-2.5 text-sm font-medium text-white transition hover:bg-stone-800 focus:outline-none focus-visible:ring-2 focus-visible:ring-stone-900 focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-60"
                >
                  {isSubmitting ? (
                    <>
                      <span
                        className="h-4 w-4 animate-spin rounded-full border-2 border-white/30 border-t-white"
                        aria-hidden="true"
                      />
                      Signing in…
                    </>
                  ) : (
                    "Sign in"
                  )}
                </button>
              </form>

              <div className="mt-7 border-t border-stone-200 pt-5">
                <div className="flex items-start justify-between gap-4">
                  <div>
                    <p className="text-xs font-medium text-stone-500">
                      Development account
                    </p>
                    <p className="mt-1 text-sm text-stone-800">{DEMO_EMAIL}</p>
                    <p className="mt-0.5 font-mono text-xs text-stone-500">
                      {DEMO_PASSWORD}
                    </p>
                  </div>
                  <button
                    type="button"
                    onClick={fillDemoAccount}
                    className="shrink-0 rounded-md border border-stone-300 px-3 py-1.5 text-xs font-medium text-stone-700 transition hover:border-stone-400 hover:bg-stone-50 focus:outline-none focus-visible:ring-2 focus-visible:ring-green-800/20"
                  >
                    Use demo
                  </button>
                </div>
              </div>
            </div>

            <p className="mt-4 text-center text-[11px] leading-5 text-stone-500">
              Development environment · Synthetic customer data only
            </p>
          </section>
        </main>
      </div>
    </div>
  );
}

export default Login;
