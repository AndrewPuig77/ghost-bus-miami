"""Shared fixtures.

`dsn` gives each test module a freshly migrated scratch database. It needs Postgres
(the Compose `db` service by default, or TEST_ADMIN_DSN); tests using it are skipped
when Postgres is unreachable.
"""

import os

import psycopg
import pytest
import redis
from alembic import command
from alembic.config import Config

ADMIN_DSN = os.environ.get(
    "TEST_ADMIN_DSN", "postgresql://ghostbus:change-me@localhost:5432/ghostbus"
)
TEST_DB = "ghostbus_test"


@pytest.fixture(scope="module")
def dsn():
    try:
        admin = psycopg.connect(ADMIN_DSN, autocommit=True, connect_timeout=3)
    except psycopg.OperationalError:
        pytest.skip("Postgres is not reachable")
    admin.execute(f"DROP DATABASE IF EXISTS {TEST_DB} WITH (FORCE)")
    admin.execute(f"CREATE DATABASE {TEST_DB}")

    test_dsn = ADMIN_DSN.rsplit("/", 1)[0] + f"/{TEST_DB}"
    previous = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = test_dsn.replace("postgresql://", "postgresql+psycopg://", 1)
    try:
        command.upgrade(Config("alembic.ini"), "head")
        yield test_dsn
    finally:
        if previous is None:
            del os.environ["DATABASE_URL"]
        else:
            os.environ["DATABASE_URL"] = previous
        admin.execute(f"DROP DATABASE IF EXISTS {TEST_DB} WITH (FORCE)")
        admin.close()


@pytest.fixture
def redis_url():
    """An emptied scratch Redis database (db 15 by default, or TEST_REDIS_URL)."""
    url = os.environ.get("TEST_REDIS_URL", "redis://localhost:6379/15")
    client = redis.Redis.from_url(url, socket_connect_timeout=3)
    try:
        client.flushdb()
    except redis.ConnectionError:
        pytest.skip("Redis is not reachable")
    yield url
    client.flushdb()
    client.close()


@pytest.fixture
def anyio_backend():
    return "asyncio"
