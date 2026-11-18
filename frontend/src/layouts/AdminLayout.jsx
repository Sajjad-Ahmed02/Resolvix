import { useState } from "react";
import { Link, NavLink, Outlet, useNavigate } from "react-router-dom";

import {
  BookIcon,
  BrandMark,
  ChatIcon,
  CloseIcon,
  DashboardIcon,
  DocumentIcon,
  LogoutIcon,
  MenuIcon,
  OrderIcon,
  SparkIcon,
} from "../components/icons";
import { useAuth } from "../context/useAuth";

const NAV_ITEMS = [
  { to: "/admin", label: "Overview", icon: DashboardIcon, end: true },
  { to: "/admin/faqs", label: "FAQs", icon: BookIcon },
  { to: "/admin/documents", label: "Documents", icon: DocumentIcon },
  { to: "/admin/orders", label: "Orders", icon: OrderIcon },
  { to: "/admin/conversations", label: "Conversations", icon: ChatIcon },
  { to: "/admin/ai", label: "AI testing", icon: SparkIcon },
];

function getInitials(name) {
  const parts = String(name || "")
    .trim()
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2);
  return parts.map((part) => part[0].toUpperCase()).join("") || "A";
}

function AdminLayout() {
  const { user, signOut } = useAuth();
  const navigate = useNavigate();
  const [isMenuOpen, setIsMenuOpen] = useState(false);

  const handleSignOut = async () => {
    await signOut();
    navigate("/login", { replace: true });
  };

  const nav = (
    <nav className="space-y-1" aria-label="Administration">
      {NAV_ITEMS.map(({ to, label, icon: Icon, end }) => (
        <NavLink
          key={to}
          to={to}
          end={end}
          onClick={() => setIsMenuOpen(false)}
          className={({ isActive }) =>
            `flex items-center gap-2.5 rounded-md px-3 py-2 text-sm font-medium transition ${
              isActive
                ? "bg-stone-950 text-white"
                : "text-stone-600 hover:bg-stone-200/70 hover:text-stone-950"
            }`
          }
        >
          <Icon className="h-4 w-4" />
          {label}
        </NavLink>
      ))}
    </nav>
  );

  return (
    <div className="min-h-dvh bg-stone-100 text-stone-900">
      <div className="mx-auto flex min-h-dvh w-full max-w-[100rem]">
        <aside className="hidden w-64 shrink-0 flex-col border-r border-stone-200 bg-white px-4 py-5 lg:flex">
          <Link to="/admin" className="flex items-center gap-2.5 px-2">
            <BrandMark className="h-8 w-8 text-sm" />
            <span>
              <span className="block text-sm font-semibold tracking-tight text-stone-950">
                Resolvix
              </span>
              <span className="block text-[11px] text-stone-500">
                Administration
              </span>
            </span>
          </Link>

          <div className="mt-8 flex-1">{nav}</div>

          <div className="mt-6 border-t border-stone-200 pt-4">
            <div className="flex items-center gap-2.5 px-2">
              <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-green-900 text-[11px] font-semibold text-white">
                {getInitials(user?.name)}
              </span>
              <span className="min-w-0">
                <span className="block truncate text-sm font-medium text-stone-900">
                  {user?.name}
                </span>
                <span className="block truncate text-[11px] text-stone-500">
                  {user?.email}
                </span>
              </span>
            </div>
            <Link
              to="/"
              className="mt-3 flex items-center gap-2 rounded-md px-3 py-2 text-xs font-medium text-stone-600 transition hover:bg-stone-100 hover:text-stone-950"
            >
              <ChatIcon className="h-3.5 w-3.5" />
              Open customer chat
            </Link>
            <button
              type="button"
              onClick={handleSignOut}
              className="mt-1 flex w-full items-center gap-2 rounded-md px-3 py-2 text-xs font-medium text-stone-600 transition hover:bg-stone-100 hover:text-stone-950"
            >
              <LogoutIcon className="h-3.5 w-3.5" />
              Sign out
            </button>
          </div>
        </aside>

        {isMenuOpen ? (
          <button
            type="button"
            className="fixed inset-0 z-30 bg-stone-950/40 lg:hidden"
            onClick={() => setIsMenuOpen(false)}
            aria-label="Close administration menu"
          />
        ) : null}

        <aside
          className={`fixed inset-y-0 left-0 z-40 flex w-72 flex-col border-r border-stone-200 bg-white px-4 py-5 transition-transform duration-200 lg:hidden ${
            isMenuOpen ? "translate-x-0" : "-translate-x-full"
          }`}
        >
          <div className="flex items-center justify-between px-2">
            <Link to="/admin" className="flex items-center gap-2.5">
              <BrandMark className="h-8 w-8 text-sm" />
              <span className="text-sm font-semibold tracking-tight">
                Resolvix Admin
              </span>
            </Link>
            <button
              type="button"
              onClick={() => setIsMenuOpen(false)}
              className="rounded-md p-1 text-stone-500 hover:bg-stone-100"
              aria-label="Close menu"
            >
              <CloseIcon className="h-4 w-4" />
            </button>
          </div>
          <div className="mt-8 flex-1">{nav}</div>
          <div className="border-t border-stone-200 pt-4">
            <Link
              to="/"
              className="flex items-center gap-2 rounded-md px-3 py-2 text-xs font-medium text-stone-600 hover:bg-stone-100"
            >
              <ChatIcon className="h-3.5 w-3.5" />
              Open customer chat
            </Link>
            <button
              type="button"
              onClick={handleSignOut}
              className="flex w-full items-center gap-2 rounded-md px-3 py-2 text-xs font-medium text-stone-600 hover:bg-stone-100"
            >
              <LogoutIcon className="h-3.5 w-3.5" />
              Sign out
            </button>
          </div>
        </aside>

        <div className="flex min-w-0 flex-1 flex-col">
          <header className="flex items-center justify-between border-b border-stone-200 bg-white px-4 py-3 lg:hidden">
            <button
              type="button"
              onClick={() => setIsMenuOpen(true)}
              className="rounded-md p-1.5 text-stone-600 hover:bg-stone-100"
              aria-label="Open administration menu"
            >
              <MenuIcon className="h-5 w-5" />
            </button>
            <span className="text-sm font-semibold tracking-tight">
              Resolvix Admin
            </span>
            <span className="flex h-7 w-7 items-center justify-center rounded-full bg-green-900 text-[10px] font-semibold text-white">
              {getInitials(user?.name)}
            </span>
          </header>

          <main className="flex-1 px-4 py-6 sm:px-6 lg:px-10 lg:py-8">
            <Outlet />
          </main>
        </div>
      </div>
    </div>
  );
}

export default AdminLayout;
