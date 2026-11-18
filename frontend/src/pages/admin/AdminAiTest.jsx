import { useRef, useState } from "react";

import {
  FeedbackBanner,
  PageHeader,
  primaryButtonClass,
  secondaryButtonClass,
  StatusPill,
} from "../../components/admin/AdminUi";
import { SparkIcon } from "../../components/icons";
import { useAuth } from "../../context/useAuth";
import * as adminService from "../../services/adminService";
import { formatMessageTime } from "../../utils/date";
import { getAdminErrorMessage } from "../../utils/adminError";

const QUICK_PROMPTS = [
  "What is the return window?",
  "Where is my order RX-2026-00000001?",
  "What are your shipping options?",
];

function MetadataBlock({ metadata }) {
  if (!metadata) {
    return null;
  }

  const sources = Array.isArray(metadata.sources) ? metadata.sources : [];
  const capabilities = Array.isArray(metadata.capabilities)
    ? metadata.capabilities
    : [];
  const toolCalls = Array.isArray(metadata.tool_calls)
    ? metadata.tool_calls
    : [];

  return (
    <div className="mt-3 space-y-3 border-t border-stone-200 pt-3">
      <div className="flex flex-wrap gap-1.5">
        {metadata.intent ? (
          <StatusPill value="active" label={`intent: ${metadata.intent}`} />
        ) : null}
        {metadata.source ? (
          <StatusPill value="refreshed" label={`source: ${metadata.source}`} />
        ) : null}
        {metadata.fallback ? (
          <StatusPill value="failed" label="fallback" />
        ) : null}
        {capabilities.map((capability) => (
          <StatusPill
            key={capability}
            value="violet"
            label={capability.replaceAll("_", " ")}
          />
        ))}
      </div>

      {sources.length > 0 ? (
        <div>
          <p className="text-[11px] font-medium uppercase tracking-wide text-stone-500">
            Retrieved sources
          </p>
          <ul className="mt-1 space-y-1">
            {sources.map((source, index) => (
              <li
                key={`${source.source_id}-${index}`}
                className="rounded-md bg-stone-50 px-2.5 py-1.5 text-xs text-stone-600"
              >
                <span className="font-medium capitalize text-stone-800">
                  {source.source_type}
                </span>{" "}
                · {source.title}
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      {toolCalls.length > 0 ? (
        <div>
          <p className="text-[11px] font-medium uppercase tracking-wide text-stone-500">
            Tool calls
          </p>
          <ul className="mt-1 space-y-1">
            {toolCalls.map((call, index) => (
              <li
                key={`${call.name}-${index}`}
                className="rounded-md bg-stone-50 px-2.5 py-1.5 font-mono text-[11px] text-stone-600"
              >
                {call.name} · {call.status}
                {call.error ? ` · ${call.error}` : ""}
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      <details>
        <summary className="cursor-pointer text-[11px] font-medium uppercase tracking-wide text-stone-500 hover:text-stone-800">
          Raw metadata
        </summary>
        <pre className="mt-2 max-h-64 overflow-auto rounded-md bg-stone-950 p-3 text-[11px] leading-5 text-stone-100">
          {JSON.stringify(metadata, null, 2)}
        </pre>
      </details>
    </div>
  );
}

function AdminAiTest() {
  const { user } = useAuth();
  const [message, setMessage] = useState("");
  const [turns, setTurns] = useState([]);
  const [conversationId, setConversationId] = useState(null);
  const [isSending, setIsSending] = useState(false);
  const [error, setError] = useState("");
  const bottomRef = useRef(null);

  const send = async (event) => {
    event.preventDefault();
    const content = message.trim();
    if (!content || isSending) {
      return;
    }

    setError("");
    setIsSending(true);

    try {
      const response = await adminService.testAgent({
        message: content,
        conversation_id: conversationId,
      });
      setConversationId(response.conversation.id);
      setTurns((current) => [
        ...current,
        {
          id: response.assistant_message.id,
          question: content,
          response,
        },
      ]);
      setMessage("");
      requestAnimationFrame(() => {
        bottomRef.current?.scrollIntoView({ block: "end" });
      });
    } catch (requestError) {
      setError(
        getAdminErrorMessage(
          requestError,
          "The agent could not answer this test question.",
        ),
      );
    } finally {
      setIsSending(false);
    }
  };

  const resetConversation = () => {
    setTurns([]);
    setConversationId(null);
    setError("");
    setMessage("");
  };

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="Agent diagnostics"
        title="AI response testing"
        description="Send questions through the production orchestrator and inspect the intent, retrieved sources, tool calls, and raw metadata."
        actions={
          <button
            type="button"
            onClick={resetConversation}
            className={secondaryButtonClass}
          >
            New test conversation
          </button>
        }
      />

      {error ? <FeedbackBanner tone="error">{error}</FeedbackBanner> : null}

      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_18rem]">
        <section className="flex min-h-[28rem] flex-col rounded-lg border border-stone-200 bg-white">
          <div className="flex items-center justify-between border-b border-stone-200 px-5 py-3.5">
            <div>
              <h2 className="text-sm font-semibold text-stone-900">
                Test transcript
              </h2>
              <p className="mt-0.5 text-xs text-stone-500">
                {conversationId
                  ? `Conversation ${conversationId.slice(0, 8)}…`
                  : "A conversation starts with your first question."}
              </p>
            </div>
            <span className="text-xs text-stone-400">{user?.name}</span>
          </div>

          <div className="flex-1 space-y-5 overflow-y-auto px-4 py-4">
            {turns.length === 0 ? (
              <div className="flex h-full min-h-64 flex-col items-center justify-center text-center">
                <SparkIcon className="h-8 w-8 text-stone-300" />
                <p className="mt-3 text-sm font-medium text-stone-700">
                  Ask the agent a test question
                </p>
                <p className="mt-1 max-w-sm text-sm leading-6 text-stone-500">
                  Responses are generated by the same orchestrator customers
                  use, including retrieval and order tools.
                </p>
              </div>
            ) : (
              turns.map((turn) => (
                <div key={turn.id} className="space-y-3">
                  <div className="flex justify-end">
                    <p className="max-w-[85%] rounded-lg rounded-br-sm bg-stone-950 px-3.5 py-2.5 text-sm leading-6 text-white">
                      {turn.question}
                    </p>
                  </div>
                  <div className="max-w-[95%] rounded-lg rounded-bl-sm border border-stone-200 bg-stone-50 px-3.5 py-3">
                    <div className="flex items-center justify-between gap-3">
                      <span className="text-[11px] font-medium uppercase tracking-wide text-green-800">
                        Assistant
                      </span>
                      <span className="text-[11px] text-stone-400">
                        {formatMessageTime(
                          turn.response.assistant_message.created_at,
                        )}{" "}
                        · {turn.response.latency_ms} ms
                      </span>
                    </div>
                    <p className="mt-1.5 whitespace-pre-wrap text-sm leading-6 text-stone-800">
                      {turn.response.assistant_message.content}
                    </p>
                    <MetadataBlock
                      metadata={turn.response.assistant_message.metadata}
                    />
                  </div>
                </div>
              ))
            )}
            <div ref={bottomRef} />
          </div>

          <form
            onSubmit={send}
            className="border-t border-stone-200 p-3"
          >
            <div className="flex items-end gap-2">
              <textarea
                value={message}
                onChange={(event) => setMessage(event.target.value)}
                onKeyDown={(event) => {
                  if (
                    event.key === "Enter" &&
                    !event.shiftKey &&
                    !event.nativeEvent.isComposing
                  ) {
                    event.preventDefault();
                    send(event);
                  }
                }}
                rows={2}
                maxLength={8000}
                placeholder="Ask a test question…"
                aria-label="Test question"
                className="min-h-[3rem] flex-1 resize-y rounded-md border border-stone-300 bg-white px-3 py-2 text-sm text-stone-900 outline-none transition placeholder:text-stone-400 focus:border-green-800 focus:ring-2 focus:ring-green-800/10"
              />
              <button
                type="submit"
                disabled={isSending || !message.trim()}
                className={primaryButtonClass}
              >
                {isSending ? "Thinking…" : "Send"}
              </button>
            </div>
          </form>
        </section>

        <aside className="space-y-4">
          <section className="rounded-lg border border-stone-200 bg-white p-4">
            <h2 className="text-sm font-semibold text-stone-900">
              Suggested prompts
            </h2>
            <div className="mt-3 space-y-2">
              {QUICK_PROMPTS.map((prompt) => (
                <button
                  key={prompt}
                  type="button"
                  onClick={() => setMessage(prompt)}
                  className="w-full rounded-md border border-stone-200 px-3 py-2 text-left text-xs leading-5 text-stone-600 transition hover:border-stone-300 hover:bg-stone-50"
                >
                  {prompt}
                </button>
              ))}
            </div>
          </section>

          <section className="rounded-lg border border-stone-200 bg-white p-4 text-xs leading-5 text-stone-500">
            <h2 className="text-sm font-semibold text-stone-900">
              How this works
            </h2>
            <p className="mt-2">
              Each question is persisted to an administrator-owned
              conversation. Follow-up questions reuse that conversation so
              multi-turn context behaves like customer chat.
            </p>
          </section>
        </aside>
      </div>
    </div>
  );
}

export default AdminAiTest;
