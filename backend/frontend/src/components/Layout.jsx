import { NavLink, Outlet } from "react-router-dom";
import { useCallback } from "react";
import { api } from "../api/client";
import { useApi } from "../hooks/useApi";
import { formatRelative } from "../lib/format";

const NAV = [
  { to: "/", label: "Dashboard", icon: "◎", end: true },
  { to: "/zones", label: "Zones", icon: "▦" },
  { to: "/aerial", label: "Aerial AI", icon: "◖" },
  { to: "/sos", label: "SOS Reports", icon: "◉" },
  { to: "/route", label: "Drone Routes", icon: "✈" },
  { to: "/risk", label: "Risk Forecast", icon: "◈" },
];

export default function Layout() {
  const healthFn = useCallback(() => api.health(), []);
  const { data, error, loading, refetch } = useApi(healthFn, []);

  const online = !loading && !error && data?.status === "ok";

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <div className="brand__mark">R</div>
          <div>
            <div className="brand__name">ResQMap</div>
            <div className="brand__sub">AI Decision Support</div>
          </div>
        </div>

        <nav className="nav">
          {NAV.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.end}
              className={({ isActive }) => `nav__item ${isActive ? "is-active" : ""}`}
            >
              <span className="nav__icon">{item.icon}</span>
              {item.label}
            </NavLink>
          ))}
        </nav>

        <div className="sidebar__foot">
          <button type="button" className="health" onClick={refetch} title="Re-check backend health">
            <span className={`health__dot ${online ? "is-on" : "is-off"}`} />
            <span className="health__text">
              <strong>{loading ? "Checking…" : online ? "Backend online" : "Backend offline"}</strong>
              <small>{data?.environment || (error ? "unreachable" : "—")} · {data?.data_mode || ""}</small>
              {data?.offline_mode && <small>OFFLINE simulated</small>}
            </span>
          </button>
          <div className="disclaimer">Prototype — DEM/GIS/drone frames are labelled-simulated; SOS, uploads + weather (when key set) are real.</div>
        </div>
      </aside>

      <main className="content">
        <Outlet />
      </main>
    </div>
  );
}

export function PageHeader({ title, subtitle, actions, updatedAt }) {
  return (
    <header className="page-header">
      <div>
        <h1 className="page-title">{title}</h1>
        {subtitle && <p className="page-subtitle">{subtitle}</p>}
        {updatedAt && <p className="page-updated">Updated {formatRelative(updatedAt)}</p>}
      </div>
      {actions && <div className="page-actions">{actions}</div>}
    </header>
  );
}
