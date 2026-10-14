import { useCallback } from "react";

export const layerLabel = (layerType) => ({
  admin_boundaries: "Admin Boundaries",
  rivers: "Rivers & Drainage",
  roads: "Roads",
  elevation: "Elevation Model",
  low_lying_areas: "Low-Lying Areas",
  shelters: "Shelters",
  hospitals: "Hospitals",
  population_density: "Population Density",
  flood_hazard: "Flood Hazard",
}[layerType] ?? layerType);

export const layerStyleColor = (layerType) => ({
  admin_boundaries: "#5e4fa2",
  rivers: "#3288bd",
  roads: "#ffd23f",
  elevation: "#66c2a5",
  low_lying_areas: "#abdda4",
  shelters: "#4aa8ff",
  hospitals: "#d94800",
  population_density: "#9ecae1",
  flood_hazard: "#ff3b5c",
}[layerType] ?? "#7c8aa5");

export const featurePopupHtml = (gisLayer, feature) => {
  const props = feature?.properties ?? {};
  const geom = feature?.geometry?.type ?? "unknown";
  const rows = Object.entries(props).map(
    ([k, v]) =>
      `<div class="layer-popup-row"><span class="layer-popup-k">${k}</span><span class="layer-popup-v">${v ?? "—"}</span></div>`,
  );
  return `
    <div class="layer-popup">
      <div class="layer-popup-head">${gisLayer.name ?? gisLayer.layer_type}</div>
      <div class="layer-popup-meta">${gisLayer.description ?? ""}</div>
      <div class="layer-popup-geom">Geometry: ${geom}</div>
      ${rows.length ? `<div class="layer-popup-props">${rows.join("")}</div>` : ""}
      <div class="layer-popup-source">Source: ${gisLayer.source ?? "—"}</div>
    </div>
  `;
};

export default function LayerPanel({
  layers = [],
  visible = new Set(),
  opacities = {},
  fetchState = "idle",
  onToggle,
  onOpacityChange,
  onFocusBounds,
}) {
  const handleToggle = useCallback(
    (layer) => {
      onToggle?.(visible.has(layer.layer_type) ? [] : [layer]);
    },
    [visible, onToggle],
  );

  const handleClear = useCallback(() => {
    onToggle?.([]);
  }, [onToggle]);

  const handleOpacity = useCallback(
    (layerType, value) => {
      onOpacityChange?.(layerType, parseFloat(value));
    },
    [onOpacityChange],
  );

  const handleFocus = useCallback(
    (layer) => {
      onFocusBounds?.(layer);
    },
    [onFocusBounds],
  );

  if (!layers.length && fetchState !== "ready") {
    return (
      <div className="layer-panel layer-panel--empty">
        <div className="layer-panel__empty-title">Map Layers</div>
        <div className="layer-panel__empty-text">
          {fetchState === "loading"
            ? "Loading GIS layers…"
            : fetchState === "error"
              ? "Could not load map layers."
              : "No map layers available."}
        </div>
      </div>
    );
  }

  return (
    <div className="layer-panel">
      <div className="layer-panel__head">
        <div className="layer-panel__title">Map Layers</div>
        <button
          className={`layer-panel__clear ${visible.size === 0 ? "is-active" : ""}`}
          onClick={handleClear}
          type="button"
        >
          Clear all
        </button>
      </div>

      <ul className="layer-panel__list">
        {layers.map((l) => {
          const layerKey = l.layer_type;
          const on = visible.has(layerKey);
          const opacity = opacities[layerKey] ?? 1;
          return (
            <li key={layerKey} className={`layer-panel__item ${on ? "is-on" : ""}`}>
              <label className="layer-panel__row">
                <input
                  className="layer-panel__toggle"
                  type="checkbox"
                  checked={on}
                  onChange={() => handleToggle(l)}
                />
                <span className="layer-panel__swatch" style={{ background: layerStyleColor(layerKey) }} />
                <span className="layer-panel__name">{layerLabel(layerKey)}</span>
                <span className="tag" title={`Source: ${l.source || "simulated"}`}>{l.source === "real-upload" ? "REAL" : "SIM"}</span>
              </label>
              {on && (
                <div className="layer-panel__opacity-row">
                  <input
                    className="layer-panel__opacity"
                    type="range"
                    min={0}
                    max={1}
                    step={0.05}
                    value={opacity}
                    onChange={(e) => handleOpacity(layerKey, e.target.value)}
                  />
                  <span className="layer-panel__opacity-val">{Math.round(opacity * 100)}%</span>
                  <button
                    className="layer-panel__focus"
                    type="button"
                    title="Focus this layer on the map"
                    onClick={() => handleFocus(l)}
                  >
                    Focus
                  </button>
                </div>
              )}
            </li>
          );
        })}
      </ul>

      {(visible.size > 0 || fetchState === "ready") && (
        <div className="layer-panel__legend">
          <div className="layer-panel__legend-title">Legend</div>
          <ul className="layer-panel__legend-list">
            {[...visible].map((key) => {
              const found = layers.find((l) => l.layer_type === key);
              if (!found) return null;
              return (
                <li key={key} className="layer-panel__legend-item">
                  <span className="layer-panel__legend-swatch" style={{ background: layerStyleColor(key) }} />
                  <span className="layer-panel__legend-name">{layerLabel(key)}</span>
                </li>
              );
            })}
          </ul>
        </div>
      )}
    </div>
  );
}
