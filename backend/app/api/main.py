"""FastAPI app: live vehicles from Redis, schedule data from Postgres.

Shared clients (Redis, the Postgres pool, the update broadcaster) are created once in
`lifespan` and kept on `app.state`.
"""

import asyncio
import contextlib
from collections.abc import AsyncIterator

from fastapi import FastAPI
from psycopg_pool import AsyncConnectionPool
from redis.asyncio import Redis

from app.api import live, schedule
from app.config import Settings, get_settings


def create_app(settings: Settings | None = None) -> FastAPI:
    @contextlib.asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        cfg = settings or get_settings()
        app.state.settings = cfg
        app.state.redis = Redis.from_url(cfg.redis_url, decode_responses=True)
        app.state.broadcaster = live.Broadcaster(app.state.redis)
        ready = asyncio.Event()
        relay = asyncio.create_task(app.state.broadcaster.run(ready))
        try:
            async with AsyncConnectionPool(
                cfg.psycopg_dsn, min_size=1, max_size=5, open=False
            ) as pool:
                app.state.pool = pool
                # Start serving once the update relay is subscribed (or after 5s regardless).
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(ready.wait(), 5)
                yield
        finally:
            relay.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await relay
            await app.state.redis.aclose()

    app = FastAPI(title="Ghost Bus Miami API", lifespan=lifespan)
    app.include_router(live.router)
    app.include_router(schedule.router)

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
