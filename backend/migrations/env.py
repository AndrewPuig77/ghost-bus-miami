from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine

from app.config import Settings

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name, disable_existing_loggers=False)

# Migrations are hand-written SQL, so there is no model metadata to autogenerate from.
target_metadata = None


def run_migrations() -> None:
    # Settings() is built fresh (not cached) so tests can point at another database.
    engine = create_engine(Settings().database_url)
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


run_migrations()
