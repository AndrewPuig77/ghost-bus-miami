// How much to trust a bus's position, from how old its GPS fix is.
// Ages are measured against the server's clock so a wrong laptop clock can't skew them.

export type Freshness = "live" | "recent" | "stale" | "lost";

export const FRESHNESS: Record<Freshness, { label: string; color: string; maxAgeS: number }> = {
  live: { label: "Under 1 min", color: "#16a34a", maxAgeS: 60 },
  recent: { label: "1–3 min", color: "#ca8a04", maxAgeS: 180 },
  stale: { label: "3–10 min", color: "#ea580c", maxAgeS: 600 },
  lost: { label: "Over 10 min", color: "#6b7280", maxAgeS: Infinity },
};

export const FRESHNESS_ORDER: Freshness[] = ["live", "recent", "stale", "lost"];

export function freshnessOf(ageS: number): Freshness {
  return FRESHNESS_ORDER.find((f) => ageS <= FRESHNESS[f].maxAgeS) ?? "lost";
}

export function formatAge(ageS: number): string {
  const s = Math.max(0, Math.round(ageS));
  if (s < 60) return `${s}s ago`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m} min ago`;
  return `${Math.floor(m / 60)} h ${m % 60} min ago`;
}
