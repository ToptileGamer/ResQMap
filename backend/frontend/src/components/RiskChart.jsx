const AXIS = "#334157";
const TEXT = "#7c8aa5";

function shortTime(value) {
  const date = value instanceof Date ? value : new Date(value);
  if (Number.isNaN(date.getTime())) return String(value ?? "");
  return date.toLocaleString(undefined, { hour: "2-digit", hour12: false });
}

/**
 * Small SVG sparkline/area chart for forecast & history series.
 * points: [{ t: Date|string, value: number }]
 */
export default function RiskChart({
  points = [],
  color = "#4aa8ff",
  max,
  unit = "",
  height = 140,
}) {
  if (!points.length) return <div className="muted">No data to chart.</div>;

  const values = points.map((p) => p.value);
  const maxValue = max ?? Math.max(10, ...values);
  const minValue = Math.min(0, ...values);
  const span = maxValue - minValue || 1;

  const W = 640;
  const H = 140;
  const PAD_X = 8;
  const PAD_Y = 12;

  const x = (i) => PAD_X + (i * (W - PAD_X * 2)) / Math.max(1, points.length - 1);
  const y = (v) => H - PAD_Y - ((v - minValue) / span) * (H - PAD_Y * 2);

  const lineD = points
    .map((p, i) => `${i === 0 ? "M" : "L"}${x(i).toFixed(1)} ${y(p.value).toFixed(1)}`)
    .join(" ");
  const areaD = `${lineD} L${x(points.length - 1).toFixed(1)} ${(H - PAD_Y).toFixed(1)} L${PAD_X} ${(H - PAD_Y).toFixed(1)} Z`;

  const mid = Math.round(points.length / 2);
  const labelIndexes = [...new Set([0, mid, points.length - 1])];

  return (
    <svg
      viewBox={`0 0 ${W} ${H}`}
      role="img"
      style={{ width: "100%", height, display: "block" }}
    >
      {[0, 0.5, 1].map((f) => {
        const gy = H - PAD_Y - f * (H - PAD_Y * 2);
        return <line key={f} x1={PAD_X} x2={W - PAD_X} y1={gy} y2={gy} stroke={AXIS} strokeWidth="1" strokeDasharray="3 5" />;
      })}
      <path d={areaD} fill={color} opacity="0.16" />
      <path d={lineD} fill="none" stroke={color} strokeWidth="2" strokeLinecap="round" />
      {points.map((p, i) => (
        <g key={i}>
          <circle cx={x(i)} cy={y(p.value)} r="3.4" fill={color} stroke="#0a111f" strokeWidth="1.5" />
          <title>{`${p.value}${unit}`}</title>
        </g>
      ))}
      {labelIndexes.map((i) => (
        <text key={i} x={x(i)} y={H - 2} fill={TEXT} fontSize="10" textAnchor="middle">
          {shortTime(points[i].t)}
        </text>
      ))}
    </svg>
  );
}