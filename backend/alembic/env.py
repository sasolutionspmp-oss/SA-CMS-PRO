"""Alembic migration environment."""
from alembic import context

from app import models
from app.config import settings
from app.db import engine

config = context.config


def run_migrations_offline() -> None:
    url = settings.database_url
    context.configure(url=url, target_metadata=models.Base.metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=models.Base.metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():  # pragma: no cover - infrastructure
    run_migrations_offline()
else:  # pragma: no cover - infrastructure
    run_migrations_online()
