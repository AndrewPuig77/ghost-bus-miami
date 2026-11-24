import { useEffect, useState } from "react";

import type { Vehicle, VehicleMessage } from "./api";

export type Connection = "connecting" | "live" | "reconnecting";

export interface LiveVehicles {
  vehicles: Map<string, Vehicle>;
  connection: Connection;
  /** Server clock minus browser clock, in ms. Add to Date.now() for server time. */
  clockOffsetMs: number;
}

const MAX_RETRY_MS = 30_000;
// Updates only carry buses that moved, so buses that go quiet are dropped here.
const FORGET_AFTER_MS = 30 * 60_000;

function socketUrl(): string {
  const scheme = location.protocol === "https:" ? "wss" : "ws";
  return `${scheme}://${location.host}/ws/vehicles`;
}

/** Keeps the newest position of every bus, from a snapshot plus streamed updates. */
export function useLiveVehicles(): LiveVehicles {
  const [state, setState] = useState<LiveVehicles>({
    vehicles: new Map(),
    connection: "connecting",
    clockOffsetMs: 0,
  });

  useEffect(() => {
    let ws: WebSocket | null = null;
    let retryMs = 1000;
    let retryTimer: number | undefined;
    let closed = false;

    const connect = () => {
      ws = new WebSocket(socketUrl());
      ws.onopen = () => {
        retryMs = 1000;
      };
      ws.onmessage = (event) => {
        const msg = JSON.parse(event.data as string) as VehicleMessage;
        const offset = Date.parse(msg.server_time) - Date.now();
        setState((prev) => {
          const next = msg.type === "snapshot" ? new Map<string, Vehicle>() : new Map(prev.vehicles);
          for (const v of msg.vehicles) {
            const old = next.get(v.vehicle_id);
            if (!old || Date.parse(v.gps_ts) >= Date.parse(old.gps_ts)) next.set(v.vehicle_id, v);
          }
          const cutoff = Date.now() + offset - FORGET_AFTER_MS;
          for (const [id, v] of next) if (Date.parse(v.gps_ts) < cutoff) next.delete(id);
          return { vehicles: next, connection: "live", clockOffsetMs: offset };
        });
      };
      ws.onclose = () => {
        if (closed) return;
        setState((prev) => ({ ...prev, connection: "reconnecting" }));
        retryTimer = window.setTimeout(connect, retryMs);
        retryMs = Math.min(retryMs * 2, MAX_RETRY_MS);
      };
    };

    connect();
    return () => {
      closed = true;
      window.clearTimeout(retryTimer);
      ws?.close();
    };
  }, []);

  return state;
}

/** Re-renders every `intervalMs` so ages keep counting up between updates. */
export function useNow(intervalMs: number): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = window.setInterval(() => setNow(Date.now()), intervalMs);
    return () => window.clearInterval(id);
  }, [intervalMs]);
  return now;
}
