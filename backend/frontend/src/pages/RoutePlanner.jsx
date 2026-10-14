import { useCallback, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import { useApi } from "../hooks/useApi";
import { PageHeader } from "../components/Layout";
import ZoneMap from "../components/ZoneMap";
import PriorityBadge from "../components/PriorityBadge";
import { ErrorState } from "../components/StateViews";
import { formatDateTime, formatNumber, priorityColor } from "../lib/format";

const DEFAULT_START = { lat: 12.9716, lng: 77.5946 };

export default function RoutePlanner() {
  const zonesFn = useCallback(() => api.listZones(), []);
  const zones = useApi(zonesFn, []);

  const [start, setStart] = useState(DEFAULT_START);
  const [maxZones, setMaxZones] = useState(3);
  const [route, setRoute] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const zoneMarkers = useMemo(
    () =>
      (zones.data || []).map((z) => ({
        id: z.id,
        name: z.name,
        lat: z.latitude,
        lng: z.longitude,
        color: "#7c8aa5",
        radius: 6,
        subtitle: z.status,
      })),
    [zones.data],
  );

  const routeMarkers = useMemo(() => {
    if (!route?.ordered_stops) return zoneMarkers;
    const stopIds = new Set();
    const stops = route.ordered_stops.map((s, i) => {
      stopIds.add(s.zone_id);
      return {
        id: s.zone_id,
        name: `${i + 1}. ${s.zone_name}`,
        lat: s.latitude,
        lng: s.longitude,
        color: priorityColor(s.priority_level),
        radius: 10,
        subtitle: `Priority ${Math.round(s.priority_score)} · ${s.priority_level}`,
        href: `/zones/${s.zone_id}`,
      };
    });
    const rest = zoneMarkers.filter((z) => !stopIds.has(z.id));
    return [...stops, ...rest];
  }, [route, zoneMarkers]);

  const routeLine = useMemo(
    () =>
      (route?.ordered_stops || []).map((s) => ({
        lat: s.latitude,
        lng: s.longitude,
        label: s.zone_name,
      })),
    [route],
  );

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError(null);
    setLoading(true);
    try {
      const data = await api.planRoute({
        drone_start_latitude: Number(start.lat),
        drone_start_longitude: Number(start.lng),
        max_zones: Number(maxZones),
      });
      setRoute(data);
    } catch (err) {
      setError(err);
      setRoute(null);
    } finally {
      setLoading(false);
    }
  };

  const useZoneAsStart = (e) => {
    const zone = (zones.data || []).find((z) => z.id === e.target.value);
    if (zone) setStart({ lat: zone.latitude, lng: zone.longitude });
  };

  return (
    <>
      <PageHeader
        title="Drone Route Planner"
        subtitle="Distance-aware inspection route ranked by zone priority"
      />

      <div className="route-layout">
        <section className="panel">
          <div className="panel__head">
            <h2 className="panel__title">Route Parameters</h2>
          </div>
          <form className="form" onSubmit={handleSubmit}>
            <label className="form__field">
              <span>Quick start</span>
              <select className="input" defaultValue="" onChange={useZoneAsStart}>
                <option value="">Choose a zone to launch from…</option>
                {(zones.data || []).map((z) => (
                  <option key={z.id} value={z.id}>
                    {z.name}
                  </option>
                ))}
              </select>
            </label>

            <div className="form__row">
              <label className="form__field">
                <span>Start latitude</span>
                <input
                  className="input"
                  type="number"
                  step="any"
                  value={start.lat}
                  onChange={(e) => setStart((s) => ({ ...s, lat: e.target.value }))}
                  required
                />
              </label>
              <label className="form__field">
                <span>Start longitude</span>
                <input
                  className="input"
                  type="number"
                  step="any"
                  value={start.lng}
                  onChange={(e) => setStart((s) => ({ ...s, lng: e.target.value }))}
                  required
                />
              </label>
            </div>

            <label className="form__field">
              <span>Max zones to visit: {maxZones}</span>
              <input
                type="range"
                min="1"
                max="10"
                value={maxZones}
                onChange={(e) => setMaxZones(e.target.value)}
              />
            </label>

            <button type="submit" className="btn btn--primary" disabled={loading}>
              {loading ? "Planning…" : "Generate route"}
            </button>
          </form>

          {error && <ErrorState error={error} label="Route planning failed" />}

          {route && (
            <div className="route-summary">
              <div className="route-summary__stats">
                <div>
                  <div className="field__label">Total distance</div>
                  <div className="field__value">
                    {formatNumber(route.total_estimated_distance_km, 1)} km
                  </div>
                </div>
                <div>
                  <div className="field__label">Stops</div>
                  <div className="field__value">{route.ordered_stops.length}</div>
                </div>
              </div>
              <div className="field">
                <div className="field__label">Route rationale</div>
                <div className="field__value field__value--sm">{route.route_reason}</div>
              </div>
              <div className="muted">Generated {formatDateTime(route.generated_at)}</div>
            </div>
          )}
        </section>

        <section className="panel panel--map">
          <div className="panel__head">
            <h2 className="panel__title">Route Map</h2>
          </div>
          <div className="map-wrap">
            <ZoneMap
              markers={routeMarkers}
              route={routeLine}
              start={{ lat: Number(start.lat), lng: Number(start.lng) }}
              height="360px"
            />
          </div>

          {route && (
            <ol className="route-stops">
              {route.ordered_stops.map((s) => (
                <li key={s.zone_id} className="route-stop">
                  <span
                    className="route-stop__seq"
                    style={{ background: priorityColor(s.priority_level) }}
                  >
                    {s.sequence}
                  </span>
                  <div className="route-stop__body">
                    <Link to={`/zones/${s.zone_id}`} className="route-stop__name">
                      {s.zone_name}
                    </Link>
                    <div className="route-stop__meta">
                      <span>{formatNumber(s.distance_from_previous_km, 1)} km from previous</span>
                    </div>
                  </div>
                  <PriorityBadge level={s.priority_level} score={s.priority_score} compact />
                </li>
              ))}
            </ol>
          )}
        </section>
      </div>
    </>
  );
}
