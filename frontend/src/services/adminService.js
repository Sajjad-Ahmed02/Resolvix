import api from "./api";

// Dashboard
export async function getStats() {
  const { data } = await api.get("/admin/stats");
  return data;
}

export async function listUsers() {
  const { data } = await api.get("/admin/users");
  return data;
}

// FAQs
export async function listFaqs() {
  const { data } = await api.get("/admin/knowledge/faqs");
  return data;
}

export async function createFaq(payload) {
  const { data } = await api.post("/admin/knowledge/faqs", payload);
  return data;
}

export async function updateFaq(id, payload) {
  const { data } = await api.put(`/admin/knowledge/faqs/${id}`, payload);
  return data;
}

export async function deleteFaq(id) {
  await api.delete(`/admin/knowledge/faqs/${id}`);
}

export async function reindexFaq(id) {
  const { data } = await api.post(`/admin/knowledge/faqs/${id}/reindex`);
  return data;
}

// Knowledge documents
export async function listDocuments() {
  const { data } = await api.get("/admin/knowledge/documents");
  return data;
}

export async function createDocument(payload) {
  const { data } = await api.post("/admin/knowledge/documents", payload);
  return data;
}

export async function updateDocument(id, payload) {
  const { data } = await api.put(
    `/admin/knowledge/documents/${id}`,
    payload,
  );
  return data;
}

export async function deleteDocument(id) {
  await api.delete(`/admin/knowledge/documents/${id}`);
}

export async function reindexDocument(id) {
  const { data } = await api.post(
    `/admin/knowledge/documents/${id}/reindex`,
  );
  return data;
}

export async function reindexAll() {
  const { data } = await api.post("/admin/knowledge/reindex");
  return data;
}

// Orders
export async function listOrders() {
  const { data } = await api.get("/admin/orders");
  return data;
}

export async function createOrder(payload) {
  const { data } = await api.post("/admin/orders", payload);
  return data;
}

export async function updateOrder(id, payload) {
  const { data } = await api.patch(`/admin/orders/${id}`, payload);
  return data;
}

export async function addOrderItem(orderId, payload) {
  const { data } = await api.post(
    `/admin/orders/${orderId}/items`,
    payload,
  );
  return data;
}

export async function updateOrderItem(orderId, itemId, payload) {
  const { data } = await api.patch(
    `/admin/orders/${orderId}/items/${itemId}`,
    payload,
  );
  return data;
}

export async function deleteOrderItem(orderId, itemId) {
  const { data } = await api.delete(
    `/admin/orders/${orderId}/items/${itemId}`,
  );
  return data;
}

// Conversations
export async function listConversations() {
  const { data } = await api.get("/admin/conversations");
  return data;
}

export async function getConversation(id) {
  const { data } = await api.get(`/admin/conversations/${id}`);
  return data;
}

// AI testing
export async function testAgent(payload) {
  const { data } = await api.post("/admin/ai/test", payload);
  return data;
}
