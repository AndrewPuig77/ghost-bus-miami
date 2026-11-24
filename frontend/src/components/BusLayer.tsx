import { CircleMarker, Popup } from "react-leaflet";

import { routeLabel, type Route, type Vehicle } from "../api";
import { FRESHNESS, formatAge, freshnessOf } from "../freshness";

interface Props {
  vehicles: Vehicle[];
  routes: Map<string, Route>;
  serverNow: number;
}

const MPS_TO_MPH = 2.23694;

export function BusLayer({ vehicles, routes, serverNow }: Props) {
  return (
    <>
      {vehicles.map((v) => {
        const ageS = (serverNow - Date.parse(v.gps_ts)) / 1000;
        const freshness = freshnessOf(ageS);
        const color = FRESHNESS[freshness].color;
        const inService = v.trip_id !== null;
        const route = v.route_id ? routes.get(v.route_id) : undefined;
        return (
          <CircleMarker
            key={v.vehicle_id}
            center={[v.lat, v.lon]}
            radius={inService ? 6 : 4}
            pathOptions={{
              color: "#ffffff",
              weight: 1.5,
              fillColor: color,
              fillOpacity: inService ? 0.95 : 0.45,
            }}
          >
            <Popup>
              <div className="bus-popup">
                <div className="bus-popup__title">
                  {route ? (
                    <>
                      <span
                        className="route-badge"
                        style={{
                          background: `#${route.color ?? "334155"}`,
                          color: `#${route.text_color ?? "ffffff"}`,
                        }}
                      >
                        {routeLabel(route)}
                      </span>
                      {route.long_name}
                    </>
                  ) : (
                    "Not in service"
                  )}
                </div>
                <div className="bus-popup__row">
                  <span className="dot" style={{ background: color }} />
                  Position {formatAge(ageS)}
                </div>
                {v.speed !== null && (
                  <div className="bus-popup__row">{Math.round(v.speed * MPS_TO_MPH)} mph</div>
                )}
                <div className="bus-popup__meta">
                  Bus {v.vehicle_id}
                  {v.trip_id && <> · trip {v.trip_id}</>}
                </div>
              </div>
            </Popup>
          </CircleMarker>
        );
      })}
    </>
  );
}
