from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings, read from environment variables (or a local .env)."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    swiftly_api_key: str = ""
    swiftly_agency: str = "miami"
    database_url: str = ""
    redis_url: str = "redis://redis:6379/0"

    # Ingestion worker
    swiftly_base_url: str = "https://api.goswift.ly/real-time"
    positions_interval_s: float = 15
    trip_updates_interval_s: float = 30
    # Swiftly allows 180 requests per 15 minutes; stay well under it.
    swiftly_max_requests: int = 150
    swiftly_window_s: float = 900
    gtfs_refresh_interval_s: float = 24 * 3600
    raw_retention_days: int = 3

    @property
    def psycopg_dsn(self) -> str:
        """DATABASE_URL without the SQLAlchemy driver suffix, for direct psycopg use."""
        return self.database_url.replace("postgresql+psycopg://", "postgresql://", 1)


@lru_cache
def get_settings() -> Settings:
    return Settings()
