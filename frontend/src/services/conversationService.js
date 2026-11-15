import api from "./api";

export async function listConversations() {
  const { data } = await api.get("/conversations");
  return data;
}

export async function createConversation(title) {
  const payload = title ? { title } : {};
  const { data } = await api.post("/conversations", payload);
  return data;
}

export async function getConversation(conversationId) {
  const { data } = await api.get(
    `/conversations/${encodeURIComponent(conversationId)}`,
  );
  return data;
}

export async function listMessages(conversationId) {
  const { data } = await api.get(
    `/conversations/${encodeURIComponent(conversationId)}/messages`,
  );
  return data;
}

export async function sendMessage(conversationId, content) {
  const { data } = await api.post(
    `/conversations/${encodeURIComponent(conversationId)}/messages`,
    { content },
  );
  return data;
}
