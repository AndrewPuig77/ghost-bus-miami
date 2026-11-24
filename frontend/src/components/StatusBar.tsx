import { useEffect, useState } from "react";

import { fetchStatus, type StatusResponse } from "../api";
import { formatAge } from "../freshness";
import type { Connection } from "../useLiveVehicles";

const POSITIONS_FEED = "gtfs-rt-vehicle-positions";
// The worker polls every 15s; more than a few missed polls means the data is behind.
const DELAYED_AFTER_S = 90;
const POLL_MS = 30_000;

interface Props {
  connection: Connection;
  serverNow: number;
  shown: number;
}

export function StatusBar({ connection, serverNow, shown }: Props) {
  const [status, setStatus] = useState<StatusResponse | null>(null);
  const [unreachable, setUnreachable] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    const load = () =>
      fetchStatus(controller.signal)
        .then((s) => {
          setStatus(s);
          setUnreachable(false);
        })
        .catch((err: unknown) => {
          if (!controller.signal.aborted) setUnreachable(true);
          if (!(err instanceof DOMException)) console.warn(err);
        });
    load();
    const id = window.setInterval(load, POLL_MS);
    return () => {
      controller.abort();
      window.clearInterval(id);
    };
  }, []);

  const lastOk = status?.feeds[POSITIONS_FEED]?.last_ok;
  const feedAgeS = lastOk ? (serverNow - Date.parse(lastOk)) / 1000 : null;
  const delayed = unreachable || connection !== "live" || feedAgeS === null || feedAgeS > DELAYED_AFTER_S;

  let message: string;
  if (unreachable) message = "Can't reach the server";
  else if (connection === "connecting") message = "Connecting…";
  else if (connection === "reconnecting") message = "Connection lost, reconnecting…";
  else if (feedAgeS === null) message = "Waiting for the first live update";
  else if (delayed) message = `Live data delayed: last update ${formatAge(feedAgeS)}`;
  else message = `Live · updated ${formatAge(feedAgeS)}`;

  return (
    <div className={`status-bar ${delayed ? "status-bar--warn" : ""}`} role="status">
      <span className={`pulse ${delayed ? "pulse--off" : ""}`} aria-hidden />
      <span>{message}</span>
      <span className="status-bar__count">{shown} buses</span>
    </div>
  );
}
