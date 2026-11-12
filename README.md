# Ghost Bus Miami

> GO Miami-Dade shows where your bus is. This shows whether you can count on it.

A web app built on Miami-Dade Transit's live data. It shows a live bus map, stores every GPS
ping, and uses that history to measure reliability: ghost buses, lateness, bunching, and
arrival ranges with confidence.

**Status:** early scaffolding. Nothing below the health check is implemented yet.

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

The API answers at http://localhost:8000/health.

## Develop the backend without Docker

Requires [uv](https://docs.astral.sh/uv/).

```sh
cd backend
uv sync
uv run pytest
uv run ruff check .
uv run uvicorn app.api.main:app --reload
```
