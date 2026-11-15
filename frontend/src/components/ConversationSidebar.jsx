import {
  BrandMark,
  ChatIcon,
  CloseIcon,
  LogoutIcon,
  PlusIcon,
} from "./icons";
import { formatConversationTime } from "../utils/date";

function getInitials(name) {
  const parts = String(name || "")
    .trim()
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2);
  return parts.map((part) => part[0].toUpperCase()).join("") || "R";
}

function conversationLabel(conversation) {
  return conversation.title?.trim() || "New conversation";
}

function ConversationSidebar({
  conversations,
  selectedId,
  onSelect,
  onCreate,
  onLogout,
  isCreating,
  isLoading,
  isBusy,
  isOpen,
  onClose,
  user,
}) {
  return (
    <>
      {isOpen ? (
        <button
          type="button"
          className="fixed inset-0 z-30 bg-stone-950/40 md:hidden"
          onClick={onClose}
          aria-label="Close conversation sidebar"
        />
      ) : null}

      <aside
        className={`fixed inset-y-0 left-0 z-40 flex w-72 shrink-0 transform flex-col border-r border-stone-200 bg-stone-100 transition-transform duration-200 md:static md:w-72 md:translate-x-0 lg:w-80 ${
          isOpen ? "translate-x-0" : "-translate-x-full"
        }`}
        aria-label="Conversations"
      >
        <div className="flex items-center justify-between px-4 py-4">
          <div className="flex items-center gap-2.5">
            <BrandMark className="h-8 w-8 text-sm" />
            <div>
              <p className="text-sm font-semibold tracking-tight text-stone-950">
                Resolvix
              </p>
              <p className="text-[11px] text-stone-500">Customer support</p>
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded-md p-1.5 text-stone-500 transition hover:bg-stone-200 hover:text-stone-900 md:hidden"
            aria-label="Close sidebar"
          >
            <CloseIcon className="h-4 w-4" />
          </button>
        </div>

        <div className="px-4 pb-1">
          <button
            type="button"
            onClick={onCreate}
            disabled={isCreating || isLoading || isBusy}
            className="flex w-full items-center justify-center gap-2 rounded-md bg-stone-950 px-3 py-2.5 text-sm font-medium text-white transition hover:bg-stone-800 focus:outline-none focus-visible:ring-2 focus-visible:ring-stone-900 focus-visible:ring-offset-2 focus-visible:ring-offset-stone-100 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {isCreating ? (
              <span
                className="h-4 w-4 animate-spin rounded-full border-2 border-white/30 border-t-white"
                aria-hidden="true"
              />
            ) : (
              <PlusIcon className="h-4 w-4" />
            )}
            {isCreating ? "Creating…" : "New conversation"}
          </button>
        </div>

        <div className="mt-5 flex items-baseline justify-between px-4">
          <p className="text-xs font-medium text-stone-600">Conversations</p>
          {!isLoading ? (
            <span className="text-xs text-stone-500">
              {conversations.length}
            </span>
          ) : null}
        </div>

        <div className="mt-2 flex-1 overflow-y-auto px-2 pb-3">
          {isLoading ? (
            <div className="space-y-1.5" aria-busy="true">
              <span className="sr-only">Loading conversations…</span>
              {[0, 1, 2, 3].map((item) => (
                <div
                  key={item}
                  className="animate-pulse rounded-md bg-stone-200/60 px-2.5 py-3"
                >
                  <div className="h-3 w-3/4 rounded bg-stone-300/70" />
                  <div className="mt-2 h-2.5 w-1/3 rounded bg-stone-300/50" />
                </div>
              ))}
            </div>
          ) : conversations.length === 0 ? (
            <div className="mx-2 rounded-md border border-dashed border-stone-300 px-4 py-8 text-center">
              <ChatIcon className="mx-auto h-5 w-5 text-stone-400" />
              <p className="mt-3 text-sm font-medium text-stone-700">
                No conversations yet
              </p>
              <p className="mt-1 text-xs leading-5 text-stone-500">
                Start a new chat and it will appear here.
              </p>
            </div>
          ) : (
            <ul className="space-y-0.5">
              {conversations.map((conversation) => {
                const isActive = conversation.id === selectedId;
                return (
                  <li key={conversation.id}>
                    <button
                      type="button"
                      onClick={() => onSelect(conversation.id)}
                      disabled={isBusy}
                      aria-current={isActive ? "true" : undefined}
                      className={`group flex w-full items-start gap-2.5 rounded-md px-2.5 py-2.5 text-left transition focus:outline-none focus-visible:ring-2 focus-visible:ring-green-800/30 disabled:cursor-not-allowed disabled:opacity-60 ${
                        isActive
                          ? "bg-white text-stone-950 ring-1 ring-inset ring-stone-200"
                          : "text-stone-700 hover:bg-stone-200/60"
                      }`}
                    >
                      <ChatIcon
                        className={`mt-0.5 h-4 w-4 shrink-0 ${
                          isActive
                            ? "text-green-800"
                            : "text-stone-400 group-hover:text-stone-500"
                        }`}
                      />
                      <span className="min-w-0 flex-1">
                        <span className="block truncate text-sm font-medium leading-5">
                          {conversationLabel(conversation)}
                        </span>
                        <span className="mt-0.5 block text-[11px] text-stone-500">
                          {formatConversationTime(conversation.updated_at)}
                        </span>
                      </span>
                    </button>
                  </li>
                );
              })}
            </ul>
          )}
        </div>

        <div className="border-t border-stone-200 p-3">
          <div className="flex items-center gap-2.5 px-1 py-1">
            <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md bg-stone-200 text-[11px] font-semibold text-stone-700">
              {getInitials(user?.name)}
            </span>
            <div className="min-w-0 flex-1">
              <p className="truncate text-sm font-medium text-stone-800">
                {user?.name || "Customer"}
              </p>
              <p className="truncate text-[11px] text-stone-500">
                {user?.email}
              </p>
            </div>
            <button
              type="button"
              onClick={onLogout}
              className="rounded-md p-1.5 text-stone-500 transition hover:bg-stone-200 hover:text-red-700 focus:outline-none focus-visible:ring-2 focus-visible:ring-green-800/30"
              aria-label="Sign out"
              title="Sign out"
            >
              <LogoutIcon className="h-4 w-4" />
            </button>
          </div>
        </div>
      </aside>
    </>
  );
}

export default ConversationSidebar;
