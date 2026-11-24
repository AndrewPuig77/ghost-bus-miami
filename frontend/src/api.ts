// Shapes of the backend's responses (backend/app/api) and small fetch helpers.

export interface Vehicle {
  vehicle_id: string;
  gps_ts: string; // ISO time of the bus's own GPS fix
  lat: number;
  lon: number;
  bearing: number | null;
  speed: number | null; // metres per second
  trip_id: string | null; // null when the bus is not running a scheduled trip
  route_id: string | null;
  direction_id: number | null;
  stop_id: string | null;
}

export interface VehicleMessage {
  type: "snapshot" | "update";
  server_time: string;
  vehicles: Vehicle[];
}

export interface Route {
  route_id: string;
  short_name: string | null;
  long_name: string | null;
  route_type: number | null;
  color: string | null; // hex without '#'
  text_color: string | null;
}

export interface FeedStatus {
  last_attempt: string | null;
  last_ok: string | null;
  last_error: string | null;
}

export interface StatusResponse {
  server_time: string;
  feeds: Record<string, FeedStatus>;
}

export interface ShapeCollection {
  type: "FeatureCollection";
  features: {
    type: "Feature";
    geometry: { type: "LineString"; coordinates: [number, number][] };
    properties: { shape_id: string; direction_id: number | null; headsign: string | null; trips: number };
  }[];
}

async function getJson<T>(path: string, signal?: AbortSignal): Promise<T> {
  const response = await fetch(path, { signal });
  if (!response.ok) throw new Error(`${path}: HTTP ${response.status}`);
  return (await response.json()) as T;
}

export const fetchRoutes = (signal?: AbortSignal) => getJson<Route[]>("/api/routes", signal);
export const fetchStatus = (signal?: AbortSignal) => getJson<StatusResponse>("/api/status", signal);
export const fetchShapes = (routeId: string, signal?: AbortSignal) =>
  getJson<ShapeCollection>(`/api/routes/${encodeURIComponent(routeId)}/shapes`, signal);

export function routeLabel(route: Route): string {
  return route.short_name ?? route.route_id;
}
