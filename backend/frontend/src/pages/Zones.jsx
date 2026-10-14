import { useCallback, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import { useApi } from "../hooks/useApi";
import { PageHeader } from "../components/Layout";
import PriorityBadge from "../components/PriorityBadge";
import { EmptyState, ErrorState, Loading } from "../components/StateViews";
import { humanize, statusColor } from "../lib/format";

export default function Zones() {
  const zonesFn = useCallback(() => api.listZones(), []);
  const analysisFn = useCallback(() => api.analyzeAll(), []);
  const zones = useApi(zonesFn, []);
  const analysis = useApi(analysisFn, []);
  const [status, setStatus] = useState("all");
  const [query, setQuery] = useState("");

  const analysisByZone = useMemo(() => {
    const map = {};
    (analysis.data?.results || []).forEach((r) => {
      map[r.zone_id] = r;
    });
    return map;
  }, [analysis.data]);

  const statuses = useMemo(() => {
    const set = new Set((zones.data || []).map((z) => z.status));
    return ["all", ...Array.from(set)];
  }, [zones.data]);

  const filtered = useMemo(() => {
    const list = zones.data || [];
    return list.filter((z) => {
      const statusOk = status === "all" || z.status === status;
      const queryOk = !query || z.name.toLowerCase().includes(query.toLowerCase());
      return statusOk && queryOk;
    });
  }, [zones.data, status, query]);

  const refresh = () => {
    zones.refetch();
    analysis.refetch();
  };

  return (
    <>
      <PageHeader
        title="Disaster Zones"
        subtitle="Flood-affected areas and their live condition"
        actions={
          <button type="button" className="btn" onClick={refresh} disabled={zones.loading}>
            {zones.loading ? "Refreshing…" : "Refresh"}
          </button>
        }
      />

      <div className="toolbar">
        <input
          type="search"
          className="input"
          placeholder="Search zones…"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
        <div className="segmented">
          {statuses.map((s) => (
            <button
              key={s}
              type="button"
              className={`segmented__btn ${status === s ? "is-active" : ""}`}
              onClick={() => setStatus(s)}
            >
              {s === "all" ? "All" : humanize(s)}
            </button>
          ))}
        </div>
      </div>

      {zones.loading && !zones.data ? (
        <Loading label="Loading zones…" />
      ) : zones.error && !zones.data ? (
        <ErrorState error={zones.error} onRetry={refresh} label="Could not load zones" />
      ) : !filtered.length ? (
        <EmptyState title="No zones match" body="Try a different filter or search term." />
      ) : (
        <div className="zone-grid">
          {filtered.map((z) => {
            const a = analysisByZone[z.id];
            return (
              <Link key={z.id} to={`/zones/${z.id}`} className="zone-card">
                <div className="zone-card__head">
                  <h3 className="zone-card__name">{z.name}</h3>
                  <span
                    className="zone-card__status"
                    style={{ color: statusColor(z.status), borderColor: `${statusColor(z.status)}55` }}
                  >
                    {humanize(z.status)}
                  </span>
                </div>

                <div className="zone-card__badge">
                  {a ? (
                    <PriorityBadge level={a.priority_level} score={a.priority_score} />
                  ) : (
                    <span className="muted">No analysis</span>
                  )}
                </div>

                <dl className="zone-card__stats">
                  <div>
                    <dt>Flood severity</dt>
                    <dd>{Math.round(z.flood_severity)}</dd>
                  </div>
                  <div>
                    <dt>Aerial damage</dt>
                    <dd>{Math.round(z.aerial_damage_score)}</dd>
                  </div>
                  <div>
                    <dt>Exposure</dt>
                    <dd>{Math.round(z.population_exposure)}</dd>
                  </div>
                  <div>
                    <dt>Shelter</dt>
                    <dd>{z.shelter_distance_km} km</dd>
                  </div>
                </dl>

                {a?.recommended_action && (
                  <div className="zone-card__action">{a.recommended_action}</div>
                )}
              </Link>
            );
          })}
        </div>
      )}
    </>
  );
}
