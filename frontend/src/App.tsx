import { useEffect, useMemo, useState } from "react";
import { MapContainer, TileLayer } from "react-leaflet";

import { fetchRoutes, fetchShapes, type Route, type ShapeCollection } from "./api";
import { BusLayer } from "./components/BusLayer";
import { Panel } from "./components/Panel";
import { RouteShapes } from "./components/RouteShapes";
import { StatusBar } from "./components/StatusBar";
import { FRESHNESS_ORDER, freshnessOf, type Freshness } from "./freshness";
import { useLiveVehicles, useNow } from "./useLiveVehicles";

const MIAMI: [number, number] = [25.77, -80.25];

export default function App() {
  const { vehicles, connection, clockOffsetMs } = useLiveVehicles();
  const serverNow = useNow(5000) + clockOffsetMs;

  const [routes, setRoutes] = useState<Route[]>([]);
  const [selectedRouteId, setSelectedRouteId] = useState("");
  const [showOutOfService, setShowOutOfService] = useState(false);
  const [shapes, setShapes] = useState<ShapeCollection | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    fetchRoutes(controller.signal).then(setRoutes).catch(console.warn);
    return () => controller.abort();
  }, []);

  useEffect(() => {
    setShapes(null);
    if (!selectedRouteId) return;
    const controller = new AbortController();
    fetchShapes(selectedRouteId, controller.signal).then(setShapes).catch(console.warn);
    return () => controller.abort();
  }, [selectedRouteId]);

  const routesById = useMemo(() => new Map(routes.map((r) => [r.route_id, r])), [routes]);
  const selectedRoute = routesById.get(selectedRouteId);

  const shown = useMemo(
    () =>
      [...vehicles.values()].filter(
        (v) =>
          (showOutOfService || v.trip_id !== null) &&
          (!selectedRouteId || v.route_id === selectedRouteId),
      ),
    [vehicles, showOutOfService, selectedRouteId],
  );

  const counts = useMemo(() => {
    const c = Object.fromEntries(FRESHNESS_ORDER.map((f) => [f, 0])) as Record<Freshness, number>;
    for (const v of shown) c[freshnessOf((serverNow - Date.parse(v.gps_ts)) / 1000)]++;
    return c;
  }, [shown, serverNow]);

  return (
    <div className="app">
      <MapContainer center={MIAMI} zoom={11} preferCanvas className="map" zoomControl={false}>
        {/* OpenStreetMap's own tiles: no key, attribution required, fine for light use.
            Busier sites should move to a dedicated tile provider. */}
        <TileLayer
          attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
          url="https://tile.openstreetmap.org/{z}/{x}/{y}.png"
          maxZoom={19}
        />
        {shapes && selectedRoute && (
          <RouteShapes shapes={shapes} color={`#${selectedRoute.color ?? "334155"}`} />
        )}
        <BusLayer vehicles={shown} routes={routesById} serverNow={serverNow} />
      </MapContainer>

      <Panel
        routes={routes}
        selectedRouteId={selectedRouteId}
        onSelectRoute={setSelectedRouteId}
        showOutOfService={showOutOfService}
        onShowOutOfService={setShowOutOfService}
        counts={counts}
      />
      <StatusBar connection={connection} serverNow={serverNow} shown={shown.length} />
    </div>
  );
}
