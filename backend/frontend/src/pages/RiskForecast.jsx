import { useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import { PageHeader } from "../components/Layout";
import ZoneMap from "../components/ZoneMap";
import PriorityBadge from "../components/PriorityBadge";
import StatCard from "../components/StatCard";
import { EmptyState, ErrorState, Loading } from "../components/StateViews";
import { formatNumber } from "../lib/format";

const HORIZONS = [0, 3, 6, 12];

export default function RiskForecast() {
  const [model, setModel] = useState("ml");
  const [horizon, setHorizon] = useState(6);
  const [rain, setRain] = useState(1.0);
  const [target, setTarget] = useState("combined");
  const [grid, setGrid] = useState(null);
  const [zones, setZones] = useState(null);
  const [metrics, setMetrics] = useState(null);
  const [backtest, setBacktest] = useState(null);
  const [alloc, setAlloc] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [predWeight, setPredWeight] = useState(0.25);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [g, z, m, b] = await Promise.all([
        api.riskGrid(model, rain, horizon),
        api.predictedZones(model, rain, horizon),
        api.modelMetrics(),
        api.backtest(8),
      ]);
      setGrid(g);
      setZones(z);
      setMetrics(m);
      setBacktest(b);
      const a = await api.allocByTarget(target, 3, 2);
      setAlloc(a);
    } catch (e) {
      setError(e.message || "Risk forecast failed");
    } finally {
      setLoading(false);
    }
  }, [model, rain, horizon, target]);

  useEffect(() => { load(); }, [load]);

  const heat = useMemo(() => {
    if (!grid?.cells) return [];
    return grid.cells.filter((c) => c.risk_probability >= 0.2).map((c) => [c.lat, c.lng, c.risk_probability]);
  }, [grid]);

  const markers = useMemo(() => {
    if (!zones?.zones) return [];
    return zones.zones.slice(0, 8).map((z) => ({
      id: z.zone_id, name: `${z.zone_name} (${Math.round(z.probability * 100)}%)`,
      lat: z.latitude, lng: z.longitude,
      color: z.probability >= 0.75 ? "#ff3b5c" : z.probability >= 0.55 ? "#ffd23f" : z.probability >= 0.35 ? "#4aa8ff" : "#39d98a",
      radius: 6 + z.probability * 10,
      subtitle: z.reason,
      href: `/zones/${z.zone_id}`,
    }));
  }, [zones]);

  return (
    <>
      <PageHeader title="Risk Forecast (Stage 3)" subtitle="Predicted flood risk: ML (default, higher recall) vs explainable rule model. All prediction data labelled simulated." />
      <section className="panel" style={{ marginBottom: 16 }}>
        <div className="panel__head"><h2 className="panel__title">Scenario Controls</h2><span className="panel__hint">changing inputs re-runs risk + ranking + allocation</span></div>
        <div className="toolbar" style={{ marginBottom: 0 }}>
          <label>Model: <select className="input input--sm" value={model} onChange={(e) => setModel(e.target.value)}><option value="ml">ML RandomForest (default)</option><option value="rule">Rule-based (explainable)</option></select></label>
          <label>Horizon: <select className="input input--sm" value={horizon} onChange={(e) => setHorizon(Number(e.target.value))}>{HORIZONS.map((h) => <option key={h} value={h}>T+{h}h</option>)}</select></label>
          <label>Rainfall ×{rain.toFixed(1)} <input type="range" min="0.2" max="3" step="0.1" value={rain} onChange={(e) => setRain(Number(e.target.value))} /></label>
          <label>Allocation target: <select className="input input--sm" value={target} onChange={(e) => setTarget(e.target.value)}><option value="current">Current</option><option value="predicted">Predicted</option><option value="combined">Combined</option></select></label>
          <label>Predicted weight {Math.round(predWeight * 100)}% <input type="range" min="0" max="0.8" step="0.05" value={predWeight} onChange={(e) => setPredWeight(Number(e.target.value))} /></label>
          <button className="btn btn--primary" onClick={load} disabled={loading}>{loading ? "Running…" : "Re-run"}</button>
        </div>
        <div className="muted" style={{ marginTop: 8 }}>Uncertainty: rainfall ±20% band shown below. Simulated prediction — not authoritative.</div>
      </section>

      {loading && !grid && <Loading label="Computing risk grid…" />}
      {error && <ErrorState error={error} onRetry={load} label="Risk forecast failed" />}
      {!grid && !loading && <EmptyState title="No forecast" body="No risk data." />}

      {grid && (
        <>
          <section className="stats-grid">
            <StatCard label="Area at risk" value={`${grid.summary.area_at_risk_km2} km²`} hint={`High cells: ${grid.summary.high_cells}`} accent="#ff3b5c" icon="▦" />
            <StatCard label="People exposed" value={formatNumber(grid.summary.people_exposed)} hint={`Mean risk ${Math.round(grid.summary.mean_risk * 100)}%`} accent="#ffd23f" icon="◉" />
            <StatCard label="Lead time" value={`T+${horizon}h`} hint="Forecast horizon" accent="#4aa8ff" icon="◷" />
            <StatCard label="Model accuracy" value={metrics ? `${Math.round(metrics.accuracy * 100)}%` : "—"} hint={metrics ? `AUC ${metrics.roc_auc}` : ""} accent="#39d98a" icon="✓" />
          </section>

          <section className="dashboard-grid">
            <div className="panel panel--map">
              <div className="panel__head"><h2 className="panel__title">Risk Heatmap ({model.toUpperCase()}, T+{horizon}h)</h2><span className="panel__hint">opacity via layer control · legend below</span></div>
              <div className="map-wrap"><ZoneMap markers={markers} heat={heat} height="420px" /></div>
              <div className="chips" style={{ marginTop: 10 }}>
                <span className="chip"><span style={{ background: "#ff3b5c", width: 12, height: 12, borderRadius: 3, display: "inline-block" }} /> Critical ≥75%</span>
                <span className="chip"><span style={{ background: "#ffd23f", width: 12, height: 12, borderRadius: 3, display: "inline-block" }} /> High ≥55%</span>
                <span className="chip"><span style={{ background: "#4aa8ff", width: 12, height: 12, borderRadius: 3, display: "inline-block" }} /> Medium ≥35%</span>
                <span className="chip"><span style={{ background: "#39d98a", width: 12, height: 12, borderRadius: 3, display: "inline-block" }} /> Low</span>
                <span className="chip">Uncertainty low {Math.round((grid.uncertainty?.low_rain || 0) * 100)}% · base {Math.round((grid.uncertainty?.base || 0) * 100)}% · high {Math.round((grid.uncertainty?.high_rain || 0) * 100)}%</span>
              </div>
            </div>
            <div className="panel">
              <div className="panel__head"><h2 className="panel__title">Likely Affected Next</h2><span className="panel__hint">{zones?.zones?.length || 0} zones</span></div>
              <div className="queue">
                {(zones?.zones || []).map((z, i) => (
                  <Link key={z.zone_id} to={`/zones/${z.zone_id}`} className="queue__item">
                    <div className="queue__rank">{i + 1}</div>
                    <div className="queue__body">
                      <div className="queue__row"><span className="queue__name">{z.zone_name}</span><PriorityBadge level={z.risk_level} score={z.probability * 100} compact /></div>
                      <div className="queue__meta"><span>conf {Math.round(z.confidence * 100)}%</span><span>·</span><span>{z.top_factors.join(", ")}</span></div>
                      <div className="queue__meta"><span>{z.reason}</span></div>
                      <div className="queue__meta"><span>Pop exposed {formatNumber(z.population_exposed)}</span><span>·</span><span>Shelter {z.nearest_shelter_km} km</span></div>
                    </div>
                  </Link>
                ))}
              </div>
            </div>
          </section>

          <section className="dashboard-grid">
            <div className="panel">
              <div className="panel__head"><h2 className="panel__title">Model Performance</h2><span className="panel__hint">held-out EVT-09/10</span></div>
              {metrics && (
                <div className="chips">
                  <span className="chip">Accuracy <strong>{metrics.accuracy}</strong></span>
                  <span className="chip">Precision <strong>{metrics.precision}</strong></span>
                  <span className="chip">Recall <strong>{metrics.recall}</strong></span>
                  <span className="chip">ROC-AUC <strong>{metrics.roc_auc}</strong></span>
                  <span className="chip">CM <strong>{JSON.stringify(metrics.confusion_matrix)}</strong></span>
                </div>
              )}
              {metrics?.feature_importances && (
                <ul style={{ listStyle: "none", padding: 0, margin: "12px 0 0", display: "flex", flexDirection: "column", gap: 6 }}>
                  {Object.entries(metrics.feature_importances).sort((a, b) => b[1] - a[1]).slice(0, 6).map(([f, v]) => (
                    <li key={f} style={{ display: "flex", justifyContent: "space-between", fontSize: 12 }}><span>{f}</span><strong>{v}</strong></li>
                  ))}
                </ul>
              )}
              <div className="muted" style={{ marginTop: 10 }}>Default ML: higher recall + probabilistic output + importances. Rule stays for full explainability. {metrics?.why_default || ""}</div>
            </div>
            <div className="panel">
              <div className="panel__head"><h2 className="panel__title">Model Card + Backtest</h2></div>
              {backtest && <div className="chips"><span className="chip">{backtest.event} ({backtest.year})</span><span className="chip">Pred <strong>{backtest.predicted_cells}</strong> vs actual <strong>{backtest.actual_cells}</strong></span><span className="chip">IoU <strong>{backtest.iou}</strong></span><span className="chip">Acc <strong>{backtest.accuracy}</strong></span></div>}
              <div className="muted" style={{ marginTop: 10 }}>Data: simulated historical EVT-01..10, synthetic DEM/rivers/pop, cached Open-Meteo rainfall, live CV+sensors. Method: L1 rule (rainfall×elevation×river×slope×trend) + L2 RandomForest(120→160 trees, seed 20261014, split by event). Limits: simulated, 28×32 cells, first call slow then cached.</div>
              {alloc && <div className="chips" style={{ marginTop: 10 }}><span className="chip">Allocation [{alloc.target}]</span><span className="chip">Assigned <strong>{alloc.total ?? alloc.assignments?.length}</strong></span><span className="chip">Unserved <strong>{alloc.unserved_zones}</strong></span><span className="chip">Util <strong>{alloc.utilisation_pct}%</strong></span></div>}
            </div>
          </section>
        </>
      )}
    </>
  );
}
