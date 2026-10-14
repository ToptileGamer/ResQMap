import { useEffect, useMemo, useRef, useState, useCallback, forwardRef } from "react";
import L from "leaflet";
import "leaflet/dist/leaflet.css";
import "leaflet.heat";
import { apiClient } from "../lib/api-client";


const DEFAULT_CENTER = [12.9716, 77.5946];

/**
 * Imperative Leaflet map with GIS layer overlays.
 *
 * markers: [{ id, name, lat, lng, color, radius, subtitle, href }]
 * route:   [{ lat, lng, label, color }]  -> drawn as a dashed polyline
 * start:   { lat, lng }                  -> drone launch marker
 * heat:    [[lat, lng, intensity], ...]  -> priority heat layer
 *
 * layers:  GIS layer toggles from /api/gis/layers (GeoJSON FeatureCollections).
 * layerOpacities: per-layer opacity values (0..1).
 * onLayerClick: optional callback for clicked GeoJSON feature.
 */
const ZoneMap = forwardRef(function ZoneMap({
  markers = [],
  route = [],
  start = null,
  heat = [],
  center = DEFAULT_CENTER,
  zoom = 11,
  height = "100%",
  onMarkerClick,
  layers = [],
  layerOpacities = {},
  onLayerClick,
}) {
  const containerRef = useRef(null);
  const mapRef = useRef(null);
  const layerRef = useRef(null);
  const geoLayerRefs = useRef(new Map());
  const [layerStore, setLayerStore] = useState(null);
  const [fetchState, setFetchState] = useState("idle");
  const [selectedFeature, setSelectedFeature] = useState(null);
  const dispatchRef = useRef(() => {});
  const mountedRef = useRef(true);

  // Initialize map once.
  useEffect(() => {
    if (!containerRef.current || mapRef.current) return;
    const map = L.map(containerRef.current, {
      center,
      zoom,
      zoomControl: true,
      attributionControl: true,
    });
    L.tileLayer(
      "https://services.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Base/MapServer/tile/{z}/{y}/{x}",
      {
        attribution:
          'Tiles &copy; <a href="https://www.esri.com/">Esri</a> &mdash; Esri, DeLorme, HERE',
        maxZoom: 16,
      },
    ).addTo(map);
    mapRef.current = map;
    layerRef.current = L.layerGroup().addTo(map);

    return () => {
      mountedRef.current = false;
      map.remove();
      mapRef.current = null;
      layerRef.current = null;
    };
  }, [center, zoom]);

  const notify = useCallback(
    (next) => {
      dispatchRef.current = next;
    },
    [],
  );

  const loadLayers = useCallback(async () => {
    if (!mountedRef.current) return;
    try {
      setFetchState("loading");
      const data = await apiClient.get("/gis/layers");
      if (mountedRef.current) {
        setLayerStore(data);
        setFetchState("ready");
        dispatchRef.current({ type: "layers-ready", layers: data.layers, bounds: data.bounds });
      }
    } catch (err) {
      if (mountedRef.current) {
        setFetchState("error");
        dispatchRef.current({ type: "layers-error", error: err });
      }
    }
  }, [notify]);

  useEffect(() => {
    dispatchRef.current = () => {};
    const startLoad = () => {
      if (typeof requestIdleCallback === "function") {
        requestIdleCallback(loadLayers, { timeout: 4000 });
      } else {
        setTimeout(loadLayers, 0);
      }
    };
    startLoad();
    return () => {
      mountedRef.current = false;
    };
  }, [loadLayers]);

  // Redraw markers/route whenever data changes.
  useEffect(() => {
    const map = mapRef.current;
    const layer = layerRef.current;
    if (!map || !layer) return;
    layer.clearLayers();

    markers.forEach((m) => {
      const marker = L.circleMarker([m.lat, m.lng], {
        radius: m.radius ?? 10,
        color: "#0b1220",
        weight: 2,
        fillColor: m.color || "#7c8aa5",
        fillOpacity: 0.9,
      });
      const subtitle = m.subtitle ? `<div class="map-popup-sub">${m.subtitle}</div>` : "";
      const link = m.href ? `<a class="map-popup-link" href="${m.href}">Open details →</a>` : "";
      marker.bindPopup(
        `<div class="map-popup"><strong>${m.name}</strong>${subtitle}${link}</div>`,
      );
      marker.on("click", () => onMarkerClick?.(m));
      marker.addTo(layer);
    });

    if (start) {
      L.circleMarker([start.lat, start.lng], {
        radius: 8,
        color: "#0b1220",
        weight: 2,
        fillColor: "#4aa8ff",
        fillOpacity: 1,
      })
        .bindPopup("<strong>Drone launch point</strong>")
        .addTo(layer);
    }

    if (route.length > 1) {
      const latlngs = route.map((p) => [p.lat, p.lng]);
      if (start) latlngs.unshift([start.lat, start.lng]);
      L.polyline(latlngs, {
        color: "#4aa8ff",
        weight: 3,
        dashArray: "6 8",
        opacity: 0.9,
      }).addTo(layer);
    }

    if (heat.length) {
      L.heatLayer(heat, {
        radius: 45,
        blur: 32,
        maxZoom: 14,
        minOpacity: 0.25,
        gradient: {
          0.0: "#39d98a",
          0.4: "#ffd23f",
          0.7: "#ff8a3d",
          1.0: "#ff3b5c",
        },
      }).addTo(layer);
    }

    const boundsPoints = [
      ...markers.map((m) => [m.lat, m.lng]),
      ...route.map((p) => [p.lat, p.lng]),
      ...(start ? [[start.lat, start.lng]] : []),
    ];
    if (boundsPoints.length > 1) {
      map.fitBounds(L.latLngBounds(boundsPoints).pad(0.25));
    } else if (boundsPoints.length === 1) {
      map.setView(boundsPoints[0], 13);
    }
  }, [markers, route, start, heat, onMarkerClick]);

  // GIS layers: sync enabled list and opacities, render GeoJSON overlays.
  useEffect(() => {
    const map = mapRef.current;
    const layer = layerRef.current;
    if (!map || !layer || !layerStore) return;

    const refs = geoLayerRefs.current;
    const enabled = layers;
    const opacities = layerOpacities;

    // Remove overlays not in the enabled list.
    for (const [key, geom] of refs) {
      if (!enabled.includes(key)) {
        layer.remove(geom);
        refs.delete(key);
      }
    }

    for (const gisLayer of layerStore.layers) {
      const key = gisLayer.layer_type;
      if (!enabled.includes(key)) continue;

      let geom = refs.get(key);
      if (!geom || !L.GeoJSON) {
        geom = L.geoJSON(gisLayer.geojson, {
          style: (f) => ({
            opacity: opacities[key] ?? 1,
            fillOpacity: opacities[key] != null ? Math.min(0.9, opacities[key] * 0.9) : 0.35,
            color: layerStyleColor(key),
            weight: 1.4,
          }),
          onEachFeature: (feature, leafletLayer) => {
            leafletLayer.bindPopup(featurePopupHtml(gisLayer, feature));
            leafletLayer.on("click", () => {
              setSelectedFeature({ layerType: gisLayer.layer_type, feature });
              onLayerClick?.({ layerType: gisLayer.layer_type, feature });
            });
          },
          pointToLayer: (f, latlng) => {
            return L.circleMarker(latlng, {
              radius: 7,
              color: layerStyleColor(key),
              weight: 2,
              fillColor: layerStyleColor(key),
              fillOpacity: 0.95,
            });
          },
        });
        geom.addTo(layer);
        refs.set(key, geom);
      } else {
        geom.setStyle({
          opacity: opacities[key] ?? 1,
          fillOpacity: opacities[key] != null ? Math.min(0.9, opacities[key] * 0.9) : 0.35,
        });
      }
    }
  }, [layerStore, layers, layerOpacities, onLayerClick]);

  return (
    <div ref={containerRef} style={{ height, width: "100%" }} />
  );
});

export default ZoneMap;
