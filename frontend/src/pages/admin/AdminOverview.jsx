import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import {
  BookIcon,
  ChatIcon,
  DocumentIcon,
  OrderIcon,
  SparkIcon,
} from "../../components/icons";
import {
  FeedbackBanner,
  PageHeader,
  secondaryButtonClass,
} from "../../components/admin/AdminUi";
import * as adminService from "../../services/adminService";
import { getErrorMessage } from "../../utils/apiError";

const CARDS = [
  { key: "customers", label: "Customers", detail: "users" },
  { key: "orders", label: "Orders", detail: "synthetic records" },
  { key: "conversations", label: "Conversations", detail: "customer chats" },
  { key: "active_faqs", label: "Active FAQs", detail: "of {faqs} total" },
  {
    key: "active_documents",
    label: "Active documents",
    detail: "of {documents} total",
  },
];

function AdminOverview() {
  const [stats, setStats] = useState(null);
  const [users, setUsers] = useState([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;

    Promise.all([adminService.getStats(), adminService.listUsers()])
      .then(([statsData, usersData]) => {
        if (cancelled) {
          return;
        }
        setStats(statsData);
        setUsers(usersData);
      })
      .catch((requestError) => {
        if (!cancelled) {
          setError(
            getErrorMessage(
              requestError,
              "Could not load the dashboard.",
            ),
          );
        }
      })
      .finally(() => {
        if (!cancelled) {
          setIsLoading(false);
        }
      });

    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="Administration"
        title="Dashboard overview"
        description="Manage the synthetic store data and the knowledge used by the support agent."
        actions={
          <>
            <Link to="/admin/ai" className={secondaryButtonClass}>
              <SparkIcon className="h-3.5 w-3.5" />
              Test the agent
            </Link>
            <Link to="/admin/faqs" className={secondaryButtonClass}>
              <BookIcon className="h-3.5 w-3.5" />
              Manage knowledge
            </Link>
          </>
        }
      />

      {error ? <FeedbackBanner tone="error">{error}</FeedbackBanner> : null}

      {isLoading ? (
        <p className="text-sm text-stone-500">Loading dashboard…</p>
      ) : stats ? (
        <>
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-5">
            {CARDS.map(({ key, label, detail }) => (
              <div
                key={key}
                className="rounded-lg border border-stone-200 bg-white p-5"
              >
                <p className="text-xs font-medium uppercase tracking-[0.12em] text-stone-500">
                  {label}
                </p>
                <p className="mt-3 text-3xl font-semibold tracking-tight text-stone-950">
                  {stats[key]}
                </p>
                <p className="mt-1 text-xs text-stone-500">
                  {detail
                    .replace("{faqs}", stats.faqs)
                    .replace("{documents}", stats.documents)}
                </p>
              </div>
            ))}
          </div>

          <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_20rem]">
            <section className="overflow-hidden rounded-lg border border-stone-200 bg-white">
              <div className="flex items-center justify-between border-b border-stone-200 px-5 py-3.5">
                <h2 className="text-sm font-semibold text-stone-900">
                  Users
                </h2>
                <span className="text-xs text-stone-500">
                  {stats.users} total
                </span>
              </div>
              <div className="overflow-x-auto">
                <table className="w-full text-left text-sm">
                  <thead className="bg-stone-50 text-xs uppercase tracking-wide text-stone-500">
                    <tr>
                      <th className="px-5 py-2.5 font-medium">Name</th>
                      <th className="px-5 py-2.5 font-medium">Email</th>
                      <th className="px-5 py-2.5 font-medium">Role</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-stone-100">
                    {users.map((user) => (
                      <tr key={user.id}>
                        <td className="px-5 py-2.5 text-stone-900">
                          {user.name}
                        </td>
                        <td className="px-5 py-2.5 text-stone-600">
                          {user.email}
                        </td>
                        <td className="px-5 py-2.5 capitalize text-stone-600">
                          {user.role}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>

            <section className="rounded-lg border border-stone-200 bg-white p-5">
              <h2 className="text-sm font-semibold text-stone-900">
                Quick actions
              </h2>
              <div className="mt-4 space-y-2">
                {[
                  {
                    to: "/admin/faqs",
                    icon: BookIcon,
                    label: "Add or edit an FAQ",
                  },
                  {
                    to: "/admin/documents",
                    icon: DocumentIcon,
                    label: "Update a knowledge document",
                  },
                  {
                    to: "/admin/orders",
                    icon: OrderIcon,
                    label: "Create a synthetic order",
                  },
                  {
                    to: "/admin/conversations",
                    icon: ChatIcon,
                    label: "Inspect customer conversations",
                  },
                ].map(({ to, icon: Icon, label }) => (
                  <Link
                    key={to}
                    to={to}
                    className="flex items-center gap-2.5 rounded-md border border-stone-200 px-3 py-2.5 text-sm text-stone-700 transition hover:border-stone-300 hover:bg-stone-50"
                  >
                    <Icon className="h-4 w-4 text-stone-500" />
                    {label}
                  </Link>
                ))}
              </div>
            </section>
          </div>
        </>
      ) : null}
    </div>
  );
}

export default AdminOverview;
