# Ghost Bus Miami

> GO Miami-Dade shows where your bus is. This shows whether you can count on it.

A web app built on Miami-Dade Transit's live data. It shows a live bus map, stores every GPS
ping, and uses that history to measure reliability: ghost buses, lateness, bunching, and
arrival ranges with confidence.

**Status:** early. The ingestion worker records live data and the static schedule; the map
and the reliability analysis are not built yet.

## How ingestion works

The `worker` service runs three loops:

- **Vehicle positions** every 15s: each GPS ping goes to Postgres (`vehicle_positions`,
  partitioned by day; a repeated GPS timestamp is skipped). Vehicles that moved are written to
  Redis (`vehicles:latest`) and announced on the `vehicles:updates` channel.
- **Trip updates** every 30s: each trip's status (scheduled, canceled, added) goes to
  `trip_status`. The raw feed is kept gzipped in `trip_update_raw` for 3 days.
- **Static schedule** once a day: a changed GTFS zip becomes a new active feed version.

Every Swiftly request goes through one rolling budget of 150 requests per 15 minutes (Swiftly
allows 180). Failures back off exponentially, a 429 pauses all requests, and every poll is
logged to `ingest_runs`.

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
db/              Postgres + PostGIS image (x86 and ARM)
infra/           Terraform for Oracle Cloud
.github/         CI and deploy workflows
docker-compose.yml
```

## Deployment

Production runs on an Oracle Cloud Always Free ARM server, created with Terraform and
deployed by GitHub Actions after CI passes. See [infra/README.md](infra/README.md).

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
