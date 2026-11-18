import { useEffect, useState } from "react";

import {
  EmptyState,
  FeedbackBanner,
  PageHeader,
  StatusPill,
} from "../../components/admin/AdminUi";
import * as adminService from "../../services/adminService";
import { formatConversationTime } from "../../utils/date";
import { getAdminErrorMessage } from "../../utils/adminError";

const ROLE_TONES = {
  user: "sky",
  assistant: "green",
  tool: "stone",
};

function AdminConversations() {
  const [conversations, setConversations] = useState([]);
  const [selectedId, setSelectedId] = useState(null);
  const [detail, setDetail] = useState(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState("");
  const [detailError, setDetailError] = useState(null);

  useEffect(() => {
    let cancelled = false;

    const loadInitial = async () => {
      try {
        const data = await adminService.listConversations();
        if (cancelled) {
          return;
        }
        setConversations(data);
        setError("");
        if (data.length > 0) {
          setSelectedId((current) => current || data[0].id);
        }
      } catch (requestError) {
        if (!cancelled) {
          setError(
            getAdminErrorMessage(
              requestError,
              "Could not load conversations.",
            ),
          );
        }
      } finally {
        if (!cancelled) {
          setIsLoading(false);
        }
      }
    };

    loadInitial();
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (!selectedId) {
      return undefined;
    }

    let cancelled = false;

    const loadDetail = async () => {
      try {
        const data = await adminService.getConversation(selectedId);
        if (!cancelled) {
          setDetail(data);
        }
      } catch (requestError) {
        if (!cancelled) {
          setDetailError({
            id: selectedId,
            message: getAdminErrorMessage(
              requestError,
              "Could not load this conversation.",
            ),
          });
        }
      }
    };

    loadDetail();
    return () => {
      cancelled = true;
    };
  }, [selectedId]);

  const visibleDetail = detail?.id === selectedId ? detail : null;
  const visibleDetailError =
    detailError?.id === selectedId ? detailError.message : "";
  const isLoadingDetail =
    Boolean(selectedId) && !visibleDetail && !visibleDetailError;

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="Support history"
        title="Conversations"
        description="Inspect persisted customer conversations, including tool calls recorded by the agent."
      />

      {error ? <FeedbackBanner tone="error">{error}</FeedbackBanner> : null}

      {isLoading ? (
        <p className="text-sm text-stone-500">Loading conversations…</p>
      ) : conversations.length === 0 ? (
        <EmptyState
          title="No conversations yet"
          description="Customer chats will appear here after the first message."
        />
      ) : (
        <div className="grid gap-4 lg:grid-cols-[22rem_minmax(0,1fr)]">
          <div className="max-h-[70vh] overflow-y-auto rounded-lg border border-stone-200 bg-white">
            <ul className="divide-y divide-stone-100">
              {conversations.map((conversation) => (
                <li key={conversation.id}>
                  <button
                    type="button"
                    onClick={() => setSelectedId(conversation.id)}
                    className={`w-full px-4 py-3 text-left transition ${
                      selectedId === conversation.id
                        ? "bg-green-50/60"
                        : "hover:bg-stone-50"
                    }`}
                  >
                    <div className="flex items-start justify-between gap-3">
                      <p className="truncate text-sm font-medium text-stone-900">
                        {conversation.title?.trim() || "Untitled conversation"}
                      </p>
                      <span className="shrink-0 text-[11px] text-stone-400">
                        {formatConversationTime(conversation.updated_at)}
                      </span>
                    </div>
                    <p className="mt-1 truncate text-xs text-stone-500">
                      {conversation.customer_name} ·{" "}
                      {conversation.customer_email}
                    </p>
                    <p className="mt-1 text-[11px] text-stone-400">
                      {conversation.message_count} message
                      {conversation.message_count === 1 ? "" : "s"}
                    </p>
                  </button>
                </li>
              ))}
            </ul>
          </div>

          <div className="rounded-lg border border-stone-200 bg-white">
            {visibleDetailError ? (
              <div className="p-4">
                <FeedbackBanner tone="error">
                  {visibleDetailError}
                </FeedbackBanner>
              </div>
            ) : isLoadingDetail ? (
              <p className="p-5 text-sm text-stone-500">
                Loading messages…
              </p>
            ) : visibleDetail ? (
              <>
                <div className="border-b border-stone-200 px-5 py-4">
                  <h2 className="text-base font-semibold tracking-tight text-stone-950">
                    {visibleDetail.title?.trim() || "Untitled conversation"}
                  </h2>
                  <p className="mt-1 text-sm text-stone-500">
                    {visibleDetail.customer_name} ·{" "}
                    {visibleDetail.customer_email}
                  </p>
                  <p className="mt-1 text-xs text-stone-400">
                    Started{" "}
                    {formatConversationTime(visibleDetail.created_at)} ·{" "}
                    {visibleDetail.message_count} message
                    {visibleDetail.message_count === 1 ? "" : "s"}
                  </p>
                </div>
                <div className="max-h-[60vh] space-y-4 overflow-y-auto px-5 py-4">
                  {visibleDetail.messages.length === 0 ? (
                    <p className="text-sm text-stone-500">
                      This conversation has no messages.
                    </p>
                  ) : (
                    visibleDetail.messages.map((message) => (
                      <article
                        key={message.id}
                        className="rounded-md border border-stone-200 p-3"
                      >
                        <div className="flex flex-wrap items-center justify-between gap-2">
                          <StatusPill
                            value={ROLE_TONES[message.role] || "stone"}
                            label={message.role}
                          />
                          <span className="text-[11px] text-stone-400">
                            {formatConversationTime(message.created_at)}
                          </span>
                        </div>
                        <p className="mt-2 whitespace-pre-wrap text-sm leading-6 text-stone-700">
                          {message.content}
                        </p>
                        {message.metadata ? (
                          <details className="mt-2">
                            <summary className="cursor-pointer text-xs font-medium text-stone-500 hover:text-stone-800">
                              Metadata
                            </summary>
                            <pre className="mt-2 overflow-x-auto rounded-md bg-stone-950 p-3 text-[11px] leading-5 text-stone-100">
                              {JSON.stringify(message.metadata, null, 2)}
                            </pre>
                          </details>
                        ) : null}
                      </article>
                    ))
                  )}
                </div>
              </>
            ) : (
              <p className="p-5 text-sm text-stone-500">
                Select a conversation to inspect its messages.
              </p>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

export default AdminConversations;
