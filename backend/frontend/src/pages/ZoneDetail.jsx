import { useCallback, useMemo } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../api/client";
import { useApi } from "../hooks/useApi";
import PriorityBadge from "../components/PriorityBadge";
import MetricBar from "../components/MetricBar";
import ZoneMap from "../components/ZoneMap";
import RiskChart from "../components/RiskChart";
import { ErrorState, Loading } from "../components/StateViews";
import { PageHeader } from "../components/Layout";
import {
  formatDateTime,
  humanize,
  priorityColor,
  severityColor,
  statusColor,
} from "../lib/format";

export default function ZoneDetail() {
  const { zoneId } = useParams();

  const zoneFn = useCallback(() => api.getZone(zoneId), [zoneId]);
  const analysisFn = useCallback(() => api.analyzeZone(zoneId), [zoneId]);
  const weatherFn = useCallback(() => api.getWeather(zoneId), [zoneId]);
  const explainFn = useCallback(() => api.explainZone(zoneId), [zoneId]);
  const sosFn = useCallback(() => api.listSos(zoneId), [zoneId]);
  const forecastFn = useCallback(() => api.getForecast(zoneId), [zoneId]);
  const historyFn = useCallback(() => api.getZoneHistory(zoneId), [zoneId]);

  const zone = useApi(zoneFn, [zoneId]);
  const analysis = useApi(analysisFn, [zoneId]);
  const weather = useApi(weatherFn, [zoneId]);
  const explanation = useApi(explainFn, [zoneId]);
  const sos = useApi(sosFn, [zoneId]);
  const forecast = useApi(forecastFn, [zoneId]);
  const history = useApi(historyFn, [zoneId]);

  const a = analysis.data;

  const markers = useMemo(() => {
    const z = zone.data;
    if (!z) return [];
    return [
      {
        id: z.id,
        name: z.name,
        lat: z.latitude,
        lng: z.longitude,
        color: a ? priorityColor(a.priority_level) : statusColor(z.status),
        radius: a ? 8 + (a.priority_score / 100) * 14 : 12,
        subtitle: a ? `Priority ${Math.round(a.priority_score)} · ${a.priority_level}` : z.status,
      },
    ];
  }, [zone.data, a]);

  if (zone.loading && !zone.data) return <Loading label="Loading zone…" />;
  if (zone.error && !zone.data) {
    return (
      <>
        <PageHeader title="Zone" subtitle={zoneId} />
        <ErrorState error={zone.error} onRetry={zone.refetch} label="Could not load zone" />
        <Link to="/zones" className="btn btn--ghost">
          ← Back to zones
        </Link>
      </>
    );
  }

  const z = zone.data;

  return (
    <>
      <div className="breadcrumb">
        <Link to="/zones">Zones</Link> <span>/</span> <span>{z?.name || zoneId}</span>
      </div>

      <PageHeader
        title={z?.name || zoneId}
        subtitle={`${humanize(z?.disaster_type)} · Last updated ${formatDateTime(z?.last_updated)}`}
        actions={
          <div className="detail-actions">
            {z && (
              <span
                className="zone-status-pill"
                style={{ color: statusColor(z.status), borderColor: `${statusColor(z.status)}55` }}
              >
                {humanize(z.status)}
              </span>
            )}
            <button
              type="button"
              className="btn"
              onClick={() => {
                analysis.refetch();
                weather.refetch();
                explanation.refetch();
                sos.refetch();
                forecast.refetch();
                history.refetch();
              }}
            >
              Refresh
            </button>
          </div>
        }
      />

      <div className="detail-grid">
        <section className="panel panel--priority">
          <div className="panel__head">
            <h2 className="panel__title">Priority Assessment</h2>
          </div>
          {analysis.loading && !a && <Loading />}
          {analysis.error && !a && (
            <ErrorState error={analysis.error} onRetry={analysis.refetch} label="Analysis unavailable" />
          )}
          {a && (
            <>
              <div className="priority-hero">
                <div className="priority-hero__score" style={{ color: priorityColor(a.priority_level) }}>
                  {Math.round(a.priority_score)}
                  <span>/100</span>
                </div>
                <PriorityBadge level={a.priority_level} />
              </div>

              <div className="field">
                <div className="field__label">Recommended action</div>
                <div className="field__value">{a.recommended_action}</div>
              </div>

              <div className="field">
                <div className="field__label">Contributing factors</div>
                <ul className="factor-list">
                  {(a.contributing_factors || []).map((f, i) => (
                    <li key={i}>{f}</li>
                  ))}
                  {!(a.contributing_factors || []).length && <li className="muted">None reported</li>}
                </ul>
              </div>

              <div className="field-row">
                <div className="field">
                  <div className="field__label">Active SOS</div>
                  <div className="field__value">{a.active_sos_count}</div>
                </div>
                <div className="field">
                  <div className="field__label">Weather summary</div>
                  <div className="field__value field__value--sm">{a.weather_summary}</div>
                </div>
              </div>
            </>
          )}
        </section>

        <section className="panel">
          <div className="panel__head">
            <h2 className="panel__title">AI Explanation</h2>
            {explanation.data && (
              <span className="tag">{humanize(explanation.data.source)}</span>
            )}
          </div>
          {explanation.loading && !explanation.data && <Loading />}
          {explanation.error && !explanation.data && (
            <div className="muted">Explanation unavailable for this zone.</div>
          )}
          {explanation.data && (
            <>
              <p className="explanation">{explanation.data.explanation}</p>
              <div className="explanation-meta">
                <span className={`flag ${explanation.data.used_llm ? "flag--on" : ""}`}>
                  LLM {explanation.data.used_llm ? "used" : "not used"}
                </span>
                {explanation.data.fallback_used && <span className="flag flag--warn">Fallback</span>}
              </div>
            </>
          )}
        </section>

        <section className="panel">
          <div className="panel__head">
            <h2 className="panel__title">Zone Metrics</h2>
          </div>
          {z && (
            <div className="metrics">
              <MetricBar label="Flood severity" value={z.flood_severity} color="#4aa8ff" />
              <MetricBar label="Aerial damage" value={z.aerial_damage_score} color="#ff8a3d" />
              <MetricBar label="Population exposure" value={z.population_exposure} color="#ffd23f" />
              <MetricBar label="Road access difficulty" value={z.road_access_difficulty} color="#ff3b5c" />
              <MetricBar
                label="Base weather risk"
                value={z.base_weather_risk}
                color="#a78bfa"
              />
              <MetricBar
                label="Shelter distance"
                value={z.shelter_distance_km}
                max={6}
                unit=" km"
                color="#39d98a"
              />
            </div>
          )}
        </section>

        <section className="panel">
          <div className="panel__head">
            <h2 className="panel__title">Weather</h2>
            {weather.data && <span className="tag">{weather.data.source}</span>}
          </div>
          {weather.loading && !weather.data && <Loading />}
          {weather.error && !weather.data && (
            <div className="muted">Weather data unavailable; using base risk only.</div>
          )}
          {weather.data && (
            <>
              <div className="weather-grid">
                <div>
                  <div className="field__label">Condition</div>
                  <div className="field__value">{humanize(weather.data.weather_condition)}</div>
                </div>
                <div>
                  <div className="field__label">Rainfall</div>
                  <div className="field__value">{weather.data.rainfall_mm} mm</div>
                </div>
                <div>
                  <div className="field__label">Wind</div>
                  <div className="field__value">{weather.data.wind_speed_kmh} km/h</div>
                </div>
              </div>
              <MetricBar
                label="Weather risk score"
                value={weather.data.weather_risk_score}
                color="#a78bfa"
              />
              {weather.data.status_message && (
                <div className="muted">{weather.data.status_message}</div>
              )}
              <div className="muted">Fetched {formatDateTime(weather.data.fetched_at)}</div>
            </>
          )}
        </section>

        <section className="panel panel--wide">
          <div className="panel__head">
            <h2 className="panel__title">24-Hour Risk Forecast</h2>
            {forecast.data && <span className="tag">{forecast.data.source}</span>}
          </div>
          {forecast.loading && !forecast.data && <Loading />}
          {forecast.error && !forecast.data && (
            <div className="muted">Forecast unavailable for this zone.</div>
          )}
          {forecast.data && (
            <>
              <RiskChart
                points={(forecast.data.points || []).map((p) => ({ t: p.timestamp, value: p.risk_projection }))}
                color="#ff8a3d"
                unit=" risk"
                max={100}
              />
              <div className="fc-table">
                {(forecast.data.points || []).slice(0, 4).map((p) => (
                  <div key={p.timestamp} className="fc-table__row">
                    <span>{formatDateTime(p.timestamp)}</span>
                    <span>☔ {p.expected_rainfall_mm} mm</span>
                    <span>≈ {p.expected_wind_kmh} km/h</span>
                    <strong style={{ color: priorityColor(p.risk_projection >= 66 ? "Critical" : p.risk_projection >= 40 ? "High" : "Low") }}>
                      Risk {Math.round(p.risk_projection)}
                    </strong>
                  </div>
                ))}
              </div>
            </>
          )}
        </section>

        <section className="panel panel--wide">
          <div className="panel__head">
            <h2 className="panel__title">7-Day History</h2>
            {history.data && <span className="tag">{history.data.source}</span>}
          </div>
          {history.loading && !history.data && <Loading />}
          {history.error && !history.data && (
            <div className="muted">History unavailable for this zone.</div>
          )}
          {history.data && (
            <>
              <RiskChart
                points={(history.data.points || []).map((p) => ({ t: p.timestamp, value: p.water_level }))}
                color="#4aa8ff"
                unit=" water level"
                max={100}
              />
              <RiskChart
                points={(history.data.points || []).map((p) => ({ t: p.timestamp, value: p.rainfall_mm }))}
                color="#39d98a"
                unit=" mm"
              />
            </>
          )}
        </section>

        <section className="panel">
          <div className="panel__head">
            <h2 className="panel__title">Location</h2>
          </div>
          <div className="map-wrap map-wrap--sm">
            <ZoneMap markers={markers} height="260px" />
          </div>
        </section>

        <section className="panel panel--wide">
          <div className="panel__head">
            <h2 className="panel__title">SOS Reports in this Zone</h2>
            <span className="panel__hint">{sos.data?.length ?? 0} total</span>
          </div>
          {sos.loading && !sos.data && <Loading />}
          {sos.error && !sos.data && <div className="muted">SOS reports unavailable.</div>}
          {sos.data && (
            <div className="sos-list">
              {sos.data.map((r) => (
                <div key={r.id} className="sos-card">
                  <div
                    className="sos-card__sev"
                    style={{ background: severityColor(r.severity) }}
                  >
                    SEV {r.severity}
                  </div>
                  <div className="sos-card__body">
                    <div className="sos-card__title">{humanize(r.emergency_type)}</div>
                    <div className="sos-card__desc">{r.description}</div>
                    <div className="sos-card__meta">
                      <span>{r.reporter_name || "Anonymous"}</span>
                      <span>· {r.people_affected} affected</span>
                      <span>· {formatDateTime(r.created_at)}</span>
                    </div>
                  </div>
                </div>
              ))}
              {!sos.data.length && <div className="muted">No reports for this zone.</div>}
            </div>
          )}
        </section>
      </div>
    </>
  );
}
