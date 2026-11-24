"""Redis: latest position per vehicle, a pub/sub channel of changes, and feed health.

Keys
    vehicles:latest      hash, vehicle_id -> JSON of its newest ping
    vehicles:updates     pub/sub channel, JSON {"fetched_at", "vehicles": [...]} per poll
    feed:<name>:status   hash with last_attempt, last_ok, last_error
"""

import json
from datetime import datetime

from redis.asyncio import Redis

from app.worker.parse import VehiclePing

LATEST_KEY = "vehicles:latest"
UPDATES_CHANNEL = "vehicles:updates"


def feed_status_key(feed: str) -> str:
    return f"feed:{feed}:status"


def ping_json(p: VehiclePing) -> dict:
    return {
        "vehicle_id": p.vehicle_id,
        "gps_ts": p.gps_ts.isoformat(),
        "lat": p.lat,
        "lon": p.lon,
        "bearing": p.bearing,
        "speed": p.speed,
        "trip_id": p.trip_id,
        "route_id": p.route_id,
        "direction_id": p.direction_id,
        "stop_id": p.stop_id,
    }


class LiveCache:
    def __init__(self, redis: Redis) -> None:
        self.redis = redis
        self._last_gps: dict[str, datetime] = {}

    async def publish_positions(self, pings: list[VehiclePing], fetched_at: datetime) -> int:
        """Update vehicles whose GPS time moved forward and announce them. Returns the count."""
        newest: dict[str, VehiclePing] = {}
        for p in pings:
            if p.vehicle_id not in newest or p.gps_ts > newest[p.vehicle_id].gps_ts:
                newest[p.vehicle_id] = p
        changed = [
            p
            for p in newest.values()
            if p.vehicle_id not in self._last_gps or p.gps_ts > self._last_gps[p.vehicle_id]
        ]
        if not changed:
            return 0

        payloads = {p.vehicle_id: ping_json(p) for p in changed}
        pipe = self.redis.pipeline(transaction=False)
        pipe.hset(LATEST_KEY, mapping={vid: json.dumps(d) for vid, d in payloads.items()})
        pipe.publish(
            UPDATES_CHANNEL,
            json.dumps({"fetched_at": fetched_at.isoformat(), "vehicles": list(payloads.values())}),
        )
        await pipe.execute()
        for p in changed:
            self._last_gps[p.vehicle_id] = p.gps_ts
        return len(changed)

    async def set_feed_status(
        self, feed: str, ok: bool, at: datetime, error: str | None = None
    ) -> None:
        mapping = {"last_attempt": at.isoformat()}
        if ok:
            mapping["last_ok"] = at.isoformat()
            mapping["last_error"] = ""
        else:
            mapping["last_error"] = error or "unknown error"
        await self.redis.hset(feed_status_key(feed), mapping=mapping)
