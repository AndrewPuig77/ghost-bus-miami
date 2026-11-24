"""Live vehicle data from Redis: a snapshot endpoint, feed health, and a WebSocket stream.

The worker publishes each poll's moved vehicles on `vehicles:updates`. The API holds one
Redis subscription and fans every message out to all connected browsers through small
per-client queues; a client too slow to keep up is disconnected rather than allowed to
fall behind or hold up the others.
"""

import asyncio
import contextlib
import json
import logging
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Request, WebSocket, WebSocketDisconnect
from redis.asyncio import Redis

from app.worker.live_cache import LATEST_KEY, UPDATES_CHANNEL

log = logging.getLogger("api.live")
router = APIRouter()

CLIENT_QUEUE_SIZE = 16


def utcnow() -> datetime:
    return datetime.now(UTC)


class Broadcaster:
    """Relays the Redis update channel to every subscribed client queue."""

    def __init__(self, redis: Redis) -> None:
        self.redis = redis
        self.clients: set[asyncio.Queue[str | None]] = set()

    def subscribe(self) -> asyncio.Queue[str | None]:
        queue: asyncio.Queue[str | None] = asyncio.Queue(CLIENT_QUEUE_SIZE)
        self.clients.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue[str | None]) -> None:
        self.clients.discard(queue)

    def broadcast(self, text: str) -> None:
        for queue in list(self.clients):
            try:
                queue.put_nowait(text)
            except asyncio.QueueFull:
                # Too slow: drop it. None tells its handler to close the socket.
                self.clients.discard(queue)
                with contextlib.suppress(asyncio.QueueEmpty):
                    queue.get_nowait()
                queue.put_nowait(None)

    async def run(self, ready: asyncio.Event) -> None:
        """Forward messages until cancelled, resubscribing if Redis drops the connection."""
        while True:
            try:
                async with self.redis.pubsub() as pubsub:
                    await pubsub.subscribe(UPDATES_CHANNEL)
                    ready.set()
                    async for message in pubsub.listen():
                        if message["type"] == "message":
                            self.broadcast(update_message(message["data"]))
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("redis subscription failed; retrying in 5s")
                await asyncio.sleep(5)


def update_message(raw: str) -> str:
    msg = json.loads(raw)
    msg["type"] = "update"
    msg["server_time"] = utcnow().isoformat()
    return json.dumps(msg)


async def current_vehicles(redis: Redis, max_age: timedelta) -> list[dict]:
    """Newest ping per vehicle, leaving out vehicles not heard from within max_age."""
    cutoff = utcnow() - max_age
    vehicles = []
    for raw in (await redis.hgetall(LATEST_KEY)).values():
        v = json.loads(raw)
        if datetime.fromisoformat(v["gps_ts"]) >= cutoff:
            vehicles.append(v)
    vehicles.sort(key=lambda v: v["vehicle_id"])
    return vehicles


async def snapshot(request_or_ws: Request | WebSocket) -> dict:
    state = request_or_ws.app.state
    max_age = timedelta(seconds=state.settings.vehicle_max_age_s)
    return {
        "type": "snapshot",
        "server_time": utcnow().isoformat(),
        "vehicles": await current_vehicles(state.redis, max_age),
    }


@router.get("/api/vehicles")
async def vehicles(request: Request) -> dict:
    return await snapshot(request)


@router.get("/api/status")
async def status(request: Request) -> dict:
    """Health of each Swiftly feed as last recorded by the worker."""
    redis: Redis = request.app.state.redis
    feeds = {}
    async for key in redis.scan_iter(match="feed:*:status"):
        name = key.removeprefix("feed:").removesuffix(":status")
        status = await redis.hgetall(key)
        feeds[name] = {
            "last_attempt": status.get("last_attempt") or None,
            "last_ok": status.get("last_ok") or None,
            "last_error": status.get("last_error") or None,
        }
    return {"server_time": utcnow().isoformat(), "feeds": dict(sorted(feeds.items()))}


@router.websocket("/ws/vehicles")
async def vehicles_ws(ws: WebSocket) -> None:
    broadcaster: Broadcaster = ws.app.state.broadcaster
    await ws.accept()
    # Subscribe before reading the snapshot so nothing published in between is missed.
    queue = broadcaster.subscribe()
    try:
        await ws.send_text(json.dumps(await snapshot(ws)))
        while (text := await queue.get()) is not None:
            await ws.send_text(text)
        await ws.close(code=1013)  # try again later: client fell behind
    except WebSocketDisconnect:
        pass
    finally:
        broadcaster.unsubscribe(queue)
