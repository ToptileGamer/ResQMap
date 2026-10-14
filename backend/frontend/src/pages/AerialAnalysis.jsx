import { useCallback, useRef, useState } from "react";
import { api } from "../api/client";
import { useApi } from "../hooks/useApi";
import { PageHeader } from "../components/Layout";
import PriorityBadge from "../components/PriorityBadge";
import { ErrorState, Loading } from "../components/StateViews";
import { humanize, priorityColor } from "../lib/format";

function withPrefix(base64) {
  return `data:image/jpeg;base64,${base64}`;
}

export default function AerialAnalysis() {
  const zonesFn = useCallback(() => api.listZones(), []);
  const zones = useApi(zonesFn, []);

  const inputRef = useRef(null);
  const [zoneId, setZoneId] = useState("");
  const [previewDataUrl, setPreviewDataUrl] = useState(null);
  const [useSynthetic, setUseSynthetic] = useState(true);
  const [description, setDescription] = useState("");
  const [running, setRunning] = useState(false);
  const [error, setError] = useState(null);
  const [result, setResult] = useState(null);

  const zonesList = zones.data || [];
  const activeZone = zonesList.find((z) => z.id === zoneId);

  const onFile = (file) => {
    if (!file) return;
    const reader = new FileReader();
    reader.onload = () => {
      setPreviewDataUrl(reader.result);
      setUseSynthetic(false);
    };
    reader.readAsDataURL(file);
  };

  const analyze = async () => {
    if (!zoneId) {
      setError("Select a zone first.");
      return;
    }
    setError(null);
    setResult(null);
    setRunning(true);
    try {
      const payload = { zone_id: zoneId, description: description || null };
      if (previewDataUrl) payload.image_base64 = previewDataUrl;
      const res = await api.analyzeAerial(payload);
      setResult(res);
    } catch (err) {
      setError(err.message || "Analysis failed.");
    } finally {
      setRunning(false);
    }
  };

  const currentRi = zonesList.findIndex((z) => z.id === zoneId);
  const nextZone = () => setZoneId(zonesList[(currentRi + 1) % zonesList.length]?.id || "");
  const prevZone = () =>
    setZoneId(zonesList[(currentRi - 1 + zonesList.length) % zonesList.length]?.id || "");

  return (
    <>
      <PageHeader
        title="Aerial Analysis"
        subtitle="Run drone imagery through flood detection and fold the result into live priority scoring"
      />

      {zones.loading && !zonesList.length && <Loading label="Loading zones…" />}
      {zones.error && !zonesList.length && (
        <ErrorState error={zones.error} onRetry={zones.refetch} label="Could not load zones" />
      )}

      {zonesList.length > 0 && (
        <div className="aerial-grid">
          <section className="panel">
            <div className="panel__head">
              <h2 className="panel__title">1 · Target zone</h2>
            </div>
            <div className="field">
              <label className="field__label" htmlFor="zone-select">
                Zone
              </label>
              <div className="select-row">
                <button type="button" className="btn btn--ghost" onClick={prevZone} aria-label="Previous zone">
                  ‹
                </button>
                <select
                  id="zone-select"
                  className="select"
                  value={zoneId}
                  onChange={(e) => setZoneId(e.target.value)}
                >
                  <option value="">Choose a zone…</option>
                  {zonesList.map((z) => (
                    <option key={z.id} value={z.id}>
                      {z.name} · {z.disaster_type}
                    </option>
                  ))}
                </select>
                <button type="button" className="btn btn--ghost" onClick={nextZone} aria-label="Next zone">
                  ›
                </button>
              </div>
            </div>
            {activeZone && (
              <div className="aerial-base">
                <div className="field__label">Baseline readings</div>
                <div className="aerial-base__row">
                  <span>Flood severity</span>
                  <strong style={{ color: priorityColor("High") }}>
                    {Math.round(activeZone.flood_severity)}%
                  </strong>
                </div>
                <div className="aerial-base__row">
                  <span>Aerial damage</span>
                  <strong>{Math.round(activeZone.aerial_damage_score)}</strong>
                </div>
                {activeZone.aerial_analyzed_at && (
                  <div className="muted">Last drone analysis: {activeZone.aerial_analyzed_at}</div>
                )}
              </div>
            )}

            <div className="field">
              <label className="field__label" htmlFor="aerial-desc">
                Optional notes
              </label>
              <input
                id="aerial-desc"
                className="input"
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                placeholder="e.g. Drone pass 2, 120 m AGL"
              />
            </div>
          </section>

          <section className="panel">
            <div className="panel__head">
              <h2 className="panel__title">2 · Image source</h2>
            </div>
            <div
              className="dropzone"
              role="button"
              tabIndex="0"
              onClick={() => inputRef.current?.click()}
              onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && inputRef.current?.click()}
            >
              <input
                ref={inputRef}
                type="file"
                accept="image/*"
                className="hidden-input"
                onChange={(e) => onFile(e.target.files?.[0])}
              />
              {previewDataUrl ? (
                <img src={previewDataUrl} alt="Selected aerial frame" className="dropzone__img" />
              ) : (
                <>
                  <div className="dropzone__icon">▣</div>
                  <p>
                    <strong>Click to upload</strong> a drone frame (PNG/JPEG)
                  </p>
                  <p className="muted">Or analyze a simulated frame generated from zone severity</p>
                </>
              )}
            </div>
            {previewDataUrl && (
              <button
                type="button"
                className="btn btn--ghost"
                onClick={() => {
                  setPreviewDataUrl(null);
                  setUseSynthetic(true);
                }}
              >
                Clear image · use synthetic
              </button>
            )}

            <label className="check">
              <input
                type="checkbox"
                checked={useSynthetic && !previewDataUrl}
                onChange={(e) => setUseSynthetic(e.target.checked)}
              />
              Use simulated drone frame (offline demo)
            </label>

            <button
              type="button"
              className="btn btn--primary aerial-run"
              onClick={analyze}
              disabled={running || !zoneId}
            >
              {running ? "Analyzing…" : "Run aerial analysis"}
            </button>
            {error && <div className="error-text">{error}</div>}
          </section>

          {result && (
            <section className="panel panel--wide aerial-result">
              <div className="panel__head">
                <h2 className="panel__title">3 · Detection result</h2>
                <span className="tag">{result.method.replace(/_/g, " ")}</span>
              </div>

              <div className="aerial-result__grid">
                <div>
                  <div className="field__label">Detected flood area</div>
                  <div className="aerial-big" style={{ color: result.flood_affected_pct > 50 ? "#ff3b5c" : "#ff8a3d" }}>
                    {result.flood_affected_pct}%
                  </div>
                  <MetricPct value={result.flood_affected_pct} />
                </div>
                <div>
                  <div className="field__label">Estimated damage</div>
                  <div className="aerial-big">{result.damage_score}/100</div>
                  <MetricPct value={result.damage_score} />
                </div>
                <div className="aerial-priority">
                  <div className="field__label">Reprioritized zone</div>
                  <PriorityBadge level={result.affected_priority_level} score={result.affected_priority_score} />
                  <p className="muted">
                    Zone {result.zone_name} now scores {result.affected_priority_score}/100 — drone
                    findings were written back into the live model.
                  </p>
                </div>
              </div>

              <div className="aerial-images">
                <figure className="aerial-figure">
                  <figcaption>Detection overlay</figcaption>
                  <img src={withPrefix(result.mask_base64)} alt="Flood mask overlay" />
                </figure>
                <figure className="aerial-figure">
                  <figcaption>Source frame ({result.image_width}×{result.image_height})</figcaption>
                  <img src={withPrefix(result.preview_base64)} alt="Analyzed drone frame" />
                </figure>
              </div>
            </section>
          )}
        </div>
      )}
    </>
  );
}

function MetricPct({ value }) {
  return (
    <div className="metric-line">
      <div className="metric-line__fill" style={{ width: `${Math.min(100, value)}%` }} />
    </div>
  );
}