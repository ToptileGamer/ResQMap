import { useCallback, useMemo, useRef } from "react";
import { Link } from "react-router-dom";
import L from "leaflet";
import { api } from "../api/client";
import { useApi } from "../hooks/useApi";
import { PageHeader } from "../components/Layout";
import StatCard from "../components/StatCard";
import PriorityBadge from "../components/PriorityBadge";
import ZoneMap from "../components/ZoneMap";
import LayerPanel from "../components/LayerPanel";
import ExportDropdown from "../components/ExportDropdown";
import { EmptyState, ErrorState, Loading } from "../components/StateViews";
import { useGISLayers } from "../lib/use-gis-layers";
import {
  formatNumber,
  formatRelative,
  priorityColor,
  sortByPriority,
  statusColor,
} from "../lib/format";

export default function Dashboard() {
  const { layers, visibleLayers, fetchState, loadOnIdle, toggleLayer, setAllVisible, opacityFor, opacities, resetLayers, bounds } = useGISLayers();
  const mapRef = useRef(null);
  const zonesFn = useCallback(() => api.listZones(), []);
  const analysisFn = useCallback(() => api.analyzeAll(), []);
  const hazardFn = useCallback(() => api.getHazardZones(), []);
  const hazardDashboardFn = useCallback(() => api.getHazardDashboard(), []);
  const sosFn = useCallback(() => api.listSos(), []);

  const zones = useApi(zonesFn, []);
  const analysis = useApi(analysisFn, []);
  const hazard = useApi(hazardFn, []);
  const hazardDashboard = useApi(hazardDashboardFn, []);
  const sos = useApi(sosFn, []);

  const results = useMemo(
    () => [...(analysis.data?.results || [])].sort(sortByPriority),
    [analysis.data],
  );

  const analysisByZone = useMemo(() => {
    const map = {};
    (analysis.data?.results || []).forEach((r) => {
      map[r.zone_id] = r;
    });
    return map;
  }, [analysis.data]);

  const markers = useMemo(() => {
    const zoneList = zones.data || [];
    return zoneList.map((z) => {
      const a = analysisByZone[z.id];
      const level = a?.priority_level;
      return {
        id: z.id,
        name: z.name,
        lat: z.latitude,
        lng: z.longitude,
        color: level ? priorityColor(level) : statusColor(z.status),
        radius: a ? 8 + (a.priority_score / 100) * 12 : 8,
        subtitle: a
          ? `Priority ${Math.round(a.priority_score)} · ${level}`
          : `Status: ${z.status}`,
        href: `/zones/${z.id}`,
      };
    });
  }, [zones.data, analysisByZone]);

  const heat = useMemo(() => {
    const zoneList = zones.data || [];
    return zoneList
      .map((z) => {
        const a = analysisByZone[z.id];
        return [z.latitude, z.longitude, a ? a.priority_score / 100 : 0.3];
      })
      .filter(([, , intensity]) => intensity > 0.05);
  }, [zones.data, analysisByZone]);

  const activeSos = sos.data?.length ?? 0;
  const totalAffected = (sos.data || []).reduce(
    (sum, r) => sum + (r.people_affected || 0),
    0,
  );

  const refreshAll = () => {
    zones.refetch();
    analysis.refetch();
    sos.refetch();
  };

  const onLayersChange = useCallback((nextLayers) => {
    if (nextLayers.length === 0) {
      resetLayers();
    } else {
      setAllVisible(nextLayers);
    }
  }, [resetLayers, setAllVisible]);

  const onLayerOpacityChange = useCallback((layerType, opacity) => {
    opacityFor(layerType, opacity);
  }, [opacityFor]);

  const onLayerFocus = useCallback((layer, map) => {
    if (!map) return;
    const geo = layer.geojson;
    if (!geo || !geo.features?.length) return;
    try {
      const bounds = map.fitBounds(L.geoJSON(geo).getBounds(), { padding: [40, 40] });
      map.getZoom && map.setView(bounds.getCenter(), Math.max(map.getZoom(), 13));
    } catch {
      // ignore invalid GeoJSON
    }
  }, []);

  const onLayerClick = useCallback(({ layerType, feature }) => {
    // Could route to a detail page or open a side drawer; for now logged.
    console.log("[ZoneMap] Layer feature clicked", layerType, feature?.properties);
  }, []);

  const layerOpacities = opacities;

  const loadingInitial = zones.loading && analysis.loading && !zones.data && !analysis.data;
  const anyError = zones.error && analysis.error;

  return (
    <>
      <PageHeader
        title="Operations Dashboard"
        subtitle="Prioritized flood-response zones for drone inspection"
        updatedAt={analysis.data?.generated_at}
        actions={
          <>
            <ExportDropdown />
            <button
              type="button"
              className="btn"
              onClick={refreshAll}
              disabled={analysis.loading}
            >
              {analysis.loading ? "Refreshing…" : "Refresh"}
            </button>
          </>
        }
      />

      {loadingInitial ? (
        <Loading label="Loading situation overview…" />
      ) : anyError && !zones.data ? (
        <ErrorState error={zones.error} onRetry={refreshAll} label="Could not load zones" />
      ) : (
        <>
          <section className="stats-grid">
            <StatCard
              label="Zones monitored"
              value={formatNumber(zones.data?.length ?? analysis.data?.total_zones ?? 0)}
              hint="Active flood watch areas"
              accent="#4aa8ff"
              icon="▦"
            />
            <StatCard
              label="Critical"
              value={formatNumber(analysis.data?.critical_count ?? 0)}
              hint="Immediate drone dispatch"
              accent="#ff3b5c"
              icon="!"
            />
            <StatCard
              label="High priority"
              value={formatNumber(analysis.data?.high_count ?? 0)}
              hint="Next inspection wave"
              accent="#ff8a3d"
              icon="▲"
            />
            <StatCard
              label="Citizen SOS"
              value={formatNumber(activeSos)}
              hint={`${formatNumber(totalAffected)} people affected`}
              accent="#ffd23f"
              icon="◉"
            />
          </section>

          <section className="dashboard-grid">
            <div className="panel panel--map">
              <div className="panel__head">
                <h2 className="panel__title">Live Zone Map</h2>
                <span className="panel__hint">
                  {analysis.data ? "Colored by priority score" : "Colored by zone status"}
                </span>
              </div>
              <div className="map-wrap map-wrap--panel">
                <div className="map-with-panel">
                  <div className="map-col">
                    <ZoneMap
                      ref={mapRef}
                      markers={markers}
                      heat={heat}
                      height="440px"
                      layers={visibleLayers}
                      layerOpacities={layerOpacities}
                      onLayerClick={onLayerClick}
                    />
                  </div>
                  <div className="panel-col">
                    <LayerPanel
                      layers={layers}
                      visible={new Set(visibleLayers.map((l) => l.layer_type))}
                      opacities={layerOpacities}
                      fetchState={fetchState}
                      onToggle={onLayersChange}
                      onOpacityChange={onLayerOpacityChange}
                      onFocusBounds={onLayerFocus}
                    />
                  </div>
                </div>
              </div>
              {analysis.error && (
                <div className="panel__note">
                  Priority analysis unavailable — showing zone status instead.
                </div>
              )}
            </div>

            <div className="panel">
              <div className="panel__head">
                <h2 className="panel__title">Priority Queue</h2>
                <span className="panel__hint">{results.length} analyzed</span>
              </div>
              <div className="queue">
                {analysis.loading && !results.length && <Loading label="Ranking zones…" />}
                {!analysis.loading && analysis.error && !results.length && (
                  <ErrorState
                    error={analysis.error}
                    onRetry={analysis.refetch}
                    label="Analysis unavailable"
                  />
                )}
                {!analysis.loading && !analysis.error && !results.length && (
                  <EmptyState title="No analysis results" body="The backend returned no zones." />
                )}
                {results.map((r, index) => (
                  <Link key={r.zone_id} to={`/zones/${r.zone_id}`} className="queue__item">
                    <div className="queue__rank">{index + 1}</div>
                    <div className="queue__body">
                      <div className="queue__row">
                        <span className="queue__name">{r.zone_name}</span>
                        <PriorityBadge level={r.priority_level} score={r.priority_score} compact />
                      </div>
                      <div className="queue__meta">
                        <span>◉ {r.active_sos_count} SOS</span>
                        <span>·</span>
                        <span>{r.contributing_factors?.[0] || "—"}</span>
                      </div>
                    </div>
                  </Link>
                ))}
              </div>
            </div>
          </section>

          <section className="dashboard-grid">
            <div className="panel">
              <div className="panel__head">
                <h2 className="panel__title">Hazard Severity (CV + Sensor + GIS)</h2>
                <span className="panel__hint">Fused multi-source ranking</span>
              </div>
              <div className="queue">
                {hazard.loading && !hazard.data && <Loading label="Computing hazard severity…" />}
                {!hazard.loading && hazard.error && !hazard.data && (
                  <ErrorState error={hazard.error} onRetry={hazard.refetch} label="Hazard unavailable" />
                )}
                {!hazard.loading && !hazard.error && !hazard.data?.zones?.length && (
                  <EmptyState title="No hazard data" body="No zones returned." />
                )}
                {hazard.data?.zones?.map((z, index) => (
                  <Link key={z.id} to={`/zones/${z.id}`} className="queue__item">
                    <div className="queue__rank">{index + 1}</div>
                    <div className="queue__body">
                      <div className="queue__row">
                        <span className="queue__name">{z.name}</span>
                        <PriorityBadge level={z.severity} score={z.score} compact />
                      </div>
                      <div className="queue__meta">
                        <span>CV: {z.cv_flood_pct}</span>
                        <span>·</span>
                        <span>Sensor: {z.sensor_alerts} alerts</span>
                        <span>·</span>
                        <span>GIS: {z.gis_risk_factors?.[0] || "—"}</span>
                      </div>
                    </div>
                  </Link>
                ))}
              </div>
            </div>

            {hazardDashboard.data && (
              <div className="panel">
                <div className="panel__head">
                  <h2 className="panel__title">Hazard Summary</h2>
                  <span className="panel__hint">Updated {new Date(hazardDashboard.data.generated_at).toLocaleTimeString()}</span>
                </div>
                <div className="stats-grid stats-grid--compact">
                  <StatCard label="Affected Area" value={`${hazardDashboard.data.affected_area_km2} km²`} hint="Sum of zone areas" accent="#ff3b5c" icon="▦" />
                  <StatCard label="People at Risk" value={formatNumber(hazardDashboard.data.people_at_risk)} hint="Population exposure" accent="#ffd23f" icon="◉" />
                  <StatCard label="Assets at Risk" value={formatNumber(hazardDashboard.data.assets_at_risk)} hint="Infrastructure proxy" accent="#ff8a3d" icon="◆" />
                  <StatCard label="Sensors in Alert" value={formatNumber(hazardDashboard.data.sensors_in_alert)} hint="Live sensor alerts" accent="#4aa8ff" icon="▲" />
                  <StatCard label="Critical Zones" value={formatNumber(hazardDashboard.data.critical_zones)} hint="Immediate action needed" accent="#ff3b5c" icon="!" />
                  <StatCard label="High Zones" value={formatNumber(hazardDashboard.data.high_zones)} hint="Next inspection wave" accent="#ffd23f" icon="▲" />
                </div>

                {hazardDashboard.data.alert_breakdown && Object.keys(hazardDashboard.data.alert_breakdown).length > 0 && (
                  <div className="panel__section" style={{marginTop: 16}}>
                    <h3 className="panel__subtitle" style={{fontSize: 12, color: 'var(--text-mute)', marginBottom: 8, textTransform: 'uppercase', letterSpacing: '0.04em'}}>Sensor Alerts by Type</h3>
                    <div className="chips">
                      {Object.entries(hazardDashboard.data.alert_breakdown).map(([type, count]) => (
                        <span key={type} className="chip">
                          {type.replace(/_/g, ' ')}
                          <strong>{count}</strong>
                        </span>
                      ))}
                    </div>
                  </div>
                )}

                {hazardDashboard.data.severity_distribution && (
                  <div className="panel__section" style={{marginTop: 16}}>
                    <h3 className="panel__subtitle" style={{fontSize: 12, color: 'var(--text-mute)', marginBottom: 8, textTransform: 'uppercase', letterSpacing: '0.04em'}}>Severity Distribution</h3>
                    <div className="chips">
                      {Object.entries(hazardDashboard.data.severity_distribution)
                        .filter(([, count]) => count > 0)
                        .map(([level, count]) => (
                          <span key={level} className="chip" style={{borderColor: `var(--${level.toLowerCase()}, #7c8aa5)`, color: `var(--${level.toLowerCase()}, #e7edf7)`}}>
                            {level}
                            <strong>{count}</strong>
                          </span>
                        ))}
                    </div>
                  </div>
                )}

                {hazardDashboard.data.top_risk_factors && hazardDashboard.data.top_risk_factors.length > 0 && (
                  <div className="panel__section" style={{marginTop: 16}}>
                    <h3 className="panel__subtitle" style={{fontSize: 12, color: 'var(--text-mute)', marginBottom: 8, textTransform: 'uppercase', letterSpacing: '0.04em'}}>Top Risk Factors</h3>
                    <ul style={{listStyle: 'none', padding: 0, margin: 0, display: 'flex', flexDirection: 'column', gap: 6}}>
                      {hazardDashboard.data.top_risk_factors.map((item, idx) => (
                        <li key={idx} style={{display: 'flex', justifyContent: 'space-between', fontSize: 12, color: 'var(--text-dim)'}}>
                          <span>{item.factor}</span>
                          <strong style={{color: 'var(--text)'}}>{item.count} zones</strong>
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
              </div>
            )}
          </section>

          <section className="dashboard-lower">
            <div className="panel">
              <div className="panel__head">
                <h2 className="panel__title">Weather Risk Sources</h2>
              </div>
              {analysis.data?.weather_source_summary &&
              Object.keys(analysis.data.weather_source_summary).length ? (
                <div className="chips">
                  {Object.entries(analysis.data.weather_source_summary).map(([src, count]) => (
                    <span key={src} className="chip">
                      {src}
                      <strong>{count}</strong>
                    </span>
                  ))}
                </div>
              ) : (
                <div className="muted">No weather source summary available.</div>
              )}
            </div>

            <div className="panel">
              <div className="panel__head">
                <h2 className="panel__title">Latest SOS Reports</h2>
                <Link to="/sos" className="panel__link">
                  View all →
                </Link>
              </div>
              <div className="sos-mini">
                {(sos.data || []).slice(0, 4).map((r) => (
                  <div key={r.id} className="sos-mini__item">
                    <div
                      className="sos-mini__sev"
                      style={{ background: `hsl(${Math.max(0, 120 - r.severity * 24)} 80% 55%)` }}
                    >
                      S{r.severity}
                    </div>
                    <div className="sos-mini__body">
                      <div className="sos-mini__title">{r.emergency_type.replace(/_/g, " ")}</div>
                      <div className="sos-mini__desc">{r.description}</div>
                    </div>
                    <div className="sos-mini__time">{formatRelative(r.created_at)}</div>
                  </div>
                ))}
                {!(sos.data || []).length && !sos.loading && (
                  <div className="muted">No SOS reports yet.</div>
                )}
                {sos.error && <div className="muted">SOS feed unavailable.</div>}
              </div>
            </div>
          </section>
        </>
      )}
    </>
  );
}
