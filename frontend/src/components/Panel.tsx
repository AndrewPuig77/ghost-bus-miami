import { routeLabel, type Route } from "../api";
import { FRESHNESS, FRESHNESS_ORDER, type Freshness } from "../freshness";

interface Props {
  routes: Route[];
  selectedRouteId: string;
  onSelectRoute: (routeId: string) => void;
  showOutOfService: boolean;
  onShowOutOfService: (show: boolean) => void;
  counts: Record<Freshness, number>;
}

export function Panel(props: Props) {
  const { routes, selectedRouteId, onSelectRoute, showOutOfService, onShowOutOfService, counts } =
    props;
  return (
    <aside className="panel">
      <h1 className="panel__title">Ghost Bus Miami</h1>
      <p className="panel__tagline">Where your bus is, and how much to trust it.</p>

      <label className="field">
        <span className="field__label">Route</span>
        <select value={selectedRouteId} onChange={(e) => onSelectRoute(e.target.value)}>
          <option value="">All routes</option>
          {routes.map((r) => (
            <option key={r.route_id} value={r.route_id}>
              {routeLabel(r)}
              {r.long_name ? ` · ${r.long_name}` : ""}
            </option>
          ))}
        </select>
      </label>

      <label className="check">
        <input
          type="checkbox"
          checked={showOutOfService}
          onChange={(e) => onShowOutOfService(e.target.checked)}
        />
        Show buses not in service
      </label>

      <div className="legend">
        <span className="field__label">Position last updated</span>
        <ul>
          {FRESHNESS_ORDER.map((f) => (
            <li key={f}>
              <span className="dot" style={{ background: FRESHNESS[f].color }} />
              <span>{FRESHNESS[f].label}</span>
              <span className="legend__count">{counts[f]}</span>
            </li>
          ))}
        </ul>
      </div>
    </aside>
  );
}
