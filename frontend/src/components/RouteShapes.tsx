import { latLngBounds } from "leaflet";
import { useEffect } from "react";
import { Polyline, useMap } from "react-leaflet";

import type { ShapeCollection } from "../api";

interface Props {
  shapes: ShapeCollection;
  color: string;
}

/** Draws every path a route follows and zooms the map to fit it. */
export function RouteShapes({ shapes, color }: Props) {
  const map = useMap();
  // GeoJSON is [lon, lat]; Leaflet wants [lat, lon].
  const lines = shapes.features.map((f) => ({
    id: f.properties.shape_id,
    points: f.geometry.coordinates.map(([lon, lat]) => [lat, lon] as [number, number]),
  }));

  useEffect(() => {
    const all = lines.flatMap((l) => l.points);
    if (all.length) map.fitBounds(latLngBounds(all), { padding: [40, 40] });
    // Depends on `shapes` only, so the map fits once per route rather than every render.
  }, [shapes, map]);

  return (
    <>
      {lines.map((l) => (
        <Polyline
          key={l.id}
          positions={l.points}
          pathOptions={{ color, weight: 4, opacity: 0.55 }}
          interactive={false}
        />
      ))}
    </>
  );
}
