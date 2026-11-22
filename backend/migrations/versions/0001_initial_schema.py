"""Initial schema: static GTFS tables, vehicle pings, trip status, ingest log.

Revision ID: 0001
Revises:
Create Date: 2026-11-13
"""

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

UPGRADE = """
CREATE EXTENSION IF NOT EXISTS postgis;

-- One row per downloaded static GTFS zip. Every schedule row and every ping points at one,
-- so history still joins after the county publishes a new schedule.
CREATE TABLE feed_versions (
    id          serial PRIMARY KEY,
    sha256      text NOT NULL UNIQUE,
    source_url  text NOT NULL,
    fetched_at  timestamptz NOT NULL DEFAULT now(),
    start_date  date,
    end_date    date,
    is_active   boolean NOT NULL DEFAULT false
);
CREATE UNIQUE INDEX feed_versions_one_active ON feed_versions (is_active) WHERE is_active;

CREATE TABLE routes (
    feed_version_id int NOT NULL REFERENCES feed_versions ON DELETE CASCADE,
    route_id        text NOT NULL,
    short_name      text,
    long_name       text,
    route_type      smallint,
    color           text,
    text_color      text,
    PRIMARY KEY (feed_version_id, route_id)
);

CREATE TABLE stops (
    feed_version_id int NOT NULL REFERENCES feed_versions ON DELETE CASCADE,
    stop_id         text NOT NULL,
    code            text,
    name            text,
    geom            geography(Point, 4326) NOT NULL,
    PRIMARY KEY (feed_version_id, stop_id)
);
CREATE INDEX stops_geom_idx ON stops USING gist (geom);

CREATE TABLE shapes (
    feed_version_id int NOT NULL REFERENCES feed_versions ON DELETE CASCADE,
    shape_id        text NOT NULL,
    geom            geometry(LineString, 4326) NOT NULL,
    PRIMARY KEY (feed_version_id, shape_id)
);

CREATE TABLE trips (
    feed_version_id int NOT NULL REFERENCES feed_versions ON DELETE CASCADE,
    trip_id         text NOT NULL,
    route_id        text NOT NULL,
    service_id      text NOT NULL,
    headsign        text,
    direction_id    smallint,
    block_id        text,
    shape_id        text,
    PRIMARY KEY (feed_version_id, trip_id)
);
CREATE INDEX trips_route_idx ON trips (feed_version_id, route_id);
CREATE INDEX trips_service_idx ON trips (feed_version_id, service_id);

-- Times are seconds since the start of the service day, so "25:10:00" (1:10am on the
-- next calendar day, same service day) is simply 90600.
CREATE TABLE stop_times (
    feed_version_id int NOT NULL REFERENCES feed_versions ON DELETE CASCADE,
    trip_id         text NOT NULL,
    stop_sequence   int NOT NULL,
    stop_id         text NOT NULL,
    arrival_secs    int,
    departure_secs  int,
    timepoint       boolean,
    PRIMARY KEY (feed_version_id, trip_id, stop_sequence)
);
CREATE INDEX stop_times_stop_idx ON stop_times (feed_version_id, stop_id);

CREATE TABLE calendar (
    feed_version_id int NOT NULL REFERENCES feed_versions ON DELETE CASCADE,
    service_id      text NOT NULL,
    monday boolean NOT NULL, tuesday boolean NOT NULL, wednesday boolean NOT NULL,
    thursday boolean NOT NULL, friday boolean NOT NULL, saturday boolean NOT NULL,
    sunday boolean NOT NULL,
    start_date      date NOT NULL,
    end_date        date NOT NULL,
    PRIMARY KEY (feed_version_id, service_id)
);

CREATE TABLE calendar_dates (
    feed_version_id int NOT NULL REFERENCES feed_versions ON DELETE CASCADE,
    service_id      text NOT NULL,
    date            date NOT NULL,
    exception_type  smallint NOT NULL,  -- 1 = service added, 2 = service removed
    PRIMARY KEY (feed_version_id, service_id, date)
);

-- Every GPS ping. The primary key drops repeats of the same GPS timestamp, which is also
-- how a frozen bus shows up. Daily partitions are created by the worker.
CREATE TABLE vehicle_positions (
    vehicle_id            text NOT NULL,
    gps_ts                timestamptz NOT NULL,
    fetched_at            timestamptz NOT NULL,
    lat                   double precision NOT NULL,
    lon                   double precision NOT NULL,
    bearing               real,
    speed                 real,
    trip_id               text,
    route_id              text,
    service_date          date,
    direction_id          smallint,
    stop_id               text,
    current_stop_sequence int,
    current_status        smallint,
    feed_version_id       int REFERENCES feed_versions,
    PRIMARY KEY (vehicle_id, gps_ts)
) PARTITION BY RANGE (gps_ts);
CREATE INDEX vehicle_positions_trip_idx ON vehicle_positions (service_date, trip_id, gps_ts);

-- One row per trip per service day, as reported by the trip updates feed.
CREATE TABLE trip_status (
    service_date     date NOT NULL,
    trip_id          text NOT NULL,
    route_id         text,
    feed_version_id  int REFERENCES feed_versions,
    status           text NOT NULL CHECK (status IN ('scheduled', 'canceled', 'added')),
    vehicle_id       text,
    first_seen_at    timestamptz NOT NULL,
    last_seen_at     timestamptz NOT NULL,
    canceled_seen_at timestamptz,
    PRIMARY KEY (service_date, trip_id)
);
CREATE INDEX trip_status_route_idx ON trip_status (service_date, route_id);

-- Raw trip-update feeds (gzip), kept for a few days so stop arrivals can be re-derived.
CREATE TABLE trip_update_raw (
    fetched_at    timestamptz PRIMARY KEY,
    entity_count  int NOT NULL,
    payload       bytea NOT NULL
);

-- One row per poll. Drives the worker heartbeat and the "live data down" banner.
CREATE TABLE ingest_runs (
    id            bigserial PRIMARY KEY,
    feed          text NOT NULL,
    started_at    timestamptz NOT NULL,
    duration_ms   int NOT NULL,
    http_status   int,
    ok            boolean NOT NULL,
    entity_count  int,
    error         text
);
CREATE INDEX ingest_runs_feed_idx ON ingest_runs (feed, started_at DESC);
"""

DOWNGRADE = """
DROP TABLE ingest_runs, trip_update_raw, trip_status, vehicle_positions, calendar_dates,
    calendar, stop_times, trips, shapes, stops, routes, feed_versions;
"""


def upgrade() -> None:
    op.execute(UPGRADE)


def downgrade() -> None:
    op.execute(DOWNGRADE)
