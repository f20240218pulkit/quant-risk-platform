from alembic import context

from src.product.database import database_engine

if context.is_offline_mode():
    raise RuntimeError("The Workbench migration requires a PostgreSQL connection.")

engine = database_engine()
with engine.connect() as connection:
    context.configure(connection=connection)
    with context.begin_transaction():
        context.run_migrations()
