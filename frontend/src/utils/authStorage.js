const SESSION_STORAGE_KEY = "resolvix.auth.session";
const LAST_CONVERSATION_KEY = "resolvix.chat.lastConversation";

export const SESSION_EXPIRED_EVENT = "resolvix:session-expired";

function readJson(key) {
  try {
    const raw = window.localStorage.getItem(key);
    return raw ? JSON.parse(raw) : null;
  } catch {
    return null;
  }
}

function writeJson(key, value) {
  try {
    window.localStorage.setItem(key, JSON.stringify(value));
  } catch {
    // Storage can be unavailable in private browsing; the in-memory session
    // still works for the current tab.
  }
}

function removeKey(key) {
  try {
    window.localStorage.removeItem(key);
  } catch {
    // Ignore storage failures.
  }
}

export function readStoredSession() {
  const session = readJson(SESSION_STORAGE_KEY);
  if (
    !session?.accessToken ||
    !session?.user ||
    typeof session.expiresAt !== "number"
  ) {
    if (session) {
      removeKey(SESSION_STORAGE_KEY);
    }
    return null;
  }

  if (session.expiresAt <= Date.now()) {
    removeKey(SESSION_STORAGE_KEY);
    return null;
  }

  return session;
}

export function writeStoredSession(session) {
  writeJson(SESSION_STORAGE_KEY, session);
}

export function clearStoredSession() {
  removeKey(SESSION_STORAGE_KEY);
}

export function readLastConversationId() {
  return readJson(LAST_CONVERSATION_KEY);
}

export function writeLastConversationId(conversationId) {
  writeJson(LAST_CONVERSATION_KEY, conversationId);
}

export function clearLastConversationId() {
  removeKey(LAST_CONVERSATION_KEY);
}
