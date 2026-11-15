import { useCallback, useEffect, useRef, useState } from "react";

import ConversationSidebar from "../components/ConversationSidebar";
import MessageBubble from "../components/MessageBubble";
import {
  AlertIcon,
  ArrowUpIcon,
  BrandMark,
  ChatIcon,
  CloseIcon,
  MenuIcon,
  PlusIcon,
} from "../components/icons";
import { useAuth } from "../context/useAuth";
import * as conversationService from "../services/conversationService";
import { getErrorMessage } from "../utils/apiError";
import {
  clearLastConversationId,
  readLastConversationId,
  writeLastConversationId,
} from "../utils/authStorage";

function conversationLabel(conversation) {
  return conversation?.title?.trim() || "New conversation";
}

function sortByUpdatedAt(items) {
  return [...items].sort(
    (left, right) =>
      new Date(right.updated_at).getTime() -
      new Date(left.updated_at).getTime(),
  );
}

function Chat() {
  const { user, signOut, notice, clearNotice } = useAuth();

  const [conversations, setConversations] = useState([]);
  const [selectedId, setSelectedId] = useState(null);
  const [messages, setMessages] = useState([]);
  const [draft, setDraft] = useState("");
  const [error, setError] = useState("");
  const [isLoadingConversations, setIsLoadingConversations] = useState(true);
  const [isLoadingMessages, setIsLoadingMessages] = useState(false);
  const [isCreating, setIsCreating] = useState(false);
  const [isSending, setIsSending] = useState(false);
  const [isSidebarOpen, setIsSidebarOpen] = useState(false);

  const messagesEndRef = useRef(null);
  const inputRef = useRef(null);
  const requestIdRef = useRef(0);
  const sendingRef = useRef(false);
  const creatingRef = useRef(false);
  const selectedIdRef = useRef(null);

  const selectedConversation =
    conversations.find((conversation) => conversation.id === selectedId) ??
    null;
  const visibleError = error || notice;

  useEffect(() => {
    selectedIdRef.current = selectedId;
  }, [selectedId]);

  const loadConversation = useCallback(async (conversationId) => {
    const requestId = requestIdRef.current + 1;
    requestIdRef.current = requestId;

    setSelectedId(conversationId);
    writeLastConversationId(conversationId);
    setMessages([]);
    setError("");
    setIsLoadingMessages(true);

    try {
      const history =
        await conversationService.listMessages(conversationId);
      if (requestIdRef.current === requestId) {
        setMessages(history);
      }
    } catch (requestError) {
      if (requestIdRef.current !== requestId) {
        return;
      }
      setError(
        getErrorMessage(
          requestError,
          "Could not load this conversation. Try selecting it again.",
        ),
      );
      if (requestError?.response?.status === 404) {
        setSelectedId(null);
        setMessages([]);
        clearLastConversationId();
      }
    } finally {
      if (requestIdRef.current === requestId) {
        setIsLoadingMessages(false);
      }
    }
  }, []);

  useEffect(() => {
    let cancelled = false;

    const load = async () => {
      try {
        const data = await conversationService.listConversations();
        if (cancelled) {
          return;
        }

        setConversations(data);
        setIsLoadingConversations(false);

        const savedId = readLastConversationId();
        const nextId = data.some(
          (conversation) => conversation.id === savedId,
        )
          ? savedId
          : data[0]?.id;

        if (nextId) {
          await loadConversation(nextId);
        } else {
          setSelectedId(null);
          setMessages([]);
          clearLastConversationId();
        }
      } catch (requestError) {
        if (cancelled) {
          return;
        }
        setError(
          getErrorMessage(
            requestError,
            "Could not load your conversations. Please refresh the page.",
          ),
        );
        setIsLoadingConversations(false);
      }
    };

    load();

    return () => {
      cancelled = true;
      requestIdRef.current += 1;
    };
  }, [loadConversation]);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({
      behavior: "smooth",
      block: "end",
    });
  }, [messages, isSending, isLoadingMessages]);

  const dismissError = () => {
    setError("");
    clearNotice();
  };

  const handleSelect = (conversationId) => {
    setIsSidebarOpen(false);
    if (sendingRef.current || conversationId === selectedId) {
      return;
    }
    loadConversation(conversationId);
  };

  const handleCreate = async () => {
    if (
      creatingRef.current ||
      sendingRef.current ||
      isLoadingConversations
    ) {
      return;
    }

    creatingRef.current = true;
    setIsCreating(true);
    setError("");
    clearNotice();

    try {
      const conversation = await conversationService.createConversation();
      requestIdRef.current += 1;
      setConversations((current) =>
        sortByUpdatedAt([conversation, ...current]),
      );
      setSelectedId(conversation.id);
      writeLastConversationId(conversation.id);
      setMessages([]);
      setDraft("");
      setIsLoadingMessages(false);
      setIsSidebarOpen(false);
      inputRef.current?.focus();
    } catch (requestError) {
      setError(
        getErrorMessage(
          requestError,
          "Could not start a new conversation. Please try again.",
        ),
      );
    } finally {
      creatingRef.current = false;
      setIsCreating(false);
    }
  };

  const handleSend = async (event) => {
    event.preventDefault();
    if (sendingRef.current) {
      return;
    }

    const content = draft.trim();
    if (!selectedId) {
      setError("Start or select a conversation before sending a message.");
      return;
    }
    if (!content) {
      setError("Write a message before sending.");
      return;
    }
    if (content.length > 8000) {
      setError("Messages cannot be longer than 8,000 characters.");
      return;
    }

    const conversationId = selectedId;
    sendingRef.current = true;
    setIsSending(true);
    setError("");
    clearNotice();

    try {
      const exchange = await conversationService.sendMessage(
        conversationId,
        content,
      );

      setConversations((current) =>
        sortByUpdatedAt([
          exchange.conversation,
          ...current.filter(
            (conversation) => conversation.id !== exchange.conversation.id,
          ),
        ]),
      );

      if (selectedIdRef.current === conversationId) {
        setMessages((current) => [
          ...current,
          exchange.user_message,
          exchange.assistant_message,
        ]);
        setDraft("");
      }
    } catch (requestError) {
      setError(
        getErrorMessage(
          requestError,
          "Your message could not be sent. Please try again.",
        ),
      );
    } finally {
      sendingRef.current = false;
      setIsSending(false);
    }
  };

  const handleComposerKeyDown = (event) => {
    if (
      event.key === "Enter" &&
      !event.shiftKey &&
      !event.nativeEvent.isComposing
    ) {
      event.preventDefault();
      if (!sendingRef.current && draft.trim() && selectedId) {
        event.currentTarget.form?.requestSubmit();
      }
    }
  };

  const composerDisabled =
    !selectedId || isLoadingMessages || isSending;

  return (
    <div className="flex h-dvh overflow-hidden bg-white">
      <ConversationSidebar
        conversations={conversations}
        selectedId={selectedId}
        onSelect={handleSelect}
        onCreate={handleCreate}
        onLogout={signOut}
        isCreating={isCreating}
        isLoading={isLoadingConversations}
        isBusy={isSending}
        isOpen={isSidebarOpen}
        onClose={() => setIsSidebarOpen(false)}
        user={user}
      />

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex items-center gap-3 border-b border-stone-200 bg-white px-4 py-3.5 sm:px-6">
          <button
            type="button"
            onClick={() => setIsSidebarOpen(true)}
            className="rounded-md border border-stone-300 p-2 text-stone-600 transition hover:bg-stone-100 hover:text-stone-900 focus:outline-none focus-visible:ring-2 focus-visible:ring-green-800/30 md:hidden"
            aria-label="Open conversation sidebar"
          >
            <MenuIcon className="h-4 w-4" />
          </button>

          <div className="min-w-0">
            <h1 className="truncate text-[15px] font-semibold tracking-tight text-stone-950">
              {selectedConversation
                ? conversationLabel(selectedConversation)
                : "Customer chat"}
            </h1>
            <p className="truncate text-xs text-stone-500">
              {selectedConversation
                ? "Messages are saved to your account"
                : "Select a conversation or start a new one"}
            </p>
          </div>
        </header>

        {visibleError ? (
          <div className="border-b border-red-200 bg-red-50">
            <div className="mx-auto flex w-full max-w-3xl items-start gap-2.5 px-4 py-2.5 text-sm text-red-800 sm:px-6">
              <AlertIcon className="mt-0.5 h-4 w-4 shrink-0 text-red-600" />
              <p className="flex-1 leading-5" role="alert">
                {visibleError}
              </p>
              <button
                type="button"
                onClick={dismissError}
                className="rounded p-0.5 text-red-500 transition hover:bg-red-100 hover:text-red-800 focus:outline-none focus-visible:ring-2 focus-visible:ring-red-400"
                aria-label="Dismiss error"
              >
                <CloseIcon className="h-3.5 w-3.5" />
              </button>
            </div>
          </div>
        ) : null}

        <main className="flex-1 overflow-y-auto bg-stone-50">
          <div className="mx-auto flex min-h-full w-full max-w-3xl flex-col px-4 py-6 sm:px-6 sm:py-8">
            {isLoadingMessages ? (
              <div
                className="flex flex-1 flex-col items-center justify-center gap-4 py-16"
                role="status"
              >
                <span
                  className="h-6 w-6 animate-spin rounded-full border-2 border-stone-200 border-t-green-800"
                  aria-hidden="true"
                />
                <p className="text-sm text-stone-500">Loading messages…</p>
              </div>
            ) : !selectedConversation ? (
              <div className="flex flex-1 flex-col items-center justify-center py-16 text-center">
                <div className="flex h-12 w-12 items-center justify-center rounded-md border border-stone-200 bg-white text-stone-500">
                  <ChatIcon className="h-5 w-5" />
                </div>
                <h2 className="mt-5 text-xl font-semibold tracking-tight text-stone-950">
                  Start a conversation
                </h2>
                <p className="mt-2 max-w-sm text-sm leading-6 text-stone-500">
                  Create a conversation to send a message. Your history is
                  saved to your account.
                </p>
                <button
                  type="button"
                  onClick={handleCreate}
                  disabled={isCreating || isLoadingConversations}
                  className="mt-6 inline-flex items-center gap-2 rounded-md bg-stone-950 px-4 py-2.5 text-sm font-medium text-white transition hover:bg-stone-800 focus:outline-none focus-visible:ring-2 focus-visible:ring-stone-900 focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-60"
                >
                  {isCreating ? (
                    <span
                      className="h-4 w-4 animate-spin rounded-full border-2 border-white/30 border-t-white"
                      aria-hidden="true"
                    />
                  ) : (
                    <PlusIcon className="h-4 w-4" />
                  )}
                  {isCreating ? "Creating…" : "Start your first conversation"}
                </button>
              </div>
            ) : messages.length === 0 && !isSending ? (
              <div className="flex flex-1 flex-col items-center justify-center py-16 text-center">
                <div className="flex h-12 w-12 items-center justify-center rounded-md border border-stone-200 bg-white text-stone-500">
                  <ChatIcon className="h-5 w-5" />
                </div>
                <h2 className="mt-5 text-lg font-semibold tracking-tight text-stone-950">
                  No messages yet
                </h2>
                <p className="mt-2 max-w-sm text-sm leading-6 text-stone-500">
                  Send the first message below. The conversation title will be
                  taken from it.
                </p>
              </div>
            ) : (
              <div
                className="flex-1 space-y-6"
                role="log"
                aria-live="polite"
                aria-relevant="additions"
              >
                {messages.map((message) => (
                  <MessageBubble key={message.id} message={message} />
                ))}

                {isSending ? (
                  <div className="flex gap-2.5">
                    <BrandMark className="mt-5 h-7 w-7 shrink-0 text-[10px]" />
                    <div>
                      <p className="mb-1 text-[11px] font-medium text-stone-500">
                        Resolvix Support
                      </p>
                      <div
                        className="flex h-9 items-center gap-1 rounded-md rounded-bl-sm bg-white px-3 ring-1 ring-inset ring-stone-200"
                        role="status"
                        aria-label="Resolvix is preparing a reply"
                      >
                        <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-stone-400" />
                        <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-stone-400 [animation-delay:120ms]" />
                        <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-stone-400 [animation-delay:240ms]" />
                      </div>
                    </div>
                  </div>
                ) : null}
              </div>
            )}

            <div ref={messagesEndRef} />
          </div>
        </main>

        <div className="border-t border-stone-200 bg-white px-4 py-4 sm:px-6">
          <form
            className="mx-auto w-full max-w-3xl"
            onSubmit={handleSend}
          >
            <label htmlFor="message-input" className="sr-only">
              Message
            </label>
            <div className="flex items-end gap-2 rounded-md border border-stone-300 bg-white p-1.5 transition focus-within:border-green-800 focus-within:ring-2 focus-within:ring-green-800/10">
              <textarea
                id="message-input"
                ref={inputRef}
                rows={1}
                maxLength={8000}
                value={draft}
                onChange={(event) => setDraft(event.target.value)}
                onKeyDown={handleComposerKeyDown}
                disabled={composerDisabled}
                placeholder={
                  selectedId
                    ? "Write a message…"
                    : "Start a conversation to write a message"
                }
                aria-describedby="composer-hint"
                className="max-h-40 min-h-10 flex-1 resize-none bg-transparent px-2 py-2 text-sm leading-6 text-stone-800 outline-none placeholder:text-stone-400 disabled:cursor-not-allowed disabled:text-stone-400"
              />
              <button
                type="submit"
                disabled={composerDisabled || !draft.trim()}
                aria-label={isSending ? "Sending message" : "Send message"}
                className={`flex h-9 w-9 shrink-0 items-center justify-center rounded text-white transition focus:outline-none focus-visible:ring-2 focus-visible:ring-stone-900 focus-visible:ring-offset-2 disabled:cursor-not-allowed ${
                  isSending
                    ? "bg-stone-800"
                    : "bg-stone-950 hover:bg-stone-800 disabled:bg-stone-200 disabled:text-stone-400"
                }`}
              >
                {isSending ? (
                  <span
                    className="h-4 w-4 animate-spin rounded-full border-2 border-white/30 border-t-white"
                    aria-hidden="true"
                  />
                ) : (
                  <ArrowUpIcon className="h-4 w-4" />
                )}
              </button>
            </div>
            <div
              id="composer-hint"
              className="mt-2 flex items-center justify-between text-[11px] text-stone-500"
            >
              <span>Enter to send · Shift + Enter for a new line</span>
              {draft.length > 7000 ? (
                <span>{draft.length.toLocaleString()} / 8,000</span>
              ) : null}
            </div>
          </form>
        </div>
      </div>
    </div>
  );
}

export default Chat;
