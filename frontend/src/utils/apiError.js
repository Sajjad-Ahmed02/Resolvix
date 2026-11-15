export function getErrorMessage(error, fallback) {
  const detail = error?.response?.data?.detail;

  if (typeof detail === "string" && detail.trim()) {
    return detail;
  }

  if (Array.isArray(detail)) {
    const messages = detail
      .map((item) => (typeof item?.msg === "string" ? item.msg : null))
      .filter(Boolean);
    if (messages.length) {
      return messages.join(" ");
    }
  }

  if (error?.code === "ERR_NETWORK" || (!error?.response && error?.request)) {
    return "Cannot reach the Resolvix API. Check that the backend is running.";
  }

  return fallback;
}
