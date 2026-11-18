import { useCallback, useEffect, useState } from "react";

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
import { formatConversationTime } from "../../utils/date";
import {
  getAdminErrorMessage,
  summarizeIndexing,
} from "../../utils/adminError";

const EMPTY_FORM = {
  title: "",
  content: "",
  category: "",
  is_active: true,
};

function AdminDocuments() {
  const [documents, setDocuments] = useState([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState("");
  const [feedback, setFeedback] = useState(null);
  const [editing, setEditing] = useState(null);
  const [viewing, setViewing] = useState(null);
  const [form, setForm] = useState(EMPTY_FORM);
  const [formError, setFormError] = useState("");
  const [isSaving, setIsSaving] = useState(false);
  const [isReindexing, setIsReindexing] = useState(false);
  const [busyId, setBusyId] = useState(null);

  const load = useCallback(async () => {
    try {
      setDocuments(await adminService.listDocuments());
      setError("");
    } catch (requestError) {
      setError(
        getAdminErrorMessage(
          requestError,
          "Could not load knowledge documents.",
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
        const data = await adminService.listDocuments();
        if (!cancelled) {
          setDocuments(data);
          setError("");
        }
      } catch (requestError) {
        if (!cancelled) {
          setError(
            getAdminErrorMessage(
              requestError,
              "Could not load knowledge documents.",
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

  const openCreate = () => {
    setEditing({});
    setForm(EMPTY_FORM);
    setFormError("");
  };

  const openEdit = (document) => {
    setEditing(document);
    setForm({
      title: document.title,
      content: document.content,
      category: document.category,
      is_active: document.is_active,
    });
    setFormError("");
  };

  const closeModal = () => {
    if (isSaving) {
      return;
    }
    setEditing(null);
    setFormError("");
  };

  const handleSubmit = async (event) => {
    event.preventDefault();
    setFormError("");
    setIsSaving(true);

    try {
      const result = editing?.id
        ? await adminService.updateDocument(editing.id, form)
        : await adminService.createDocument(form);
      setFeedback(summarizeIndexing(result.indexing));
      setEditing(null);
      await load();
    } catch (requestError) {
      setFormError(
        getAdminErrorMessage(
          requestError,
          "Could not save the knowledge document.",
        ),
      );
    } finally {
      setIsSaving(false);
    }
  };

  const toggleActive = async (document) => {
    setBusyId(document.id);
    setFeedback(null);
    try {
      const result = await adminService.updateDocument(document.id, {
        title: document.title,
        content: document.content,
        category: document.category,
        is_active: !document.is_active,
      });
      setFeedback(summarizeIndexing(result.indexing));
      await load();
    } catch (requestError) {
      setFeedback({
        tone: "error",
        message: getAdminErrorMessage(
          requestError,
          "Could not change the document status.",
        ),
      });
    } finally {
      setBusyId(null);
    }
  };

  const reindex = async (document) => {
    setBusyId(document.id);
    setFeedback(null);
    try {
      const result = await adminService.reindexDocument(document.id);
      setFeedback(summarizeIndexing(result));
      await load();
    } catch (requestError) {
      setFeedback({
        tone: "error",
        message: getAdminErrorMessage(
          requestError,
          "Re-indexing failed.",
        ),
      });
    } finally {
      setBusyId(null);
    }
  };

  const remove = async (document) => {
    if (
      !window.confirm(
        `Delete "${document.title}"? This also removes its indexed chunks.`,
      )
    ) {
      return;
    }

    setBusyId(document.id);
    setFeedback(null);
    try {
      await adminService.deleteDocument(document.id);
      setFeedback({ tone: "success", message: "Document deleted." });
      await load();
    } catch (requestError) {
      setFeedback({
        tone: "error",
        message: getAdminErrorMessage(
          requestError,
          "Could not delete the document.",
        ),
      });
    } finally {
      setBusyId(null);
    }
  };

  const reindexAll = async () => {
    setIsReindexing(true);
    setFeedback(null);
    try {
      const result = await adminService.reindexAll();
      const failed = result.summary.failed || 0;
      if (failed) {
        const failures = result.results
          .filter((item) => item.status === "failed")
          .map((item) => `${item.title}: ${item.error || "unknown error"}`);
        setFeedback({
          tone: "error",
          message: `${failed} source(s) failed to re-index. ${failures.join(
            " · ",
          )}`,
        });
      } else {
        setFeedback({
          tone: "success",
          message: `Re-indexed ${
            result.summary.indexed + result.summary.refreshed
          } source(s); ${result.summary.skipped} already current.`,
        });
      }
      await load();
    } catch (requestError) {
      setFeedback({
        tone: "error",
        message: getAdminErrorMessage(
          requestError,
          "Could not re-index the knowledge base.",
        ),
      });
    } finally {
      setIsReindexing(false);
    }
  };

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="Knowledge base"
        title="Knowledge documents"
        description="Long-form policies and product content. Updating content re-chunks the document and regenerates embeddings."
        actions={
          <>
            <button
              type="button"
              onClick={reindexAll}
              disabled={isReindexing}
              className={secondaryButtonClass}
            >
              {isReindexing ? "Re-indexing…" : "Re-index all"}
            </button>
            <button
              type="button"
              onClick={openCreate}
              className={primaryButtonClass}
            >
              <PlusIcon className="h-3.5 w-3.5" />
              New document
            </button>
          </>
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
        <p className="text-sm text-stone-500">Loading documents…</p>
      ) : documents.length === 0 ? (
        <EmptyState
          title="No knowledge documents yet"
          description="Add a policy or product guide so the agent can retrieve it."
          action={
            <button
              type="button"
              onClick={openCreate}
              className={primaryButtonClass}
            >
              New document
            </button>
          }
        />
      ) : (
        <div className="overflow-hidden rounded-lg border border-stone-200 bg-white">
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead className="bg-stone-50 text-xs uppercase tracking-wide text-stone-500">
                <tr>
                  <th className="px-5 py-3 font-medium">Title</th>
                  <th className="px-5 py-3 font-medium">Category</th>
                  <th className="px-5 py-3 font-medium">Status</th>
                  <th className="px-5 py-3 font-medium">Updated</th>
                  <th className="px-5 py-3 text-right font-medium">
                    Actions
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y divide-stone-100">
                {documents.map((document) => (
                  <tr key={document.id} className="align-top">
                    <td className="max-w-md px-5 py-4">
                      <p className="font-medium text-stone-900">
                        {document.title}
                      </p>
                      <p className="mt-1 line-clamp-2 text-xs leading-5 text-stone-500">
                        {document.content}
                      </p>
                    </td>
                    <td className="whitespace-nowrap px-5 py-4 text-stone-600">
                      {document.category}
                    </td>
                    <td className="whitespace-nowrap px-5 py-4">
                      <StatusPill
                        value={document.is_active ? "active" : "inactive"}
                        label={document.is_active ? "Active" : "Inactive"}
                      />
                    </td>
                    <td className="whitespace-nowrap px-5 py-4 text-xs text-stone-500">
                      {formatConversationTime(document.updated_at)}
                    </td>
                    <td className="px-5 py-4">
                      <div className="flex flex-wrap justify-end gap-1.5">
                        <button
                          type="button"
                          onClick={() => setViewing(document)}
                          className={secondaryButtonClass}
                        >
                          View
                        </button>
                        <button
                          type="button"
                          onClick={() => openEdit(document)}
                          className={secondaryButtonClass}
                        >
                          Edit
                        </button>
                        <button
                          type="button"
                          onClick={() => reindex(document)}
                          disabled={busyId === document.id}
                          className={secondaryButtonClass}
                        >
                          Re-index
                        </button>
                        <button
                          type="button"
                          onClick={() => toggleActive(document)}
                          disabled={busyId === document.id}
                          className={secondaryButtonClass}
                        >
                          {document.is_active ? "Deactivate" : "Activate"}
                        </button>
                        <button
                          type="button"
                          onClick={() => remove(document)}
                          disabled={busyId === document.id}
                          className={dangerButtonClass}
                        >
                          Delete
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {viewing ? (
        <Modal
          title={viewing.title}
          description={`${viewing.category} · ${
            viewing.is_active ? "Active" : "Inactive"
          }`}
          onClose={() => setViewing(null)}
        >
          <p className="max-h-[60vh] overflow-y-auto whitespace-pre-wrap text-sm leading-6 text-stone-700">
            {viewing.content}
          </p>
        </Modal>
      ) : null}

      {editing ? (
        <Modal
          title={editing.id ? "Edit document" : "New document"}
          description="Saving commits the source, then chunks and embeds the content."
          onClose={closeModal}
        >
          <form onSubmit={handleSubmit} className="space-y-4">
            {formError ? (
              <FeedbackBanner tone="error">{formError}</FeedbackBanner>
            ) : null}

            <Field label="Title">
              <input
                value={form.title}
                onChange={(event) =>
                  setForm((current) => ({
                    ...current,
                    title: event.target.value,
                  }))
                }
                required
                minLength={3}
                maxLength={255}
                className={inputClass}
              />
            </Field>

            <Field
              label="Content"
              hint="Chunking and embeddings run automatically when you save."
            >
              <textarea
                value={form.content}
                onChange={(event) =>
                  setForm((current) => ({
                    ...current,
                    content: event.target.value,
                  }))
                }
                rows={12}
                required
                minLength={3}
                maxLength={200000}
                className={inputClass}
              />
            </Field>

            <div className="grid gap-4 sm:grid-cols-2">
              <Field label="Category">
                <input
                  value={form.category}
                  onChange={(event) =>
                    setForm((current) => ({
                      ...current,
                      category: event.target.value,
                    }))
                  }
                  required
                  maxLength={100}
                  placeholder="returns"
                  className={inputClass}
                />
              </Field>

              <label className="flex items-end gap-2 pb-2 text-sm text-stone-700">
                <input
                  type="checkbox"
                  checked={form.is_active}
                  onChange={(event) =>
                    setForm((current) => ({
                      ...current,
                      is_active: event.target.checked,
                    }))
                  }
                  className="h-4 w-4 rounded border-stone-300 text-green-800 focus:ring-green-800"
                />
                Active (retrievable by the agent)
              </label>
            </div>

            <div className="flex justify-end gap-2 border-t border-stone-200 pt-4">
              <button
                type="button"
                onClick={closeModal}
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
                {isSaving
                  ? "Saving…"
                  : editing.id
                    ? "Save changes"
                    : "Create document"}
              </button>
            </div>
          </form>
        </Modal>
      ) : null}
    </div>
  );
}

export default AdminDocuments;
