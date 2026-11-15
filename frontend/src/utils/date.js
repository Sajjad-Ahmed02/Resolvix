const timeFormatter = new Intl.DateTimeFormat(undefined, {
  hour: "numeric",
  minute: "2-digit",
});

const dateFormatter = new Intl.DateTimeFormat(undefined, {
  month: "short",
  day: "numeric",
});

const fullDateFormatter = new Intl.DateTimeFormat(undefined, {
  month: "short",
  day: "numeric",
  year: "numeric",
});

function toDate(value) {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? null : date;
}

export function formatMessageTime(value) {
  const date = toDate(value);
  return date ? timeFormatter.format(date) : "";
}

export function formatConversationTime(value) {
  const date = toDate(value);
  if (!date) {
    return "";
  }

  const now = new Date();
  const isToday =
    date.getFullYear() === now.getFullYear() &&
    date.getMonth() === now.getMonth() &&
    date.getDate() === now.getDate();

  if (isToday) {
    return timeFormatter.format(date);
  }

  if (date.getFullYear() === now.getFullYear()) {
    return dateFormatter.format(date);
  }

  return fullDateFormatter.format(date);
}
