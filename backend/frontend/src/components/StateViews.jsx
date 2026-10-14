export function Loading({ label = "Loading…" }) {
  return (
    <div className="state-view">
      <span className="spinner" />
      <span>{label}</span>
    </div>
  );
}

export function ErrorState({ error, onRetry, label = "Something went wrong" }) {
  const isNetwork =
    error?.name === "TypeError" || /fetch|network|failed to fetch/i.test(error?.message || "");
  const message = error?.message || String(error || "");
  return (
    <div className="state-view state-view--error">
      <div className="state-view__title">{label}</div>
      <div className="state-view__body">
        {isNetwork
          ? "Could not reach the ResQMap backend. Is it running and reachable at the configured API URL?"
          : message}
      </div>
      {onRetry && (
        <button type="button" className="btn btn--ghost" onClick={onRetry}>
          Retry
        </button>
      )}
    </div>
  );
}

export function EmptyState({ title = "Nothing here yet", body, action }) {
  return (
    <div className="state-view">
      <div className="state-view__title">{title}</div>
      {body && <div className="state-view__body">{body}</div>}
      {action}
    </div>
  );
}
