export default function MetricBar({ label, value, max = 100, color = "#4aa8ff", unit = "" }) {
  const num = Number(value);
  const pct = Number.isFinite(num) ? Math.min(100, Math.max(0, (num / max) * 100)) : 0;
  return (
    <div className="metric">
      <div className="metric__head">
        <span className="metric__label">{label}</span>
        <span className="metric__value">
          {Number.isFinite(num) ? num.toFixed(unit ? 1 : 0) : "—"}
          {unit}
        </span>
      </div>
      <div className="metric__track">
        <div className="metric__fill" style={{ width: `${pct}%`, background: color }} />
      </div>
    </div>
  );
}
