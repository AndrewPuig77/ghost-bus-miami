# Ghost Bus Miami

> GO Miami-Dade shows where your bus is. This shows whether you can count on it.

A web app built on Miami-Dade Transit's live data. It shows a live bus map, stores every GPS
ping, and uses that history to measure reliability: ghost buses, lateness, bunching, and
arrival ranges with confidence.

**Status:** early. The database schema and the static GTFS loader work; live ingestion and
the map are not built yet.

## Stack

- **Backend:** Python 3.13, FastAPI, an asyncio ingestion worker
- **Data:** PostgreSQL + PostGIS (history), Redis (live cache and pub/sub)
- **Frontend:** React + TypeScript + Vite + Leaflet (not started)
- **Sources:** Swiftly GTFS-realtime feeds, Miami-Dade static GTFS

## Layout

```
backend/
  app/
    api/         FastAPI routes and WebSocket
    worker/      Swiftly polling loop
    gtfs/        static GTFS loader
    detection/   ghost, lateness and bunching jobs
    db/          models and session
    config.py    settings from environment
  migrations/    database migrations
  tests/
frontend/        React app
docker-compose.yml
```

## Run it

Requires Docker Desktop.

```sh
cp .env.example .env    # then set SWIFTLY_API_KEY and a Postgres password
docker compose up --build
```

The API answers at http://localhost:8000/health. Database migrations run automatically on
startup (the `migrate` service).

Load the static schedule (safe to re-run; an unchanged zip is skipped):

```sh
docker compose run --rm api python -m app.gtfs.loader
```

Run the tests inside a container, against the Compose database:

```sh
docker compose run --rm -v ./backend:/src -w /src \
  -e UV_PROJECT_ENVIRONMENT=/tmp/venv -e UV_LINK_MODE=copy \
  -e TEST_ADMIN_DSN=postgresql://ghostbus:change-me@db:5432/ghostbus \
  api uv run pytest
```

## Develop the backend without Docker

Requires [uv](https://docs.astral.sh/uv/).

```sh
cd backend
uv sync
uv run pytest
uv run ruff check .
uv run uvicorn app.api.main:app --reload
```
