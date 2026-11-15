function FullPageLoader({ label = "Loading…" }) {
  return (
    <div className="flex min-h-dvh items-center justify-center bg-stone-100 text-stone-600">
      <div className="flex items-center gap-3">
        <span
          className="h-5 w-5 animate-spin rounded-full border-2 border-stone-300 border-t-green-800"
          aria-hidden="true"
        />
        <p className="text-sm">{label}</p>
      </div>
    </div>
  );
}

export default FullPageLoader;
