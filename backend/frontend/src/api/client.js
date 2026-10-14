const BASE_URL = (import.meta.env.VITE_API_BASE_URL || "/api").replace(/\/$/, "");

export class ApiError extends Error {
  constructor(message, status, payload) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.payload = payload;
  }
}

function url(path) {
  if (/^https?:\/\//i.test(path)) return path;
  const normalized = path.startsWith("/") ? path : `/${path}`;
  return `${BASE_URL}${normalized}`;
}

async function request(path, { method = "GET", body, signal, responseType = "json" } = {}) {
  const res = await fetch(url(path), {
    method,
    headers: body ? { "Content-Type": "application/json" } : undefined,
    body: body ? JSON.stringify(body) : undefined,
    signal,
  });

  if (responseType === "blob") {
    if (!res.ok) {
      const text = await res.text();
      let payload = null;
      try {
        payload = JSON.parse(text);
      } catch {
        payload = text;
      }
      const detail =
        (payload && payload.detail && (payload.detail.message || payload.detail)) ||
        (typeof payload === "string" ? payload : null) ||
        `Request failed with status ${res.status}`;
      throw new ApiError(String(detail), res.status, payload);
    }
    return res.blob();
  }

  const text = await res.text();
  let payload = null;
  if (text) {
    try {
      payload = JSON.parse(text);
    } catch {
      payload = text;
    }
  }

  if (!res.ok) {
    const detail =
      (payload && payload.detail && (payload.detail.message || payload.detail)) ||
      (typeof payload === "string" ? payload : null) ||
      `Request failed with status ${res.status}`;
    throw new ApiError(String(detail), res.status, payload);
  }

  return payload;
}

// The backend router paths were not present in the provided source, so GET
// requests try a small set of conventional candidates before giving up.
async function getFirst(paths, options) {
  let lastError;
  for (const path of paths) {
    try {
      return await request(path, options);
    } catch (err) {
      lastError = err;
      if (err instanceof ApiError && (err.status === 404 || err.status === 405)) {
        continue;
      }
      throw err;
    }
  }
  throw lastError;
}

export const api = {
  health: () => request("/health"),

  listZones: () => getFirst(["/zones", "/zones/"]),

  getZone: (zoneId) => request(`/zones/${encodeURIComponent(zoneId)}`),

  analyzeAll: () =>
    getFirst(["/analysis/all", "/analysis", "/analysis/refresh"]),

  analyzeZone: (zoneId) =>
    getFirst([
      `/analysis/${encodeURIComponent(zoneId)}`,
      `/analysis/zone/${encodeURIComponent(zoneId)}`,
    ]),

  explainZone: (zoneId) =>
    getFirst([
      `/analysis/${encodeURIComponent(zoneId)}/explanation`,
      `/analysis/${encodeURIComponent(zoneId)}/explain`,
      `/analysis/${encodeURIComponent(zoneId)}/explanation/`,
    ]),

  getWeather: (zoneId) =>
    getFirst([
      `/weather/${encodeURIComponent(zoneId)}`,
      `/weather?zone_id=${encodeURIComponent(zoneId)}`,
    ]),

  listWeather: () => getFirst(["/weather", "/weather/all"]),

  listSos: (zoneId) =>
    getFirst([
      zoneId ? `/sos?zone_id=${encodeURIComponent(zoneId)}` : "/sos",
      "/sos/",
    ]),

  createSos: (report) => request("/sos", { method: "POST", body: report }),

  planRoute: (payload) =>
    request("/routes/drone", { method: "POST", body: payload }),

  getZoneHistory: (zoneId) =>
    request(`/zones/${encodeURIComponent(zoneId)}/history`),

  getForecast: (zoneId) =>
    request(`/analysis/${encodeURIComponent(zoneId)}/forecast`),

  analyzeAerial: (payload) =>
    request("/imagery/analyze", { method: "POST", body: payload }),

  listMediaSamples: () => request("/media/samples"),

  getGisLayers: () => request("/gis/layers"),

  getHazardZones: (sensorRadiusKm = 4.0) =>
    request(`/hazard/zones?sensor_radius_km=${sensorRadiusKm}`),

  getHazardDashboard: (sensorRadiusKm = 4.0) =>
    request(`/hazard/dashboard?sensor_radius_km=${sensorRadiusKm}`),

  exportGeoJSON: (includeGis = false) =>
    request(`/export/geojson?include_gis=${includeGis}`, { responseType: "blob" }),

  exportPDF: () =>
    request("/export", { method: "POST", body: { format: "pdf" }, responseType: "blob" }),

  exportPNG: () =>
    request("/export", { method: "POST", body: { format: "png" }, responseType: "blob" }),

  getWeights: () => request("/hazard/weights"),
  setWeights: (w) => request("/hazard/weights", { method: "POST", body: w }),
  planSearch: (p) => request("/routes/search", { method: "POST", body: p }),
  rescueRoute: (p) => request("/routes/rescue", { method: "POST", body: p }),
  riskGrid: (model = "ml", rain = 1.0, horizon = 6) => request(`/risk/grid?model=${model}&rainfall_multiplier=${rain}&horizon_hours=${horizon}`),
  predictedZones: (model = "ml", rain = 1.0, horizon = 6) => request(`/risk/predicted-zones?model=${model}&rainfall_multiplier=${rain}&horizon_hours=${horizon}`),
  modelMetrics: () => request("/risk/model-metrics"),
  backtest: (idx = 8) => request(`/risk/backtest?event_idx=${idx}`),
  modelCard: () => request("/risk/model-card"),
  allocByTarget: (target = "current", d = 3, t = 2) => request(`/allocation/by-target?target=${target}&num_drones=${d}&num_teams=${t}`),
  allocSummary: (d = 3, t = 2) => request(`/allocation/summary?num_drones=${d}&num_teams=${t}`),
  allocCsv: () => request("/allocation/export.csv?num_drones=3&num_teams=2", { responseType: "blob" }),
  exportRoutes: () => request("/export/routes", { responseType: "blob" }),
  whatIf: (p) => request("/whatif", { method: "POST", body: p }),
};

export { BASE_URL };
