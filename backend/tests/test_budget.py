import httpx
import pytest

from app.worker.swiftly import RequestBudget, SwiftlyClient, SwiftlyError, retry_after_seconds


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def test_budget_blocks_at_cap_until_oldest_request_expires():
    clock = FakeClock()
    budget = RequestBudget(max_requests=3, window_s=900, clock=clock)
    for _ in range(3):
        assert budget.wait_time() == 0
        budget.record()
        clock.now += 10
    # 3 sent at t=1000, 1010, 1020; now t=1030. The first frees up at t=1900.
    assert budget.wait_time() == pytest.approx(870)
    clock.now = 1900
    assert budget.wait_time() == 0
    assert budget.used == 2


def test_pause_blocks_even_with_budget_left():
    clock = FakeClock()
    budget = RequestBudget(max_requests=100, window_s=900, clock=clock)
    budget.pause(60)
    assert budget.wait_time() == pytest.approx(60)
    clock.now += 61
    assert budget.wait_time() == 0


def test_retry_after_parsing():
    assert retry_after_seconds("120") == 120
    assert retry_after_seconds(None) == 60
    assert retry_after_seconds("Wed, 21 Oct 2026 07:28:00 GMT") == 60
    assert retry_after_seconds("0") == 1


@pytest.mark.anyio
async def test_client_sends_key_and_pauses_on_429():
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.path.endswith("positions"):
            return httpx.Response(200, content=b"pb")
        return httpx.Response(429, headers={"Retry-After": "90"})

    clock = FakeClock()
    budget = RequestBudget(max_requests=10, window_s=900, clock=clock)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = SwiftlyClient(http, "https://api.example/real-time/", "miami", "secret", budget)
        assert await client.fetch("positions") == b"pb"
        with pytest.raises(SwiftlyError) as err:
            await client.fetch("trip-updates")

    assert err.value.status == 429
    assert str(seen[0].url) == "https://api.example/real-time/miami/positions"
    assert seen[0].headers["Authorization"] == "secret"
    assert budget.used == 2
    assert budget.wait_time() == pytest.approx(90)
