"""Postgres writes for the ingestion worker."""

import gzip
import time
from collections.abc import Iterable
from datetime import date, datetime, timedelta

from psycopg import sql
from psycopg_pool import AsyncConnectionPool

from app.worker.parse import TripStatusUpdate, VehiclePing

INSERT_PING = """
INSERT INTO vehicle_positions (
    vehicle_id, gps_ts, fetched_at, lat, lon, bearing, speed, trip_id, route_id,
    service_date, direction_id, stop_id, current_stop_sequence, current_status, feed_version_id
) VALUES (
    %(vehicle_id)s, %(gps_ts)s, %(fetched_at)s, %(lat)s, %(lon)s, %(bearing)s, %(speed)s,
    %(trip_id)s, %(route_id)s, %(service_date)s, %(direction_id)s, %(stop_id)s,
    %(current_stop_sequence)s, %(current_status)s, %(feed_version_id)s
)
ON CONFLICT DO NOTHING
"""

# A trip keeps its latest status, but canceled_seen_at remembers that it was ever canceled.
UPSERT_TRIP_STATUS = """
INSERT INTO trip_status AS t (
    service_date, trip_id, route_id, feed_version_id, status, vehicle_id,
    first_seen_at, last_seen_at, canceled_seen_at
) VALUES (
    %(service_date)s, %(trip_id)s, %(route_id)s, %(feed_version_id)s, %(status)s,
    %(vehicle_id)s, %(seen)s, %(seen)s,
    CASE WHEN %(status)s::text = 'canceled' THEN %(seen)s::timestamptz END
)
ON CONFLICT (service_date, trip_id) DO UPDATE SET
    status           = EXCLUDED.status,
    route_id         = coalesce(EXCLUDED.route_id, t.route_id),
    vehicle_id       = coalesce(EXCLUDED.vehicle_id, t.vehicle_id),
    feed_version_id  = coalesce(t.feed_version_id, EXCLUDED.feed_version_id),
    last_seen_at     = EXCLUDED.last_seen_at,
    canceled_seen_at = coalesce(t.canceled_seen_at, EXCLUDED.canceled_seen_at)
"""


class Store:
    FEED_VERSION_TTL_S = 600

    def __init__(self, pool: AsyncConnectionPool) -> None:
        self.pool = pool
        self._partitions: set[date] = set()
        self._feed_version: int | None = None
        self._feed_version_checked = float("-inf")

    async def active_feed_version(self) -> int | None:
        """The active static GTFS version, cached for a few minutes."""
        if time.monotonic() - self._feed_version_checked > self.FEED_VERSION_TTL_S:
            async with self.pool.connection() as conn:
                row = await (
                    await conn.execute("SELECT id FROM feed_versions WHERE is_active")
                ).fetchone()
            self._feed_version = row[0] if row else None
            self._feed_version_checked = time.monotonic()
        return self._feed_version

    def forget_feed_version(self) -> None:
        self._feed_version_checked = float("-inf")

    async def ensure_partitions(self, days: Iterable[date]) -> None:
        """Create the daily (UTC) vehicle_positions partitions these days need."""
        missing = sorted(set(days) - self._partitions)
        if not missing:
            return
        async with self.pool.connection() as conn:
            for day in missing:
                await conn.execute(
                    sql.SQL(
                        "CREATE TABLE IF NOT EXISTS {} PARTITION OF vehicle_positions "
                        "FOR VALUES FROM ({}) TO ({})"
                    ).format(
                        sql.Identifier(f"vehicle_positions_{day:%Y%m%d}"),
                        sql.Literal(f"{day} 00:00:00+00"),
                        sql.Literal(f"{day + timedelta(days=1)} 00:00:00+00"),
                    )
                )
                self._partitions.add(day)

    async def insert_pings(
        self, pings: list[VehiclePing], fetched_at: datetime, feed_version_id: int | None
    ) -> int:
        """Store pings; repeats of a (vehicle, GPS time) already stored are skipped.

        Returns how many new rows were written.
        """
        if not pings:
            return 0
        await self.ensure_partitions(p.gps_ts.date() for p in pings)
        rows = [
            {
                "vehicle_id": p.vehicle_id,
                "gps_ts": p.gps_ts,
                "fetched_at": fetched_at,
                "lat": p.lat,
                "lon": p.lon,
                "bearing": p.bearing,
                "speed": p.speed,
                "trip_id": p.trip_id,
                "route_id": p.route_id,
                "service_date": p.service_date,
                "direction_id": p.direction_id,
                "stop_id": p.stop_id,
                "current_stop_sequence": p.current_stop_sequence,
                "current_status": p.current_status,
                "feed_version_id": feed_version_id,
            }
            for p in pings
        ]
        async with self.pool.connection() as conn, conn.cursor() as cur:
            await cur.executemany(INSERT_PING, rows)
            return cur.rowcount

    async def upsert_trip_statuses(
        self, updates: list[TripStatusUpdate], seen: datetime, feed_version_id: int | None
    ) -> None:
        if not updates:
            return
        rows = [
            {
                "service_date": u.service_date,
                "trip_id": u.trip_id,
                "route_id": u.route_id,
                "feed_version_id": feed_version_id,
                "status": u.status,
                "vehicle_id": u.vehicle_id,
                "seen": seen,
            }
            for u in updates
        ]
        async with self.pool.connection() as conn, conn.cursor() as cur:
            await cur.executemany(UPSERT_TRIP_STATUS, rows)

    async def insert_raw_trip_updates(
        self, fetched_at: datetime, entity_count: int, content: bytes
    ) -> None:
        async with self.pool.connection() as conn:
            await conn.execute(
                "INSERT INTO trip_update_raw (fetched_at, entity_count, payload) "
                "VALUES (%s, %s, %s)",
                (fetched_at, entity_count, gzip.compress(content)),
            )

    async def record_run(
        self,
        feed: str,
        started_at: datetime,
        duration_ms: int,
        http_status: int | None,
        ok: bool,
        entity_count: int | None,
        error: str | None,
    ) -> None:
        async with self.pool.connection() as conn:
            await conn.execute(
                "INSERT INTO ingest_runs (feed, started_at, duration_ms, http_status, ok, "
                "entity_count, error) VALUES (%s, %s, %s, %s, %s, %s, %s)",
                (feed, started_at, duration_ms, http_status, ok, entity_count, error),
            )

    async def prune(self, raw_retention_days: int, runs_retention_days: int = 30) -> None:
        """Delete raw trip-update payloads and ingest logs past their retention."""
        async with self.pool.connection() as conn:
            await conn.execute(
                "DELETE FROM trip_update_raw WHERE fetched_at < now() - make_interval(days => %s)",
                (raw_retention_days,),
            )
            await conn.execute(
                "DELETE FROM ingest_runs WHERE started_at < now() - make_interval(days => %s)",
                (runs_retention_days,),
            )
