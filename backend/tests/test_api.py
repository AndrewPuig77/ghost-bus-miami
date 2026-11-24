import asyncio
import json
from datetime import UTC, datetime, timedelta

import psycopg
import pytest
import redis
from fastapi.testclient import TestClient

from app.api.live import Broadcaster
from app.api.main import create_app
from app.config import Settings
from app.worker.live_cache import LATEST_KEY, UPDATES_CHANNEL

LINE = "LINESTRING(-80.2 25.7, -80.19 25.71, -80.18 25.72)"


@pytest.fixture(scope="module")
def schedule_db(dsn):
    with psycopg.connect(dsn) as conn:
        fv = conn.execute(
            "INSERT INTO feed_versions (sha256, source_url, is_active) "
            "VALUES ('abc', 'test', true) RETURNING id"
        ).fetchone()[0]
        for route_id, name in [("r11", "11"), ("r2", "2"), ("rA", "A"), ("r101", "101")]:
            conn.execute(
                "INSERT INTO routes (feed_version_id, route_id, short_name, long_name) "
                "VALUES (%s, %s, %s, %s)",
                (fv, route_id, name, f"Route {name}"),
            )
        conn.execute("INSERT INTO shapes VALUES (%s, 's1', ST_GeomFromText(%s, 4326))", (fv, LINE))
        for trip_id in ("t1", "t2"):
            conn.execute(
                "INSERT INTO trips (feed_version_id, trip_id, route_id, service_id, headsign, "
                "direction_id, shape_id) VALUES (%s, %s, 'r2', 'wk', 'Downtown', 0, 's1')",
                (fv, trip_id),
            )
    return dsn


@pytest.fixture
def client(schedule_db, redis_url):
    app = create_app(Settings(database_url=schedule_db, redis_url=redis_url))
    with TestClient(app) as c:
        yield c


@pytest.fixture
def r(redis_url):
    client = redis.Redis.from_url(redis_url, decode_responses=True)
    yield client
    client.close()


def ping(vehicle_id: str, age: timedelta) -> dict:
    return {
        "vehicle_id": vehicle_id,
        "gps_ts": (datetime.now(UTC) - age).isoformat(),
        "lat": 25.77,
        "lon": -80.19,
        "bearing": None,
        "speed": None,
        "trip_id": None,
        "route_id": "r2",
        "direction_id": None,
        "stop_id": None,
    }


def test_routes_in_number_order(client) -> None:
    names = [route["short_name"] for route in client.get("/api/routes").json()]
    assert names == ["2", "11", "101", "A"]


def test_route_shapes_as_geojson(client) -> None:
    body = client.get("/api/routes/r2/shapes").json()
    [feature] = body["features"]
    assert feature["geometry"]["type"] == "LineString"
    assert len(feature["geometry"]["coordinates"]) == 3
    assert feature["properties"] == {
        "shape_id": "s1",
        "direction_id": 0,
        "headsign": "Downtown",
        "trips": 2,
    }
    assert client.get("/api/routes/r11/shapes").json()["features"] == []
    assert client.get("/api/routes/nope/shapes").status_code == 404


def test_vehicles_leave_out_stale(client, r) -> None:
    r.hset(
        LATEST_KEY,
        mapping={
            "fresh": json.dumps(ping("fresh", timedelta(seconds=20))),
            "old": json.dumps(ping("old", timedelta(hours=2))),
        },
    )
    body = client.get("/api/vehicles").json()
    assert [v["vehicle_id"] for v in body["vehicles"]] == ["fresh"]
    assert body["type"] == "snapshot" and "server_time" in body


def test_status_lists_feeds(client, r) -> None:
    r.hset("feed:gtfs-rt-vehicle-positions:status", mapping={"last_ok": "x", "last_error": ""})
    feeds = client.get("/api/status").json()["feeds"]
    assert feeds == {
        "gtfs-rt-vehicle-positions": {"last_attempt": None, "last_ok": "x", "last_error": None}
    }


def test_websocket_sends_snapshot_then_updates(client, r) -> None:
    r.hset(LATEST_KEY, "bus1", json.dumps(ping("bus1", timedelta(seconds=5))))
    with client.websocket_connect("/ws/vehicles") as ws:
        first = ws.receive_json()
        assert first["type"] == "snapshot"
        assert [v["vehicle_id"] for v in first["vehicles"]] == ["bus1"]

        update = {"fetched_at": "now", "vehicles": [ping("bus2", timedelta(0))]}
        r.publish(UPDATES_CHANNEL, json.dumps(update))
        # Pub/sub channels span Redis databases, so a locally running worker's updates
        # may arrive too; skip past them.
        for _ in range(10):
            msg = ws.receive_json()
            assert msg["type"] == "update"
            if [v["vehicle_id"] for v in msg["vehicles"]] == ["bus2"]:
                break
        else:
            pytest.fail("published update never arrived")


def test_slow_client_is_dropped() -> None:
    async def scenario() -> None:
        b = Broadcaster(redis=None)  # type: ignore[arg-type]
        slow, fast = b.subscribe(), b.subscribe()
        for i in range(20):
            b.broadcast(str(i))
            while not fast.empty():
                fast.get_nowait()
        assert slow not in b.clients and fast in b.clients
        # The slow client's queue ends with the signal to close.
        items = [slow.get_nowait() for _ in range(slow.qsize())]
        assert items[-1] is None

    asyncio.run(scenario())
