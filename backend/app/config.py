from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings, read from environment variables (or a local .env)."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    swiftly_api_key: str = ""
    swiftly_agency: str = "miami"
    database_url: str = ""
    redis_url: str = "redis://redis:6379/0"

    @property
    def psycopg_dsn(self) -> str:
        """DATABASE_URL without the SQLAlchemy driver suffix, for direct psycopg use."""
        return self.database_url.replace("postgresql+psycopg://", "postgresql://", 1)


@lru_cache
def get_settings() -> Settings:
    return Settings()
