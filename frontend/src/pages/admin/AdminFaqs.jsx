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
  question: "",
  answer: "",
  category: "",
  is_active: true,
};

function AdminFaqs() {
  const [faqs, setFaqs] = useState([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState("");
  const [feedback, setFeedback] = useState(null);
  const [editing, setEditing] = useState(null);
  const [form, setForm] = useState(EMPTY_FORM);
  const [formError, setFormError] = useState("");
  const [isSaving, setIsSaving] = useState(false);
  const [isReindexing, setIsReindexing] = useState(false);
  const [busyId, setBusyId] = useState(null);

  const load = useCallback(async () => {
    try {
      setFaqs(await adminService.listFaqs());
      setError("");
    } catch (requestError) {
      setError(
        getAdminErrorMessage(
          requestError,
          "Could not load FAQs.",
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
        const data = await adminService.listFaqs();
        if (!cancelled) {
          setFaqs(data);
          setError("");
        }
      } catch (requestError) {
        if (!cancelled) {
          setError(
            getAdminErrorMessage(
              requestError,
              "Could not load FAQs.",
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

  const openEdit = (faq) => {
    setEditing(faq);
    setForm({
      question: faq.question,
      answer: faq.answer,
      category: faq.category,
      is_active: faq.is_active,
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
        ? await adminService.updateFaq(editing.id, form)
        : await adminService.createFaq(form);
      const summary = summarizeIndexing(result.indexing);
      setFeedback(summary);
      setEditing(null);
      await load();
    } catch (requestError) {
      setFormError(
        getAdminErrorMessage(
          requestError,
          "Could not save the FAQ.",
        ),
      );
    } finally {
      setIsSaving(false);
    }
  };

  const toggleActive = async (faq) => {
    setBusyId(faq.id);
    setFeedback(null);
    try {
      const result = await adminService.updateFaq(faq.id, {
        question: faq.question,
        answer: faq.answer,
        category: faq.category,
        is_active: !faq.is_active,
      });
      setFeedback(summarizeIndexing(result.indexing));
      await load();
    } catch (requestError) {
      setFeedback({
        tone: "error",
        message: getAdminErrorMessage(
          requestError,
          "Could not change the FAQ status.",
        ),
      });
    } finally {
      setBusyId(null);
    }
  };

  const reindex = async (faq) => {
    setBusyId(faq.id);
    setFeedback(null);
    try {
      const result = await adminService.reindexFaq(faq.id);
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

  const remove = async (faq) => {
    if (
      !window.confirm(
        `Delete the FAQ "${faq.question}"? This also removes its indexed chunks.`,
      )
    ) {
      return;
    }

    setBusyId(faq.id);
    setFeedback(null);
    try {
      await adminService.deleteFaq(faq.id);
      setFeedback({ tone: "success", message: "FAQ deleted." });
      await load();
    } catch (requestError) {
      setFeedback({
        tone: "error",
        message: getAdminErrorMessage(
          requestError,
          "Could not delete the FAQ.",
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
        title="FAQs"
        description="Create, edit, deactivate, and delete support answers. Every change re-synchronizes the FAQ's chunks and embeddings."
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
              New FAQ
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
        <p className="text-sm text-stone-500">Loading FAQs…</p>
      ) : faqs.length === 0 ? (
        <EmptyState
          title="No FAQs yet"
          description="Add the first support answer to start building the retrieval index."
          action={
            <button
              type="button"
              onClick={openCreate}
              className={primaryButtonClass}
            >
              New FAQ
            </button>
          }
        />
      ) : (
        <div className="overflow-hidden rounded-lg border border-stone-200 bg-white">
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead className="bg-stone-50 text-xs uppercase tracking-wide text-stone-500">
                <tr>
                  <th className="px-5 py-3 font-medium">Question</th>
                  <th className="px-5 py-3 font-medium">Category</th>
                  <th className="px-5 py-3 font-medium">Status</th>
                  <th className="px-5 py-3 font-medium">Updated</th>
                  <th className="px-5 py-3 text-right font-medium">
                    Actions
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y divide-stone-100">
                {faqs.map((faq) => (
                  <tr key={faq.id} className="align-top">
                    <td className="max-w-md px-5 py-4">
                      <p className="font-medium text-stone-900">
                        {faq.question}
                      </p>
                      <p className="mt-1 line-clamp-2 text-xs leading-5 text-stone-500">
                        {faq.answer}
                      </p>
                    </td>
                    <td className="whitespace-nowrap px-5 py-4 text-stone-600">
                      {faq.category}
                    </td>
                    <td className="whitespace-nowrap px-5 py-4">
                      <StatusPill
                        value={faq.is_active ? "active" : "inactive"}
                        label={faq.is_active ? "Active" : "Inactive"}
                      />
                    </td>
                    <td className="whitespace-nowrap px-5 py-4 text-xs text-stone-500">
                      {formatConversationTime(faq.updated_at)}
                    </td>
                    <td className="px-5 py-4">
                      <div className="flex flex-wrap justify-end gap-1.5">
                        <button
                          type="button"
                          onClick={() => openEdit(faq)}
                          className={secondaryButtonClass}
                        >
                          Edit
                        </button>
                        <button
                          type="button"
                          onClick={() => reindex(faq)}
                          disabled={busyId === faq.id}
                          className={secondaryButtonClass}
                        >
                          Re-index
                        </button>
                        <button
                          type="button"
                          onClick={() => toggleActive(faq)}
                          disabled={busyId === faq.id}
                          className={secondaryButtonClass}
                        >
                          {faq.is_active ? "Deactivate" : "Activate"}
                        </button>
                        <button
                          type="button"
                          onClick={() => remove(faq)}
                          disabled={busyId === faq.id}
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

      {editing ? (
        <Modal
          title={editing.id ? "Edit FAQ" : "New FAQ"}
          description="Saving commits the FAQ and queues chunking plus embedding generation."
          onClose={closeModal}
        >
          <form onSubmit={handleSubmit} className="space-y-4">
            {formError ? (
              <FeedbackBanner tone="error">{formError}</FeedbackBanner>
            ) : null}

            <Field label="Question">
              <textarea
                value={form.question}
                onChange={(event) =>
                  setForm((current) => ({
                    ...current,
                    question: event.target.value,
                  }))
                }
                rows={2}
                required
                minLength={3}
                maxLength={2000}
                className={inputClass}
              />
            </Field>

            <Field label="Answer">
              <textarea
                value={form.answer}
                onChange={(event) =>
                  setForm((current) => ({
                    ...current,
                    answer: event.target.value,
                  }))
                }
                rows={4}
                required
                minLength={3}
                maxLength={20000}
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
                  placeholder="shipping"
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
                {isSaving ? "Saving…" : editing.id ? "Save changes" : "Create FAQ"}
              </button>
            </div>
          </form>
        </Modal>
      ) : null}
    </div>
  );
}

export default AdminFaqs;
