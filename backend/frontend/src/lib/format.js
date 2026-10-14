export const PRIORITY_LEVELS = ["Critical", "High", "Moderate", "Low"];

export const PRIORITY_META = {
  Critical: { color: "#ff3b5c", label: "Critical", rank: 0 },
  High: { color: "#ff8a3d", label: "High", rank: 1 },
  Moderate: { color: "#ffd23f", label: "Moderate", rank: 2 },
  Low: { color: "#39d98a", label: "Low", rank: 3 },
};

export function priorityColor(level) {
  return PRIORITY_META[level]?.color || "#7c8aa5";
}

export function statusColor(status) {
  const map = {
    active: "#ff3b5c",
    monitoring: "#ffd23f",
    watch: "#4aa8ff",
    stable: "#39d98a",
  };
  return map[String(status || "").toLowerCase()] || "#7c8aa5";
}

export function formatDateTime(value) {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  return date.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function formatRelative(value) {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  const diff = Date.now() - date.getTime();
  const mins = Math.round(diff / 60000);
  if (Math.abs(mins) < 1) return "just now";
  if (Math.abs(mins) < 60) return `${mins}m ago`;
  const hours = Math.round(mins / 60);
  if (Math.abs(hours) < 24) return `${hours}h ago`;
  const days = Math.round(hours / 24);
  return `${days}d ago`;
}

export function formatNumber(value, digits = 0) {
  if (value === null || value === undefined || value === "") return "—";
  const num = Number(value);
  if (Number.isNaN(num)) return String(value);
  return num.toLocaleString(undefined, {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

export function humanize(value) {
  if (!value) return "—";
  return String(value)
    .replace(/[_-]+/g, " ")
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

export function severityColor(severity) {
  const s = Number(severity) || 0;
  if (s >= 5) return "#ff3b5c";
  if (s === 4) return "#ff8a3d";
  if (s === 3) return "#ffd23f";
  return "#39d98a";
}

export function sortByPriority(a, b) {
  const ra = PRIORITY_META[a.priority_level]?.rank ?? 99;
  const rb = PRIORITY_META[b.priority_level]?.rank ?? 99;
  if (ra !== rb) return ra - rb;
  return (b.priority_score ?? 0) - (a.priority_score ?? 0);
}
