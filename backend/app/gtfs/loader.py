"""Load Miami-Dade's static GTFS zip into Postgres as a new feed version.

Usage:
    python -m app.gtfs.loader                # download the current zip and load it
    python -m app.gtfs.loader --file x.zip   # load a local zip

Each file is streamed with COPY into an all-text staging table whose columns mirror the
file's header, then cast into the real table with one INSERT ... SELECT. That keeps the
load fast (about a million stop_times rows) and tolerant of extra or missing columns.
"""

import argparse
import csv
import hashlib
import io
import logging
import zipfile
from pathlib import Path

import httpx
import psycopg
from psycopg import sql

from app.config import get_settings

log = logging.getLogger("gtfs.loader")

GTFS_URL = "http://www.miamidade.gov/transit/googletransit/current/google_transit.zip"

REQUIRED_FILES = ["routes", "stops", "trips", "stop_times"]
OPTIONAL_FILES = ["shapes", "calendar", "calendar_dates"]


def _secs(col: str) -> str:
    """SQL turning 'H:MM:SS' (possibly padded, possibly past 24h) into seconds."""
    t = f"btrim(s.{col})"
    return (
        f"CASE WHEN {t} = '' THEN NULL ELSE split_part({t}, ':', 1)::int * 3600"
        f" + split_part({t}, ':', 2)::int * 60 + split_part({t}, ':', 3)::int END"
    )


def _date(col: str) -> str:
    return f"to_date(s.{col}, 'YYYYMMDD')"


# For each GTFS file: target table, then {target column: SQL expression over staging "s"}.
# Columns named in OPTIONAL_COLUMNS are added to staging as NULL when the file lacks them.
OPTIONAL_COLUMNS = {
    "routes": ["route_short_name", "route_long_name", "route_color", "route_text_color"],
    "stops": ["stop_code"],
    "trips": ["trip_headsign", "direction_id", "block_id", "shape_id"],
    "stop_times": ["timepoint"],
}

TRANSFORMS: dict[str, str] = {
    "routes": """
        INSERT INTO routes (feed_version_id, route_id, short_name, long_name, route_type,
                            color, text_color)
        SELECT %(fv)s, s.route_id, nullif(s.route_short_name, ''),
               nullif(s.route_long_name, ''), s.route_type::smallint,
               nullif(s.route_color, ''), nullif(s.route_text_color, '')
        FROM stg_routes s
    """,
    "stops": """
        INSERT INTO stops (feed_version_id, stop_id, code, name, geom)
        SELECT %(fv)s, s.stop_id, nullif(s.stop_code, ''), s.stop_name,
               ST_SetSRID(ST_MakePoint(s.stop_lon::float8, s.stop_lat::float8), 4326)
        FROM stg_stops s
        WHERE btrim(s.stop_lat) <> '' AND btrim(s.stop_lon) <> ''
    """,
    "trips": """
        INSERT INTO trips (feed_version_id, trip_id, route_id, service_id, headsign,
                           direction_id, block_id, shape_id)
        SELECT %(fv)s, s.trip_id, s.route_id, s.service_id, nullif(s.trip_headsign, ''),
               nullif(s.direction_id, '')::smallint, nullif(s.block_id, ''),
               nullif(s.shape_id, '')
        FROM stg_trips s
    """,
    "stop_times": f"""
        INSERT INTO stop_times (feed_version_id, trip_id, stop_sequence, stop_id,
                                arrival_secs, departure_secs, timepoint)
        SELECT %(fv)s, s.trip_id, s.stop_sequence::int, s.stop_id,
               {_secs("arrival_time")}, {_secs("departure_time")},
               nullif(s.timepoint, '') = '1'
        FROM stg_stop_times s
    """,
    "shapes": """
        INSERT INTO shapes (feed_version_id, shape_id, geom)
        SELECT %(fv)s, s.shape_id,
               ST_MakeLine(
                   ST_SetSRID(ST_MakePoint(s.shape_pt_lon::float8, s.shape_pt_lat::float8), 4326)
                   ORDER BY s.shape_pt_sequence::int)
        FROM stg_shapes s
        GROUP BY s.shape_id
        HAVING count(*) >= 2
    """,
    "calendar": f"""
        INSERT INTO calendar (feed_version_id, service_id, monday, tuesday, wednesday,
                              thursday, friday, saturday, sunday, start_date, end_date)
        SELECT %(fv)s, s.service_id, s.monday = '1', s.tuesday = '1', s.wednesday = '1',
               s.thursday = '1', s.friday = '1', s.saturday = '1', s.sunday = '1',
               {_date("start_date")}, {_date("end_date")}
        FROM stg_calendar s
    """,
    "calendar_dates": f"""
        INSERT INTO calendar_dates (feed_version_id, service_id, date, exception_type)
        SELECT %(fv)s, s.service_id, {_date("date")}, s.exception_type::smallint
        FROM stg_calendar_dates s
    """,
}


def _read_header(raw: io.BufferedIOBase) -> list[str]:
    """Consume the first line of a GTFS file and return its column names."""
    line = raw.readline().decode("utf-8-sig")
    return [name.strip() for name in next(csv.reader([line]))]


def _copy_file(cur: psycopg.Cursor, archive: zipfile.ZipFile, name: str) -> None:
    """Create stg_<name> with one text column per header column and COPY the file in."""
    staging = sql.Identifier(f"stg_{name}")
    with archive.open(f"{name}.txt") as raw:
        header = _read_header(raw)
        columns = header + [c for c in OPTIONAL_COLUMNS.get(name, []) if c not in header]
        cur.execute(
            sql.SQL("CREATE TEMP TABLE {} ({}) ON COMMIT DROP").format(
                staging,
                sql.SQL(", ").join(sql.SQL("{} text").format(sql.Identifier(c)) for c in columns),
            )
        )
        copy_sql = sql.SQL("COPY {} ({}) FROM STDIN WITH (FORMAT csv)").format(
            staging, sql.SQL(", ").join(sql.Identifier(c) for c in header)
        )
        with cur.copy(copy_sql) as copy:
            while chunk := raw.read(1 << 16):
                copy.write(chunk)


def load_gtfs(zip_bytes: bytes, source_url: str, dsn: str) -> int | None:
    """Load a GTFS zip as a new active feed version.

    Returns the new feed_version id, or None if this exact zip was already loaded.
    Everything runs in one transaction, so a failed load leaves the database untouched.
    """
    digest = hashlib.sha256(zip_bytes).hexdigest()
    archive = zipfile.ZipFile(io.BytesIO(zip_bytes))
    present = {Path(n).stem for n in archive.namelist() if n.endswith(".txt")}
    missing = [f for f in REQUIRED_FILES if f not in present]
    if missing:
        raise ValueError(f"GTFS zip is missing required files: {missing}")

    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        cur.execute("SELECT id FROM feed_versions WHERE sha256 = %s", (digest,))
        if cur.fetchone():
            log.info("feed %s already loaded, nothing to do", digest[:12])
            return None

        cur.execute(
            "INSERT INTO feed_versions (sha256, source_url) VALUES (%s, %s) RETURNING id",
            (digest, source_url),
        )
        feed_version_id = cur.fetchone()[0]

        for name in REQUIRED_FILES + [f for f in OPTIONAL_FILES if f in present]:
            _copy_file(cur, archive, name)
            cur.execute(TRANSFORMS[name], {"fv": feed_version_id})
            log.info("loaded %s: %d rows", name, cur.rowcount)

        # The version's date range spans every service calendar and exception date.
        cur.execute(
            """
            UPDATE feed_versions SET start_date = r.lo, end_date = r.hi
            FROM (
                SELECT min(d) AS lo, max(d) AS hi FROM (
                    SELECT start_date AS d FROM calendar WHERE feed_version_id = %(fv)s
                    UNION ALL SELECT end_date FROM calendar WHERE feed_version_id = %(fv)s
                    UNION ALL SELECT date FROM calendar_dates WHERE feed_version_id = %(fv)s
                ) dates
            ) r
            WHERE id = %(fv)s
            """,
            {"fv": feed_version_id},
        )
        cur.execute("UPDATE feed_versions SET is_active = false WHERE is_active")
        cur.execute("UPDATE feed_versions SET is_active = true WHERE id = %s", (feed_version_id,))
        log.info("feed version %d is now active", feed_version_id)
        return feed_version_id


def download(url: str = GTFS_URL) -> bytes:
    response = httpx.get(url, follow_redirects=True, timeout=120)
    response.raise_for_status()
    return response.content


def main() -> None:
    parser = argparse.ArgumentParser(description="Load static GTFS into Postgres")
    parser.add_argument("--url", default=GTFS_URL, help="GTFS zip URL")
    parser.add_argument("--file", type=Path, help="load a local zip instead of downloading")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

    if args.file:
        zip_bytes, source = args.file.read_bytes(), str(args.file)
    else:
        log.info("downloading %s", args.url)
        zip_bytes, source = download(args.url), args.url

    load_gtfs(zip_bytes, source, get_settings().psycopg_dsn)


if __name__ == "__main__":
    main()
