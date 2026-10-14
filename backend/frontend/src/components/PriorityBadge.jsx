import { priorityColor } from "../lib/format";

export default function PriorityBadge({ level, score, compact = false }) {
  if (!level) return null;
  const color = priorityColor(level);
  return (
    <span
      className={`badge ${compact ? "badge--compact" : ""}`}
      style={{
        color,
        borderColor: `${color}55`,
        background: `${color}1a`,
      }}
    >
      <span className="badge__dot" style={{ background: color }} />
      {level}
      {score !== undefined && score !== null && (
        <span className="badge__score">{Math.round(score)}</span>
      )}
    </span>
  );
}
