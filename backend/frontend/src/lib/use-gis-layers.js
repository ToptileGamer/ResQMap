import { useMemo, useState, useCallback } from "react";
import { api } from "../api/client";


export function useGISLayers() {
  const [layers, setLayers] = useState([]);
  const [bounds, setBounds] = useState(null);
  const [fetchState, setFetchState] = useState("idle");
  const [error, setError] = useState(null);

  const load = useCallback(async () => {
    setFetchState("loading");
    setError(null);
    try {
      const data = await api.getGisLayers();
      setLayers(data.layers ?? []);
      setBounds(data.bounds ?? null);
      setFetchState("ready");
    } catch (err) {
      setError(err);
      setFetchState("error");
    }
  }, []);

  const [visibleLayerTypes, setVisibleLayerTypes] = useState(new Set());
  const [opacityState, setOpacityState] = useState({});

  const visibleLayers = useMemo(
    () => layers.filter((l) => visibleLayerTypes.has(l.layer_type)),
    [layers, visibleLayerTypes],
  );

  const toggleLayer = useCallback(
    (layerType, on) => {
      setVisibleLayerTypes((prev) => {
        const next = new Set(prev);
        if (on) next.add(layerType);
        else next.delete(layerType);
        return next;
      });
    },
    [],
  );

  const opacityFor = useCallback(
    (layerType, opacity) => {
      setOpacityState((prev) => ({ ...prev, [layerType]: opacity }));
    },
    [setOpacityState],
  );

  const opacities = useMemo(
    () => Object.fromEntries(Object.entries(opacityState).filter(([, v]) => v != null)),
    [opacityState],
  );

  const resetLayers = useCallback(() => {
    setVisibleLayerTypes(new Set());
    setOpacityState({});
  }, []);

  const loadOnIdle = useCallback(() => {
    if (typeof requestIdleCallback === "function") {
      requestIdleCallback(load, { timeout: 4000 });
    } else {
      queueMicrotask(load);
    }
  }, [load]);

  return {
    layers,
    visibleLayers,
    bounds,
    fetchState,
    error,
    load,
    loadOnIdle,
    toggleLayer,
    setVisibleLayerTypes,
    setAllVisible: (next) => {
      setVisibleLayerTypes(new Set(next.map((l) => l.layer_type)));
    },
    opacityFor,
    opacities,
    resetLayers,
  };
}
