"""Integration test: migrate a scratch database, load a tiny GTFS zip, check the rows.

Needs the Compose Postgres running on localhost:5432; skipped otherwise.
"""

import io
import os
import zipfile

import psycopg
import pytest
from alembic import command
from alembic.config import Config

from app.gtfs.loader import load_gtfs

ADMIN_DSN = os.environ.get(
    "TEST_ADMIN_DSN", "postgresql://ghostbus:change-me@localhost:5432/ghostbus"
)
TEST_DB = "ghostbus_test"

FILES = {
    # BOM, CRLF line endings and space-padded times mirror the real Miami-Dade feed.
    "routes.txt": "﻿route_id,route_short_name,route_long_name,route_type,route_color\r\n"
    "R1,37,HIALEAH-SO.MIAMI,3,004000\r\n",
    "stops.txt": "stop_id,stop_code,stop_name,stop_lat,stop_lon\r\n"
    "S1,A,First St,25.77,-80.19\r\nS2,,Second St,25.78,-80.20\r\n",
    "trips.txt": "route_id,service_id,trip_id,trip_headsign,direction_id,shape_id\r\n"
    "R1,WK,T1,DOWNTOWN,0,SH1\r\nR1,WK,T2,,1,\r\n",
    "stop_times.txt": "trip_id,arrival_time,departure_time,stop_id,stop_sequence,timepoint\r\n"
    "T1, 5:32:00, 5:32:30,S1,1,1\r\nT1,25:10:00,25:10:00,S2,2,0\r\nT2,,,S1,1,\r\n",
    "shapes.txt": "shape_id,shape_pt_lat,shape_pt_lon,shape_pt_sequence\r\n"
    "SH1,25.78,-80.20,2\r\nSH1,25.77,-80.19,1\r\n",
    "calendar.txt": "service_id,monday,tuesday,wednesday,thursday,friday,saturday,sunday,"
    "start_date,end_date\r\nWK,1,1,1,1,1,0,0,20260720,20261122\r\n",
    "calendar_dates.txt": "service_id,date,exception_type\r\nWK,20261126,2\r\n",
}


def make_zip(files: dict[str, str]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, text in files.items():
            archive.writestr(name, text.encode("utf-8"))
    return buffer.getvalue()


@pytest.fixture(scope="module")
def dsn():
    try:
        admin = psycopg.connect(ADMIN_DSN, autocommit=True, connect_timeout=3)
    except psycopg.OperationalError:
        pytest.skip("Postgres is not reachable on localhost:5432")
    admin.execute(f"DROP DATABASE IF EXISTS {TEST_DB} WITH (FORCE)")
    admin.execute(f"CREATE DATABASE {TEST_DB}")

    test_dsn = ADMIN_DSN.rsplit("/", 1)[0] + f"/{TEST_DB}"
    previous = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = test_dsn.replace("postgresql://", "postgresql+psycopg://", 1)
    try:
        command.upgrade(Config("alembic.ini"), "head")
        yield test_dsn
    finally:
        if previous is None:
            del os.environ["DATABASE_URL"]
        else:
            os.environ["DATABASE_URL"] = previous
        admin.execute(f"DROP DATABASE IF EXISTS {TEST_DB} WITH (FORCE)")
        admin.close()


def one(dsn: str, query: str):
    with psycopg.connect(dsn) as conn:
        return conn.execute(query).fetchone()


def test_load_and_versioning(dsn):
    first = load_gtfs(make_zip(FILES), "test://one", dsn)
    assert first is not None

    assert one(dsn, "SELECT count(*) FROM routes")[0] == 1
    assert one(dsn, "SELECT count(*) FROM stops")[0] == 2
    assert one(dsn, "SELECT count(*) FROM trips")[0] == 2
    assert one(dsn, "SELECT count(*) FROM stop_times")[0] == 3

    # Padded and past-midnight times become seconds into the service day; blanks stay NULL.
    assert one(
        dsn,
        "SELECT arrival_secs, departure_secs, timepoint FROM stop_times "
        "WHERE trip_id = 'T1' AND stop_sequence = 1",
    ) == (5 * 3600 + 32 * 60, 5 * 3600 + 32 * 60 + 30, True)
    assert one(
        dsn, "SELECT arrival_secs FROM stop_times WHERE trip_id = 'T1' AND stop_sequence = 2"
    ) == (25 * 3600 + 10 * 60,)
    assert one(dsn, "SELECT arrival_secs FROM stop_times WHERE trip_id = 'T2'") == (None,)

    # Shape points are joined in sequence order, not file order.
    assert one(dsn, "SELECT ST_AsText(geom) FROM shapes")[0] == (
        "LINESTRING(-80.19 25.77,-80.2 25.78)"
    )
    assert one(dsn, "SELECT short_name, color FROM routes") == ("37", "004000")
    assert one(dsn, "SELECT headsign, shape_id FROM trips WHERE trip_id = 'T2'") == (None, None)
    assert one(dsn, "SELECT start_date::text, end_date::text, is_active FROM feed_versions") == (
        "2026-07-20",
        "2026-11-26",
        True,
    )

    # The same zip again is a no-op.
    assert load_gtfs(make_zip(FILES), "test://one", dsn) is None
    assert one(dsn, "SELECT count(*) FROM feed_versions")[0] == 1

    # A changed zip becomes a second version; the old one is kept but no longer active.
    changed = dict(FILES)
    changed["trips.txt"] += "R1,WK,T3,DOWNTOWN,0,SH1\r\n"
    second = load_gtfs(make_zip(changed), "test://two", dsn)
    assert second is not None and second != first
    assert one(dsn, "SELECT count(*) FROM trips")[0] == 5
    assert one(dsn, "SELECT id FROM feed_versions WHERE is_active")[0] == second


def test_missing_required_file(dsn):
    files = {k: v for k, v in FILES.items() if k != "stop_times.txt"}
    with pytest.raises(ValueError, match="stop_times"):
        load_gtfs(make_zip(files), "test://bad", dsn)
