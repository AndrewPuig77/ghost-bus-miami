"""Ingestion worker: polls Swiftly 24/7 and records everything it sees.

Three independent loops run concurrently:
    positions      vehicle positions every 15s -> Postgres pings + Redis live cache
    trip updates   trip updates every 30s -> trip_status + raw payloads (kept 3 days)
    gtfs refresh   static schedule once a day (a new zip becomes a new feed version)

Every Swiftly call shares one RequestBudget, and every poll is logged to ingest_runs.
"""

import asyncio
import logging
import signal
import time
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

import httpx
from psycopg_pool import AsyncConnectionPool
from redis.asyncio import Redis

from app.config import Settings, get_settings
from app.gtfs.loader import GTFS_URL, download, load_gtfs
from app.worker.live_cache import LiveCache
from app.worker.parse import (
    filter_plausible,
    parse_feed,
    parse_trip_updates,
    parse_vehicle_positions,
)
from app.worker.store import Store
from app.worker.swiftly import RequestBudget, SwiftlyClient, SwiftlyError

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logging.getLogger("httpx").setLevel(logging.WARNING)
log = logging.getLogger("worker")

POSITIONS_FEED = "gtfs-rt-vehicle-positions"
TRIP_UPDATES_FEED = "gtfs-rt-trip-updates"
MAX_BACKOFF_S = 300
PRUNE_EVERY_S = 3600


def utcnow() -> datetime:
    return datetime.now(UTC)


class Ingestor:
    def __init__(self, settings: Settings, client: SwiftlyClient, store: Store, cache: LiveCache):
        self.settings = settings
        self.client = client
        self.store = store
        self.cache = cache
        self._last_prune = float("-inf")

    async def poll_positions(self) -> tuple[int, str]:
        content = await self.client.fetch(POSITIONS_FEED)
        fetched_at = utcnow()
        feed = parse_feed(content)
        all_pings = parse_vehicle_positions(feed)
        pings = filter_plausible(all_pings, fetched_at)
        feed_version = await self.store.active_feed_version()
        new_rows = await self.store.insert_pings(pings, fetched_at, feed_version)
        moved = await self._cache_safely(self.cache.publish_positions(pings, fetched_at))
        dropped = len(all_pings) - len(pings)
        note = f"{len(pings)} vehicles, {new_rows} new pings, {moved} moved"
        return len(feed.entity), note + (f", {dropped} bad timestamps" if dropped else "")

    async def poll_trip_updates(self) -> tuple[int, str]:
        content = await self.client.fetch(TRIP_UPDATES_FEED)
        fetched_at = utcnow()
        feed = parse_feed(content)
        updates = parse_trip_updates(feed)
        feed_version = await self.store.active_feed_version()
        await self.store.upsert_trip_statuses(updates, fetched_at, feed_version)
        await self.store.insert_raw_trip_updates(fetched_at, len(feed.entity), content)
        if time.monotonic() - self._last_prune > PRUNE_EVERY_S:
            await self.store.prune(self.settings.raw_retention_days)
            self._last_prune = time.monotonic()
        canceled = sum(u.status == "canceled" for u in updates)
        return len(feed.entity), f"{len(updates)} trips, {canceled} canceled"

    async def _cache_safely(self, call: Awaitable[int]) -> int:
        """Redis trouble must never stop history from being written."""
        try:
            return await call
        except Exception:
            log.exception("redis update failed")
            return 0

    async def run_every(
        self, feed: str, interval_s: float, poll: Callable[[], Awaitable[tuple[int, str]]]
    ) -> None:
        failures = 0
        while True:
            started = time.monotonic()
            started_at = utcnow()
            ok, http_status, entities, error = False, None, None, None
            try:
                entities, note = await poll()
                ok, http_status, failures = True, 200, 0
                log.info("%s: %s (%d ms)", feed, note, (time.monotonic() - started) * 1000)
            except SwiftlyError as exc:
                http_status, error = exc.status, str(exc)
                failures += 1
                log.warning("%s: %s", feed, error)
            except Exception as exc:
                error = repr(exc)[:500]
                failures += 1
                log.exception("%s: poll failed", feed)

            duration_ms = int((time.monotonic() - started) * 1000)
            try:
                await self.store.record_run(
                    feed, started_at, duration_ms, http_status, ok, entities, error
                )
            except Exception:
                log.exception("could not record ingest run")
            await self._cache_safely(self.cache.set_feed_status(feed, ok, started_at, error))

            # Back off exponentially while failing: 30s, 60s, 120s ... capped at 5 minutes.
            delay = interval_s if ok else min(interval_s * 2**failures, MAX_BACKOFF_S)
            await asyncio.sleep(max(0.0, delay - (time.monotonic() - started)))

    async def refresh_gtfs_forever(self) -> None:
        while True:
            try:
                zip_bytes = await asyncio.to_thread(download, GTFS_URL)
                version = await asyncio.to_thread(
                    load_gtfs, zip_bytes, GTFS_URL, self.settings.psycopg_dsn
                )
                if version is not None:
                    self.store.forget_feed_version()
            except Exception:
                log.exception("static GTFS refresh failed; will retry in an hour")
                await asyncio.sleep(3600)
                continue
            await asyncio.sleep(self.settings.gtfs_refresh_interval_s)


async def run() -> None:
    settings = get_settings()
    if not settings.swiftly_api_key:
        raise SystemExit("SWIFTLY_API_KEY is not set")

    budget = RequestBudget(settings.swiftly_max_requests, settings.swiftly_window_s)
    redis = Redis.from_url(settings.redis_url)
    async with (
        httpx.AsyncClient(timeout=20) as http,
        AsyncConnectionPool(settings.psycopg_dsn, min_size=1, max_size=4, open=False) as pool,
    ):
        client = SwiftlyClient(
            http,
            settings.swiftly_base_url,
            settings.swiftly_agency,
            settings.swiftly_api_key,
            budget,
        )
        ingestor = Ingestor(settings, client, Store(pool), LiveCache(redis))
        log.info(
            "worker started: positions every %ss, trip updates every %ss, cap %d requests/%ds",
            settings.positions_interval_s,
            settings.trip_updates_interval_s,
            settings.swiftly_max_requests,
            settings.swiftly_window_s,
        )
        try:
            async with asyncio.TaskGroup() as tasks:
                tasks.create_task(
                    ingestor.run_every(
                        POSITIONS_FEED, settings.positions_interval_s, ingestor.poll_positions
                    )
                )
                tasks.create_task(
                    ingestor.run_every(
                        TRIP_UPDATES_FEED,
                        settings.trip_updates_interval_s,
                        ingestor.poll_trip_updates,
                    )
                )
                tasks.create_task(ingestor.refresh_gtfs_forever())
        finally:
            await redis.aclose()


def main() -> None:
    async def runner() -> None:
        task = asyncio.current_task()
        loop = asyncio.get_running_loop()
        # `docker compose stop` sends SIGTERM; cancel cleanly so open transactions roll back.
        for sig in (signal.SIGTERM, signal.SIGINT):
            try:
                loop.add_signal_handler(sig, task.cancel)
            except NotImplementedError:  # Windows
                pass
        try:
            await run()
        except asyncio.CancelledError:
            log.info("worker stopped")

    asyncio.run(runner())


if __name__ == "__main__":
    main()
