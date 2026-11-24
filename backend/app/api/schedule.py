"""Static schedule data from the active GTFS feed version: routes and their shapes."""

import re

from fastapi import APIRouter, HTTPException, Request
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

router = APIRouter()

ACTIVE_VERSION = "(SELECT id FROM feed_versions WHERE is_active)"


def route_sort_key(route: dict) -> tuple:
    """Numeric routes in number order (2, 9, 11, 101), then lettered ones."""
    name = route["short_name"] or route["route_id"]
    match = re.match(r"\d+", name)
    return (0, int(match.group()), name) if match else (1, 0, name)


async def fetch_all(pool: AsyncConnectionPool, query: str, params: tuple = ()) -> list[dict]:
    async with pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(query, params)
        return await cur.fetchall()


@router.get("/api/routes")
async def routes(request: Request) -> list[dict]:
    rows = await fetch_all(
        request.app.state.pool,
        f"""
        SELECT route_id, short_name, long_name, route_type, color, text_color
        FROM routes
        WHERE feed_version_id = {ACTIVE_VERSION}
        """,
    )
    return sorted(rows, key=route_sort_key)


@router.get("/api/routes/{route_id}/shapes")
async def route_shapes(request: Request, route_id: str) -> dict:
    """Every path the route's trips follow, as GeoJSON, busiest first."""
    pool = request.app.state.pool
    exists = await fetch_all(
        pool,
        f"SELECT 1 FROM routes WHERE feed_version_id = {ACTIVE_VERSION} AND route_id = %s",
        (route_id,),
    )
    if not exists:
        raise HTTPException(404, "unknown route")

    rows = await fetch_all(
        pool,
        f"""
        WITH used AS (
            SELECT shape_id, direction_id,
                   mode() WITHIN GROUP (ORDER BY headsign) AS headsign,
                   count(*) AS trips
            FROM trips
            WHERE feed_version_id = {ACTIVE_VERSION}
              AND route_id = %s AND shape_id IS NOT NULL
            GROUP BY shape_id, direction_id
        )
        SELECT used.shape_id, used.direction_id, used.headsign, used.trips,
               ST_AsGeoJSON(s.geom, 5)::json AS geometry
        FROM used
        JOIN shapes s ON s.feed_version_id = {ACTIVE_VERSION} AND s.shape_id = used.shape_id
        ORDER BY used.trips DESC, used.shape_id
        """,
        (route_id,),
    )
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": row.pop("geometry"),
                "properties": row,
            }
            for row in rows
        ],
    }
