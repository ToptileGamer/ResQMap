export default function StatCard({ label, value, hint, accent = "#4aa8ff", icon }) {
  return (
    <div className="stat-card" style={{ "--accent": accent }}>
      <div className="stat-card__top">
        <span className="stat-card__label">{label}</span>
        {icon && <span className="stat-card__icon">{icon}</span>}
      </div>
      <div className="stat-card__value">{value}</div>
      {hint && <div className="stat-card__hint">{hint}</div>}
    </div>
  );
}
