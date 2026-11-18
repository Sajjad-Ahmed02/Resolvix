const LAST_CONVERSATION_KEY = "resolvix.chat.lastConversation";

// The API client dispatches this when a silent refresh fails and the session
// cannot be recovered. Access and refresh tokens live in HttpOnly cookies and
// are never readable by JavaScript.
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

export function readLastConversationId() {
  return readJson(LAST_CONVERSATION_KEY);
}

export function writeLastConversationId(conversationId) {
  writeJson(LAST_CONVERSATION_KEY, conversationId);
}

export function clearLastConversationId() {
  removeKey(LAST_CONVERSATION_KEY);
}
