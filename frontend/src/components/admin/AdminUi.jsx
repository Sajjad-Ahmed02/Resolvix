import { useEffect } from "react";

import { CloseIcon } from "../icons";

const PILL_TONES = {
  green: "border-green-200 bg-green-50 text-green-800",
  amber: "border-amber-200 bg-amber-50 text-amber-800",
  red: "border-red-200 bg-red-50 text-red-800",
  sky: "border-sky-200 bg-sky-50 text-sky-800",
  violet: "border-violet-200 bg-violet-50 text-violet-800",
  stone: "border-stone-200 bg-stone-100 text-stone-600",
};

const STATUS_TONES = {
  active: "green",
  true: "green",
  indexed: "green",
  refreshed: "sky",
  confirmed: "sky",
  processing: "violet",
  in_transit: "sky",
  out_for_delivery: "violet",
  delivered: "green",
  completed: "green",
  pending: "amber",
  skipped: "stone",
  inactive: "stone",
  false: "stone",
  not_shipped: "stone",
  deleted: "amber",
  cancelled: "red",
  failed: "red",
};

export function PageHeader({ eyebrow, title, description, actions }) {
  return (
    <div className="flex flex-col gap-4 border-b border-stone-200 pb-6 sm:flex-row sm:items-end sm:justify-between">
      <div>
        {eyebrow ? (
          <p className="text-xs font-medium uppercase tracking-[0.14em] text-green-800">
            {eyebrow}
          </p>
        ) : null}
        <h1 className="mt-2 text-2xl font-semibold tracking-tight text-stone-950">
          {title}
        </h1>
        {description ? (
          <p className="mt-2 max-w-2xl text-sm leading-6 text-stone-500">
            {description}
          </p>
        ) : null}
      </div>
      {actions ? (
        <div className="flex shrink-0 flex-wrap items-center gap-2">
          {actions}
        </div>
      ) : null}
    </div>
  );
}

export function FeedbackBanner({ tone = "info", children, onDismiss }) {
  const toneClasses = {
    error: "border-red-200 bg-red-50 text-red-800",
    success: "border-green-200 bg-green-50 text-green-800",
    info: "border-sky-200 bg-sky-50 text-sky-800",
  };

  return (
    <div
      role={tone === "error" ? "alert" : "status"}
      className={`flex items-start justify-between gap-4 rounded-md border px-3.5 py-3 text-sm leading-5 ${toneClasses[tone]}`}
    >
      <div className="min-w-0 break-words">{children}</div>
      {onDismiss ? (
        <button
          type="button"
          onClick={onDismiss}
          className="shrink-0 text-current opacity-60 transition hover:opacity-100"
          aria-label="Dismiss message"
        >
          <CloseIcon className="h-4 w-4" />
        </button>
      ) : null}
    </div>
  );
}

export function StatusPill({ value, label }) {
  const key = String(value);
  const tone = PILL_TONES[STATUS_TONES[key]] || "stone";
  const text = label ?? key.replaceAll("_", " ");
  return (
    <span
      className={`inline-flex items-center rounded-full border px-2 py-0.5 text-[11px] font-medium capitalize ${tone}`}
    >
      {text}
    </span>
  );
}

export function EmptyState({ title, description, action }) {
  return (
    <div className="rounded-lg border border-dashed border-stone-300 bg-white px-6 py-12 text-center">
      <p className="text-sm font-medium text-stone-800">{title}</p>
      {description ? (
        <p className="mx-auto mt-1 max-w-md text-sm leading-6 text-stone-500">
          {description}
        </p>
      ) : null}
      {action ? <div className="mt-4">{action}</div> : null}
    </div>
  );
}

export function Modal({ title, description, onClose, children, footer }) {
  useEffect(() => {
    const onKeyDown = (event) => {
      if (event.key === "Escape") {
        onClose();
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [onClose]);

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-stone-950/40 p-4 sm:p-8">
      <div
        role="dialog"
        aria-modal="true"
        aria-label={title}
        className="my-auto w-full max-w-2xl rounded-lg border border-stone-200 bg-white shadow-xl"
      >
        <div className="flex items-start justify-between gap-4 border-b border-stone-200 px-5 py-4">
          <div>
            <h2 className="text-base font-semibold tracking-tight text-stone-950">
              {title}
            </h2>
            {description ? (
              <p className="mt-1 text-sm leading-5 text-stone-500">
                {description}
              </p>
            ) : null}
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded-md p-1 text-stone-500 transition hover:bg-stone-100 hover:text-stone-900"
            aria-label="Close dialog"
          >
            <CloseIcon className="h-4 w-4" />
          </button>
        </div>
        <div className="px-5 py-4">{children}</div>
        {footer ? (
          <div className="flex flex-wrap justify-end gap-2 border-t border-stone-200 px-5 py-3">
            {footer}
          </div>
        ) : null}
      </div>
    </div>
  );
}

export function Field({ label, hint, children }) {
  return (
    <label className="block text-[13px] font-medium text-stone-700">
      <span className="mb-1.5 block">{label}</span>
      {children}
      {hint ? (
        <span className="mt-1 block text-xs font-normal leading-5 text-stone-500">
          {hint}
        </span>
      ) : null}
    </label>
  );
}

export const inputClass =
  "w-full rounded-md border border-stone-300 bg-white px-3 py-2 text-sm text-stone-900 outline-none transition placeholder:text-stone-400 focus:border-green-800 focus:ring-2 focus:ring-green-800/10 disabled:cursor-not-allowed disabled:bg-stone-100";

export const primaryButtonClass =
  "inline-flex items-center justify-center gap-1.5 rounded-md bg-stone-950 px-3.5 py-2 text-sm font-medium text-white transition hover:bg-stone-800 focus:outline-none focus-visible:ring-2 focus-visible:ring-stone-900 focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-60";

export const secondaryButtonClass =
  "inline-flex items-center justify-center gap-1.5 rounded-md border border-stone-300 bg-white px-3 py-1.5 text-sm font-medium text-stone-700 transition hover:border-stone-400 hover:bg-stone-50 focus:outline-none focus-visible:ring-2 focus-visible:ring-green-800/20 disabled:cursor-not-allowed disabled:opacity-60";

export const dangerButtonClass =
  "inline-flex items-center justify-center gap-1.5 rounded-md border border-red-200 bg-white px-3 py-1.5 text-sm font-medium text-red-700 transition hover:border-red-300 hover:bg-red-50 focus:outline-none focus-visible:ring-2 focus-visible:ring-red-300/40 disabled:cursor-not-allowed disabled:opacity-60";
