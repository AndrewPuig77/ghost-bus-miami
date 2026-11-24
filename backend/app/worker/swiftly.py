"""Swiftly API client with a hard cap on request volume.

Swiftly allows 180 requests per 15 minutes. Every request goes through one shared
RequestBudget, so no combination of polling loops, retries or bugs can exceed the cap.
"""

import asyncio
import time
from collections import deque
from collections.abc import Callable

import httpx


class RequestBudget:
    """Allows at most `max_requests` in any rolling `window_s` seconds."""

    def __init__(
        self, max_requests: int, window_s: float, clock: Callable[[], float] = time.monotonic
    ) -> None:
        self._max = max_requests
        self._window = window_s
        self._clock = clock
        self._sent: deque[float] = deque()
        self._paused_until = 0.0
        self._lock = asyncio.Lock()

    def wait_time(self) -> float:
        """Seconds until another request is allowed (0 means now)."""
        now = self._clock()
        while self._sent and now - self._sent[0] >= self._window:
            self._sent.popleft()
        wait = max(0.0, self._paused_until - now)
        if len(self._sent) >= self._max:
            wait = max(wait, self._sent[0] + self._window - now)
        return wait

    def record(self) -> None:
        self._sent.append(self._clock())

    def pause(self, seconds: float) -> None:
        """Block all requests for a while, e.g. after a 429."""
        self._paused_until = max(self._paused_until, self._clock() + seconds)

    @property
    def used(self) -> int:
        self.wait_time()  # prunes expired entries
        return len(self._sent)

    async def acquire(self) -> None:
        async with self._lock:
            while (wait := self.wait_time()) > 0:
                await asyncio.sleep(wait)
            self.record()


class SwiftlyError(Exception):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(f"HTTP {status}: {message}")
        self.status = status


def retry_after_seconds(value: str | None, default: float = 60) -> float:
    try:
        return max(1.0, float(value)) if value else default
    except ValueError:
        return default  # HTTP-date form; not worth parsing


class SwiftlyClient:
    def __init__(
        self,
        http: httpx.AsyncClient,
        base_url: str,
        agency: str,
        api_key: str,
        budget: RequestBudget,
    ) -> None:
        self._http = http
        self._base = f"{base_url.rstrip('/')}/{agency}"
        self._headers = {"Authorization": api_key, "Accept": "application/x-protobuf"}
        self.budget = budget

    async def fetch(self, feed: str) -> bytes:
        """Fetch one GTFS-realtime feed as protobuf bytes."""
        await self.budget.acquire()
        response = await self._http.get(f"{self._base}/{feed}", headers=self._headers)
        if response.status_code == 429:
            pause = retry_after_seconds(response.headers.get("Retry-After"))
            self.budget.pause(pause)
            raise SwiftlyError(429, f"rate limited, pausing all requests for {pause:.0f}s")
        if response.status_code != 200:
            raise SwiftlyError(response.status_code, response.text[:200])
        return response.content
