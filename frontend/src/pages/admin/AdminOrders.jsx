import { useCallback, useEffect, useMemo, useState } from "react";

import {
  dangerButtonClass,
  EmptyState,
  FeedbackBanner,
  Field,
  inputClass,
  Modal,
  PageHeader,
  primaryButtonClass,
  secondaryButtonClass,
  StatusPill,
} from "../../components/admin/AdminUi";
import { PlusIcon } from "../../components/icons";
import * as adminService from "../../services/adminService";
import { getAdminErrorMessage } from "../../utils/adminError";

const ORDER_STATUSES = [
  "pending",
  "confirmed",
  "processing",
  "completed",
  "cancelled",
];

const SHIPPING_STATUSES = [
  "not_shipped",
  "in_transit",
  "out_for_delivery",
  "delivered",
];

const EMPTY_ITEM = {
  product_name: "",
  quantity: 1,
  unit_price: "",
};

function formatMoney(value) {
  const number = Number(value);
  return Number.isFinite(number)
    ? number.toLocaleString(undefined, {
        style: "currency",
        currency: "USD",
      })
    : "—";
}

function formatDate(value) {
  if (!value) {
    return "—";
  }
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? "—"
    : date.toLocaleDateString(undefined, {
        month: "short",
        day: "numeric",
        year: "numeric",
      });
}

function newOrderNumber() {
  const suffix = String(Math.floor(Math.random() * 100_000_000)).padStart(
    8,
    "0",
  );
  return `RX-2026-${suffix}`;
}

function CreateOrderModal({ users, onClose, onCreated }) {
  const [form, setForm] = useState({
    user_id: users.find((user) => user.role === "customer")?.id || "",
    order_number: newOrderNumber(),
    status: "pending",
    shipping_status: "not_shipped",
    estimated_delivery: "",
    items: [{ ...EMPTY_ITEM }],
  });
  const [error, setError] = useState("");
  const [isSaving, setIsSaving] = useState(false);

  const updateItem = (index, patch) => {
    setForm((current) => ({
      ...current,
      items: current.items.map((item, itemIndex) =>
        itemIndex === index ? { ...item, ...patch } : item,
      ),
    }));
  };

  const addItem = () => {
    setForm((current) => ({
      ...current,
      items: [...current.items, { ...EMPTY_ITEM }],
    }));
  };

  const removeItem = (index) => {
    setForm((current) => ({
      ...current,
      items: current.items.filter((_, itemIndex) => itemIndex !== index),
    }));
  };

  const handleSubmit = async (event) => {
    event.preventDefault();
    setError("");

    if (!form.user_id) {
      setError("Select a customer for the order.");
      return;
    }
    if (form.items.length === 0) {
      setError("Add at least one line item.");
      return;
    }

    setIsSaving(true);
    try {
      const order = await adminService.createOrder({
        user_id: form.user_id,
        order_number: form.order_number,
        status: form.status,
        shipping_status: form.shipping_status,
        estimated_delivery: form.estimated_delivery || null,
        items: form.items.map((item) => ({
          product_name: item.product_name,
          quantity: Number(item.quantity),
          unit_price: String(item.unit_price),
        })),
      });
      onCreated(order);
    } catch (requestError) {
      setError(
        getAdminErrorMessage(
          requestError,
          "Could not create the order.",
        ),
      );
    } finally {
      setIsSaving(false);
    }
  };

  return (
    <Modal
      title="New synthetic order"
      description="The order total is calculated from the line items."
      onClose={isSaving ? () => {} : onClose}
    >
      <form onSubmit={handleSubmit} className="space-y-4">
        {error ? <FeedbackBanner tone="error">{error}</FeedbackBanner> : null}

        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Customer">
            <select
              value={form.user_id}
              onChange={(event) =>
                setForm((current) => ({
                  ...current,
                  user_id: event.target.value,
                }))
              }
              required
              className={inputClass}
            >
              <option value="">Select a customer…</option>
              {users
                .filter((user) => user.role === "customer")
                .map((user) => (
                  <option key={user.id} value={user.id}>
                    {user.name} · {user.email}
                  </option>
                ))}
            </select>
          </Field>

          <Field label="Order number">
            <input
              value={form.order_number}
              onChange={(event) =>
                setForm((current) => ({
                  ...current,
                  order_number: event.target.value.toUpperCase(),
                }))
              }
              required
              minLength={3}
              maxLength={30}
              className={inputClass}
            />
          </Field>

          <Field label="Order status">
            <select
              value={form.status}
              onChange={(event) =>
                setForm((current) => ({
                  ...current,
                  status: event.target.value,
                }))
              }
              className={inputClass}
            >
              {ORDER_STATUSES.map((status) => (
                <option key={status} value={status}>
                  {status.replaceAll("_", " ")}
                </option>
              ))}
            </select>
          </Field>

          <Field label="Shipping status">
            <select
              value={form.shipping_status}
              onChange={(event) =>
                setForm((current) => ({
                  ...current,
                  shipping_status: event.target.value,
                }))
              }
              className={inputClass}
            >
              {SHIPPING_STATUSES.map((status) => (
                <option key={status} value={status}>
                  {status.replaceAll("_", " ")}
                </option>
              ))}
            </select>
          </Field>

          <Field label="Estimated delivery">
            <input
              type="date"
              value={form.estimated_delivery}
              onChange={(event) =>
                setForm((current) => ({
                  ...current,
                  estimated_delivery: event.target.value,
                }))
              }
              className={inputClass}
            />
          </Field>
        </div>

        <div className="rounded-md border border-stone-200">
          <div className="flex items-center justify-between border-b border-stone-200 bg-stone-50 px-3 py-2">
            <p className="text-xs font-medium uppercase tracking-wide text-stone-500">
              Line items
            </p>
            <button
              type="button"
              onClick={addItem}
              className="inline-flex items-center gap-1 text-xs font-medium text-green-800 hover:underline"
            >
              <PlusIcon className="h-3 w-3" />
              Add item
            </button>
          </div>
          <div className="space-y-3 p-3">
            {form.items.map((item, index) => (
              <div
                key={index}
                className="grid gap-2 sm:grid-cols-[minmax(0,1fr)_5rem_7rem_auto]"
              >
                <input
                  value={item.product_name}
                  onChange={(event) =>
                    updateItem(index, {
                      product_name: event.target.value,
                    })
                  }
                  placeholder="Product name"
                  required
                  maxLength={255}
                  aria-label={`Product name for item ${index + 1}`}
                  className={inputClass}
                />
                <input
                  type="number"
                  min="1"
                  max="10000"
                  value={item.quantity}
                  onChange={(event) =>
                    updateItem(index, { quantity: event.target.value })
                  }
                  aria-label={`Quantity for item ${index + 1}`}
                  className={inputClass}
                />
                <input
                  type="number"
                  min="0"
                  step="0.01"
                  value={item.unit_price}
                  onChange={(event) =>
                    updateItem(index, { unit_price: event.target.value })
                  }
                  placeholder="0.00"
                  required
                  aria-label={`Unit price for item ${index + 1}`}
                  className={inputClass}
                />
                <button
                  type="button"
                  onClick={() => removeItem(index)}
                  disabled={form.items.length === 1}
                  className={dangerButtonClass}
                  aria-label={`Remove item ${index + 1}`}
                >
                  Remove
                </button>
              </div>
            ))}
          </div>
        </div>

        <div className="flex justify-end gap-2 border-t border-stone-200 pt-4">
          <button
            type="button"
            onClick={onClose}
            disabled={isSaving}
            className={secondaryButtonClass}
          >
            Cancel
          </button>
          <button
            type="submit"
            disabled={isSaving}
            className={primaryButtonClass}
          >
            {isSaving ? "Creating…" : "Create order"}
          </button>
        </div>
      </form>
    </Modal>
  );
}

function OrderDetail({ order, onChanged, onFeedback }) {
  const [status, setStatus] = useState(order.status);
  const [shippingStatus, setShippingStatus] = useState(
    order.shipping_status || "not_shipped",
  );
  const [isSavingStatus, setIsSavingStatus] = useState(false);
  const [itemDraft, setItemDraft] = useState({ ...EMPTY_ITEM });
  const [isAddingItem, setIsAddingItem] = useState(false);
  const [editingItemId, setEditingItemId] = useState(null);
  const [itemEditDraft, setItemEditDraft] = useState({ ...EMPTY_ITEM });
  const [busyItemId, setBusyItemId] = useState(null);

  const saveStatus = async () => {
    setIsSavingStatus(true);
    try {
      const updated = await adminService.updateOrder(order.id, {
        status,
        shipping_status: shippingStatus,
      });
      onChanged(updated);
      onFeedback({ tone: "success", message: "Order status updated." });
    } catch (requestError) {
      onFeedback({
        tone: "error",
        message: getAdminErrorMessage(
          requestError,
          "Could not update the order.",
        ),
      });
    } finally {
      setIsSavingStatus(false);
    }
  };

  const addItem = async (event) => {
    event.preventDefault();
    setIsAddingItem(true);
    try {
      const updated = await adminService.addOrderItem(order.id, {
        product_name: itemDraft.product_name,
        quantity: Number(itemDraft.quantity),
        unit_price: String(itemDraft.unit_price),
      });
      setItemDraft({ ...EMPTY_ITEM });
      onChanged(updated);
      onFeedback({ tone: "success", message: "Line item added." });
    } catch (requestError) {
      onFeedback({
        tone: "error",
        message: getAdminErrorMessage(
          requestError,
          "Could not add the line item.",
        ),
      });
    } finally {
      setIsAddingItem(false);
    }
  };

  const startEditItem = (item) => {
    setEditingItemId(item.id);
    setItemEditDraft({
      product_name: item.product_name,
      quantity: item.quantity,
      unit_price: item.unit_price,
    });
  };

  const saveItem = async (itemId) => {
    setBusyItemId(itemId);
    try {
      const updated = await adminService.updateOrderItem(
        order.id,
        itemId,
        {
          product_name: itemEditDraft.product_name,
          quantity: Number(itemEditDraft.quantity),
          unit_price: String(itemEditDraft.unit_price),
        },
      );
      setEditingItemId(null);
      onChanged(updated);
      onFeedback({ tone: "success", message: "Line item updated." });
    } catch (requestError) {
      onFeedback({
        tone: "error",
        message: getAdminErrorMessage(
          requestError,
          "Could not update the line item.",
        ),
      });
    } finally {
      setBusyItemId(null);
    }
  };

  const deleteItem = async (item) => {
    if (!window.confirm(`Remove "${item.product_name}" from this order?`)) {
      return;
    }
    setBusyItemId(item.id);
    try {
      const updated = await adminService.deleteOrderItem(
        order.id,
        item.id,
      );
      onChanged(updated);
      onFeedback({ tone: "success", message: "Line item removed." });
    } catch (requestError) {
      onFeedback({
        tone: "error",
        message: getAdminErrorMessage(
          requestError,
          "Could not remove the line item.",
        ),
      });
    } finally {
      setBusyItemId(null);
    }
  };

  return (
    <section className="rounded-lg border border-stone-200 bg-white">
      <div className="flex flex-wrap items-start justify-between gap-4 border-b border-stone-200 px-5 py-4">
        <div>
          <p className="text-xs uppercase tracking-wide text-stone-500">
            Order
          </p>
          <h2 className="mt-1 text-lg font-semibold tracking-tight text-stone-950">
            {order.order_number}
          </h2>
          <p className="mt-1 text-sm text-stone-500">
            {order.user.name} · {order.user.email}
          </p>
        </div>
        <div className="text-right">
          <p className="text-xs uppercase tracking-wide text-stone-500">
            Total
          </p>
          <p className="mt-1 text-lg font-semibold text-stone-950">
            {formatMoney(order.total_amount)}
          </p>
          <p className="mt-1 text-xs text-stone-500">
            Placed {formatDate(order.order_date)}
          </p>
        </div>
      </div>

      <div className="grid gap-4 border-b border-stone-200 px-5 py-4 sm:grid-cols-[1fr_1fr_auto] sm:items-end">
        <Field label="Order status">
          <select
            value={status}
            onChange={(event) => setStatus(event.target.value)}
            className={inputClass}
          >
            {ORDER_STATUSES.map((value) => (
              <option key={value} value={value}>
                {value.replaceAll("_", " ")}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Shipping status">
          <select
            value={shippingStatus}
            onChange={(event) => setShippingStatus(event.target.value)}
            className={inputClass}
          >
            {SHIPPING_STATUSES.map((value) => (
              <option key={value} value={value}>
                {value.replaceAll("_", " ")}
              </option>
            ))}
          </select>
        </Field>
        <button
          type="button"
          onClick={saveStatus}
          disabled={isSavingStatus}
          className={primaryButtonClass}
        >
          {isSavingStatus ? "Saving…" : "Save status"}
        </button>
      </div>

      <div className="px-5 py-4">
        <div className="mb-3 flex items-center justify-between">
          <h3 className="text-sm font-semibold text-stone-900">Line items</h3>
          <span className="text-xs text-stone-500">
            {order.items.length} item{order.items.length === 1 ? "" : "s"}
          </span>
        </div>

        {order.items.length === 0 ? (
          <p className="rounded-md border border-dashed border-stone-300 px-3 py-6 text-center text-sm text-stone-500">
            This order has no line items.
          </p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead className="border-b border-stone-200 text-xs uppercase tracking-wide text-stone-500">
                <tr>
                  <th className="py-2 pr-3 font-medium">Product</th>
                  <th className="py-2 pr-3 font-medium">Qty</th>
                  <th className="py-2 pr-3 font-medium">Unit price</th>
                  <th className="py-2 pr-3 font-medium">Line total</th>
                  <th className="py-2 text-right font-medium">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-stone-100">
                {order.items.map((item) =>
                  editingItemId === item.id ? (
                    <tr key={item.id}>
                      <td className="py-2 pr-3">
                        <input
                          value={itemEditDraft.product_name}
                          onChange={(event) =>
                            setItemEditDraft((current) => ({
                              ...current,
                              product_name: event.target.value,
                            }))
                          }
                          className={inputClass}
                          aria-label="Edit product name"
                        />
                      </td>
                      <td className="py-2 pr-3">
                        <input
                          type="number"
                          min="1"
                          value={itemEditDraft.quantity}
                          onChange={(event) =>
                            setItemEditDraft((current) => ({
                              ...current,
                              quantity: event.target.value,
                            }))
                          }
                          className={`${inputClass} w-20`}
                          aria-label="Edit quantity"
                        />
                      </td>
                      <td className="py-2 pr-3">
                        <input
                          type="number"
                          min="0"
                          step="0.01"
                          value={itemEditDraft.unit_price}
                          onChange={(event) =>
                            setItemEditDraft((current) => ({
                              ...current,
                              unit_price: event.target.value,
                            }))
                          }
                          className={`${inputClass} w-28`}
                          aria-label="Edit unit price"
                        />
                      </td>
                      <td className="py-2 pr-3 text-stone-500">—</td>
                      <td className="py-2">
                        <div className="flex justify-end gap-1.5">
                          <button
                            type="button"
                            onClick={() => saveItem(item.id)}
                            disabled={busyItemId === item.id}
                            className={secondaryButtonClass}
                          >
                            Save
                          </button>
                          <button
                            type="button"
                            onClick={() => setEditingItemId(null)}
                            className={secondaryButtonClass}
                          >
                            Cancel
                          </button>
                        </div>
                      </td>
                    </tr>
                  ) : (
                    <tr key={item.id}>
                      <td className="py-2 pr-3 text-stone-900">
                        {item.product_name}
                      </td>
                      <td className="py-2 pr-3 text-stone-600">
                        {item.quantity}
                      </td>
                      <td className="py-2 pr-3 text-stone-600">
                        {formatMoney(item.unit_price)}
                      </td>
                      <td className="py-2 pr-3 text-stone-600">
                        {formatMoney(
                          Number(item.unit_price) * item.quantity,
                        )}
                      </td>
                      <td className="py-2">
                        <div className="flex justify-end gap-1.5">
                          <button
                            type="button"
                            onClick={() => startEditItem(item)}
                            className={secondaryButtonClass}
                          >
                            Edit
                          </button>
                          <button
                            type="button"
                            onClick={() => deleteItem(item)}
                            disabled={busyItemId === item.id}
                            className={dangerButtonClass}
                          >
                            Remove
                          </button>
                        </div>
                      </td>
                    </tr>
                  ),
                )}
              </tbody>
            </table>
          </div>
        )}

        <form
          onSubmit={addItem}
          className="mt-4 grid gap-2 rounded-md border border-stone-200 bg-stone-50 p-3 sm:grid-cols-[minmax(0,1fr)_5rem_7rem_auto]"
        >
          <input
            value={itemDraft.product_name}
            onChange={(event) =>
              setItemDraft((current) => ({
                ...current,
                product_name: event.target.value,
              }))
            }
            placeholder="New product name"
            required
            maxLength={255}
            aria-label="New item product name"
            className={inputClass}
          />
          <input
            type="number"
            min="1"
            value={itemDraft.quantity}
            onChange={(event) =>
              setItemDraft((current) => ({
                ...current,
                quantity: event.target.value,
              }))
            }
            aria-label="New item quantity"
            className={inputClass}
          />
          <input
            type="number"
            min="0"
            step="0.01"
            value={itemDraft.unit_price}
            onChange={(event) =>
              setItemDraft((current) => ({
                ...current,
                unit_price: event.target.value,
              }))
            }
            placeholder="0.00"
            required
            aria-label="New item unit price"
            className={inputClass}
          />
          <button
            type="submit"
            disabled={isAddingItem}
            className={primaryButtonClass}
          >
            {isAddingItem ? "Adding…" : "Add item"}
          </button>
        </form>
      </div>
    </section>
  );
}

function AdminOrders() {
  const [orders, setOrders] = useState([]);
  const [users, setUsers] = useState([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState("");
  const [feedback, setFeedback] = useState(null);
  const [isCreating, setIsCreating] = useState(false);
  const [selectedId, setSelectedId] = useState(null);

  const load = useCallback(async () => {
    try {
      const [orderData, userData] = await Promise.all([
        adminService.listOrders(),
        adminService.listUsers(),
      ]);
      setOrders(orderData);
      setUsers(userData);
      setError("");
    } catch (requestError) {
      setError(
        getAdminErrorMessage(
          requestError,
          "Could not load orders.",
        ),
      );
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    let cancelled = false;

    const loadInitial = async () => {
      try {
        const [orderData, userData] = await Promise.all([
          adminService.listOrders(),
          adminService.listUsers(),
        ]);
        if (!cancelled) {
          setOrders(orderData);
          setUsers(userData);
          setError("");
        }
      } catch (requestError) {
        if (!cancelled) {
          setError(
            getAdminErrorMessage(
              requestError,
              "Could not load orders.",
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

  const selectedOrder = useMemo(
    () => orders.find((order) => order.id === selectedId) || null,
    [orders, selectedId],
  );

  const handleChanged = (updatedOrder) => {
    setOrders((current) =>
      current.map((order) =>
        order.id === updatedOrder.id ? updatedOrder : order,
      ),
    );
  };

  const handleCreated = async (order) => {
    setIsCreating(false);
    setFeedback({ tone: "success", message: "Order created." });
    setSelectedId(order.id);
    await load();
  };

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="Synthetic store"
        title="Orders"
        description="Create synthetic orders, update fulfilment status, and manage line items. Totals are recalculated after every item change."
        actions={
          <button
            type="button"
            onClick={() => setIsCreating(true)}
            className={primaryButtonClass}
          >
            <PlusIcon className="h-3.5 w-3.5" />
            New order
          </button>
        }
      />

      {error ? <FeedbackBanner tone="error">{error}</FeedbackBanner> : null}
      {feedback ? (
        <FeedbackBanner
          tone={feedback.tone}
          onDismiss={() => setFeedback(null)}
        >
          {feedback.message}
        </FeedbackBanner>
      ) : null}

      {isLoading ? (
        <p className="text-sm text-stone-500">Loading orders…</p>
      ) : orders.length === 0 ? (
        <EmptyState
          title="No orders yet"
          description="Create a synthetic order so the agent can answer order-status questions."
          action={
            <button
              type="button"
              onClick={() => setIsCreating(true)}
              className={primaryButtonClass}
            >
              New order
            </button>
          }
        />
      ) : (
        <div className="overflow-hidden rounded-lg border border-stone-200 bg-white">
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead className="bg-stone-50 text-xs uppercase tracking-wide text-stone-500">
                <tr>
                  <th className="px-5 py-3 font-medium">Order</th>
                  <th className="px-5 py-3 font-medium">Customer</th>
                  <th className="px-5 py-3 font-medium">Status</th>
                  <th className="px-5 py-3 font-medium">Shipping</th>
                  <th className="px-5 py-3 font-medium">Total</th>
                  <th className="px-5 py-3 font-medium">Items</th>
                  <th className="px-5 py-3 text-right font-medium">
                    Actions
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y divide-stone-100">
                {orders.map((order) => (
                  <tr
                    key={order.id}
                    className={
                      order.id === selectedId ? "bg-green-50/40" : undefined
                    }
                  >
                    <td className="whitespace-nowrap px-5 py-3">
                      <p className="font-medium text-stone-900">
                        {order.order_number}
                      </p>
                      <p className="text-xs text-stone-500">
                        {formatDate(order.order_date)}
                      </p>
                    </td>
                    <td className="px-5 py-3">
                      <p className="text-stone-900">{order.user.name}</p>
                      <p className="text-xs text-stone-500">
                        {order.user.email}
                      </p>
                    </td>
                    <td className="whitespace-nowrap px-5 py-3">
                      <StatusPill value={order.status} />
                    </td>
                    <td className="whitespace-nowrap px-5 py-3">
                      <StatusPill
                        value={order.shipping_status || "not_shipped"}
                      />
                    </td>
                    <td className="whitespace-nowrap px-5 py-3 text-stone-700">
                      {formatMoney(order.total_amount)}
                    </td>
                    <td className="whitespace-nowrap px-5 py-3 text-stone-600">
                      {order.items.length}
                    </td>
                    <td className="px-5 py-3 text-right">
                      <button
                        type="button"
                        onClick={() =>
                          setSelectedId(
                            order.id === selectedId ? null : order.id,
                          )
                        }
                        className={secondaryButtonClass}
                      >
                        {order.id === selectedId ? "Close" : "Manage"}
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {selectedOrder ? (
        <OrderDetail
          key={selectedOrder.id}
          order={selectedOrder}
          onChanged={handleChanged}
          onFeedback={setFeedback}
        />
      ) : null}

      {isCreating ? (
        <CreateOrderModal
          users={users}
          onClose={() => setIsCreating(false)}
          onCreated={handleCreated}
        />
      ) : null}
    </div>
  );
}

export default AdminOrders;
