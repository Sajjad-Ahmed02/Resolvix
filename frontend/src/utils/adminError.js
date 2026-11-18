import { getErrorMessage } from "./apiError";

/**
 * Read an error message from the admin API, including structured 502 payloads
 * returned when a source was saved but re-indexing failed.
 */
export function getAdminErrorMessage(error, fallback) {
  const detail = error?.response?.data?.detail;

  if (detail && typeof detail === "object" && !Array.isArray(detail)) {
    const message =
      typeof detail.message === "string" ? detail.message : fallback;
    const reason = typeof detail.error === "string" ? detail.error : "";
    return reason ? `${message} ${reason}` : message;
  }

  return getErrorMessage(error, fallback);
}

export function summarizeIndexing(indexing) {
  if (!indexing) {
    return null;
  }

  if (indexing.status === "failed") {
    return {
      tone: "error",
      message: `Indexing failed: ${indexing.error || "unknown error"}`,
    };
  }

  const chunksLabel = `${indexing.chunks} chunk${
    indexing.chunks === 1 ? "" : "s"
  }`;

  switch (indexing.status) {
    case "indexed":
      return { tone: "success", message: `Indexed ${chunksLabel}.` };
    case "refreshed":
      return { tone: "success", message: `Refreshed ${chunksLabel}.` };
    case "deleted":
      return {
        tone: "success",
        message: "Removed the source from the vector index.",
      };
    case "skipped":
      return {
        tone: "info",
        message: "The vector index is already up to date.",
      };
    default:
      return { tone: "info", message: `Index status: ${indexing.status}.` };
  }
}
