import { useCallback, useMemo, useState } from "react";
import { api } from "../api/client";
import { useApi } from "../hooks/useApi";
import { PageHeader } from "../components/Layout";
import { EmptyState, ErrorState, Loading } from "../components/StateViews";
import { formatDateTime, humanize, severityColor } from "../lib/format";

const EMERGENCY_TYPES = [
  "trapped_residents",
  "medical_need",
  "overflow",
  "underpass_flooding",
  "drainage_collapse",
  "food_water",
  "power_outage",
  "other",
];

const EMPTY_FORM = {
  zone_id: "",
  reporter_name: "",
  emergency_type: "trapped_residents",
  severity: 3,
  people_affected: 1,
  description: "",
  latitude: "",
  longitude: "",
};

export default function Sos() {
  const sosFn = useCallback(() => api.listSos(), []);
  const zonesFn = useCallback(() => api.listZones(), []);
  const sos = useApi(sosFn, []);
  const zones = useApi(zonesFn, []);

  const [form, setForm] = useState(EMPTY_FORM);
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState(null);
  const [toast, setToast] = useState(null);
  const [filterZone, setFilterZone] = useState("all");

  const zoneById = useMemo(() => {
    const map = {};
    (zones.data || []).forEach((z) => {
      map[z.id] = z;
    });
    return map;
  }, [zones.data]);

  const reports = useMemo(() => {
    const list = sos.data || [];
    const filtered = filterZone === "all" ? list : list.filter((r) => r.zone_id === filterZone);
    return [...filtered].sort((a, b) => new Date(b.created_at) - new Date(a.created_at));
  }, [sos.data, filterZone]);

  const update = (key) => (e) => {
    const value = e.target.value;
    setForm((prev) => ({ ...prev, [key]: value }));
  };

  const handleZoneChange = (e) => {
    const zoneId = e.target.value;
    const zone = zoneById[zoneId];
    setForm((prev) => ({
      ...prev,
      zone_id: zoneId,
      latitude: zone ? String(zone.latitude) : prev.latitude,
      longitude: zone ? String(zone.longitude) : prev.longitude,
    }));
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    setSubmitError(null);
    setToast(null);

    if (!form.zone_id) {
      setSubmitError("Select a zone for this report.");
      return;
    }
    if (!form.description.trim()) {
      setSubmitError("Describe the emergency.");
      return;
    }

    const payload = {
      zone_id: form.zone_id,
      reporter_name: form.reporter_name.trim() || null,
      emergency_type: form.emergency_type,
      severity: Number(form.severity),
      people_affected: Number(form.people_affected) || 0,
      description: form.description.trim(),
      latitude: form.latitude === "" ? null : Number(form.latitude),
      longitude: form.longitude === "" ? null : Number(form.longitude),
    };

    setSubmitting(true);
    try {
      await api.createSos(payload);
      setToast("SOS report submitted.");
      setForm((prev) => ({ ...EMPTY_FORM, zone_id: prev.zone_id }));
      await sos.refetch();
    } catch (err) {
      setSubmitError(err.message || "Failed to submit report.");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <>
      <PageHeader
        title="Citizen SOS Reports"
        subtitle="Ground-truth distress signals feeding the prioritization model"
        actions={
          <button type="button" className="btn" onClick={() => sos.refetch()} disabled={sos.loading}>
            {sos.loading ? "Refreshing…" : "Refresh"}
          </button>
        }
      />

      <div className="sos-layout">
        <section className="panel">
          <div className="panel__head">
            <h2 className="panel__title">New Report</h2>
          </div>
          <form className="form" onSubmit={handleSubmit}>
            <label className="form__field">
              <span>Zone *</span>
              <select className="input" value={form.zone_id} onChange={handleZoneChange} required>
                <option value="">Select a zone…</option>
                {(zones.data || []).map((z) => (
                  <option key={z.id} value={z.id}>
                    {z.name}
                  </option>
                ))}
              </select>
            </label>

            <label className="form__field">
              <span>Emergency type</span>
              <select className="input" value={form.emergency_type} onChange={update("emergency_type")}>
                {EMERGENCY_TYPES.map((t) => (
                  <option key={t} value={t}>
                    {humanize(t)}
                  </option>
                ))}
              </select>
            </label>

            <div className="form__row">
              <label className="form__field">
                <span>Severity (1–5)</span>
                <input
                  className="input"
                  type="number"
                  min="1"
                  max="5"
                  value={form.severity}
                  onChange={update("severity")}
                />
              </label>
              <label className="form__field">
                <span>People affected</span>
                <input
                  className="input"
                  type="number"
                  min="0"
                  value={form.people_affected}
                  onChange={update("people_affected")}
                />
              </label>
            </div>

            <label className="form__field">
              <span>Reporter name</span>
              <input
                className="input"
                type="text"
                placeholder="Optional"
                value={form.reporter_name}
                onChange={update("reporter_name")}
              />
            </label>

            <label className="form__field">
              <span>Description *</span>
              <textarea
                className="input"
                rows="3"
                placeholder="What is happening on the ground?"
                value={form.description}
                onChange={update("description")}
              />
            </label>

            <div className="form__row">
              <label className="form__field">
                <span>Latitude</span>
                <input className="input" type="number" step="any" value={form.latitude} onChange={update("latitude")} />
              </label>
              <label className="form__field">
                <span>Longitude</span>
                <input className="input" type="number" step="any" value={form.longitude} onChange={update("longitude")} />
              </label>
            </div>

            {submitError && <div className="alert alert--error">{submitError}</div>}
            {toast && <div className="alert alert--ok">{toast}</div>}

            <button type="submit" className="btn btn--primary" disabled={submitting}>
              {submitting ? "Submitting…" : "Submit SOS report"}
            </button>
          </form>
        </section>

        <section className="panel">
          <div className="panel__head">
            <h2 className="panel__title">Report Feed</h2>
            <select
              className="input input--sm"
              value={filterZone}
              onChange={(e) => setFilterZone(e.target.value)}
            >
              <option value="all">All zones</option>
              {(zones.data || []).map((z) => (
                <option key={z.id} value={z.id}>
                  {z.name}
                </option>
              ))}
            </select>
          </div>

          {sos.loading && !sos.data ? (
            <Loading label="Loading reports…" />
          ) : sos.error && !sos.data ? (
            <ErrorState error={sos.error} onRetry={sos.refetch} label="Could not load reports" />
          ) : !reports.length ? (
            <EmptyState title="No reports" body="No SOS reports match the current filter." />
          ) : (
            <div className="sos-list">
              {reports.map((r) => (
                <div key={r.id} className="sos-card">
                  <div className="sos-card__sev" style={{ background: severityColor(r.severity) }}>
                    SEV {r.severity}
                  </div>
                  <div className="sos-card__body">
                    <div className="sos-card__title">
                      {humanize(r.emergency_type)}
                      <span className="sos-card__zone">
                        {zoneById[r.zone_id]?.name || r.zone_id}
                      </span>
                    </div>
                    <div className="sos-card__desc">{r.description}</div>
                    <div className="sos-card__meta">
                      <span>{r.reporter_name || "Anonymous"}</span>
                      <span>· {r.people_affected} affected</span>
                      <span>· {formatDateTime(r.created_at)}</span>
                      <span className="tag">{r.source || "real-user"}</span>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </section>
      </div>
    </>
  );
}
