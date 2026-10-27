"""Alembic environment. migrate.py passes an open connection; the `alembic` CLI opens its own."""

import os
from logging.config import fileConfig

from alembic import context

from jobhunt.db import DEFAULT_DB_URL, make_engine, metadata

config = context.config


def run(connection) -> None:
    # Batch mode lets future ALTERs work on SQLite, which rebuilds the table instead.
    context.configure(connection=connection, target_metadata=metadata, render_as_batch=True)
    with context.begin_transaction():
        context.run_migrations()


connection = config.attributes.get("connection")
if connection is not None:
    run(connection)
else:
    # Development use through the repo-root alembic.ini.
    if config.config_file_name is not None:
        fileConfig(config.config_file_name)
    from jobhunt.migrate import migration_connection

    engine = make_engine(os.environ.get("JOBHUNT_DB_URL", DEFAULT_DB_URL))
    try:
        with migration_connection(engine) as conn:
            run(conn)
    finally:
        engine.dispose()
