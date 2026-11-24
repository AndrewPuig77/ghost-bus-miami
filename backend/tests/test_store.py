"""Integration tests for the worker's Postgres writes (needs the scratch database)."""

import gzip
from datetime import UTC, date, datetime, timedelta

import psycopg
import pytest
from psycopg_pool import AsyncConnectionPool

from app.worker.parse import TripStatusUpdate, VehiclePing
from app.worker.store import Store

pytestmark = pytest.mark.anyio

NOW = datetime(2026, 11, 13, 23, 59, 50, tzinfo=UTC)


def one(dsn: str, query: str):
    with psycopg.connect(dsn) as conn:
        return conn.execute(query).fetchone()


@pytest.fixture
async def store(dsn):
    async with AsyncConnectionPool(dsn, min_size=1, max_size=2, open=False) as pool:
        yield Store(pool)


async def test_pings_dedupe_and_daily_partitions(store, dsn):
    pings = [
        VehiclePing("21165", NOW, 25.7, -80.3, trip_id="6315472", service_date=date(2026, 11, 13)),
        VehiclePing("20213", NOW + timedelta(seconds=20), 25.8, -80.25),  # next UTC day
    ]
    assert await store.insert_pings(pings, NOW, None) == 2
    # The same GPS timestamps again (a frozen bus) add nothing.
    assert await store.insert_pings(pings, NOW + timedelta(seconds=15), None) == 0

    later = [VehiclePing("21165", NOW + timedelta(seconds=15), 25.71, -80.3)]
    assert await store.insert_pings(later, NOW + timedelta(seconds=15), None) == 1

    assert one(dsn, "SELECT count(*) FROM vehicle_positions")[0] == 3
    # NOW is 23:59:50 UTC, so the two later pings land in the next day's partition.
    assert one(dsn, "SELECT count(*) FROM vehicle_positions_20261113")[0] == 1
    assert one(dsn, "SELECT count(*) FROM vehicle_positions_20261114")[0] == 2


async def test_trip_status_remembers_cancellation(store, dsn):
    day = date(2026, 11, 13)

    async def report(status: str, vehicle: str | None, at: datetime) -> None:
        update = TripStatusUpdate(day, "T1", "31120", status, vehicle)
        await store.upsert_trip_statuses([update], at, None)

    await report("scheduled", "21165", NOW)
    await report("canceled", None, NOW + timedelta(minutes=1))
    await report("scheduled", None, NOW + timedelta(minutes=2))  # agency reinstated it

    status, vehicle, first, last, canceled = one(
        dsn,
        "SELECT status, vehicle_id, first_seen_at, last_seen_at, canceled_seen_at "
        "FROM trip_status WHERE trip_id = 'T1'",
    )
    assert status == "scheduled"
    assert vehicle == "21165"  # kept when later reports omit the vehicle
    assert first == NOW and last == NOW + timedelta(minutes=2)
    assert canceled == NOW + timedelta(minutes=1)


async def test_raw_payloads_runs_and_pruning(store, dsn):
    recent = datetime.now(UTC)
    old = recent - timedelta(days=4)
    await store.insert_raw_trip_updates(old, 1, b"old feed")
    await store.insert_raw_trip_updates(recent, 2, b"new feed")
    await store.record_run(
        "gtfs-rt-trip-updates", old - timedelta(days=30), 120, 200, True, 2, None
    )
    await store.record_run("gtfs-rt-trip-updates", recent, 95, 429, False, None, "rate limited")

    await store.prune(raw_retention_days=3)

    payload = one(dsn, "SELECT payload FROM trip_update_raw")[0]
    assert one(dsn, "SELECT count(*) FROM trip_update_raw")[0] == 1
    assert gzip.decompress(payload) == b"new feed"
    assert one(dsn, "SELECT count(*), bool_and(NOT ok) FROM ingest_runs") == (1, True)
