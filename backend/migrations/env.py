from alembic import context
from app.database.session import Base, engine
from app.models.discovery import DiscoverySearch, DiscoveryCache, DiscoveredBusiness  # noqa: F401
from app.models.audit import Audit  # noqa: F401
from app.models.lead import Lead  # noqa: F401

config = context.config

def run_migrations_offline():
    context.configure(url=engine.url, target_metadata=Base.metadata, literal_binds=True, dialect_opts={'paramstyle': 'named'})
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online():
    supplied = config.attributes.get('connection')
    if supplied is not None:
        context.configure(connection=supplied, target_metadata=Base.metadata, render_as_batch=True)
        with context.begin_transaction():
            context.run_migrations()
        return
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=Base.metadata, render_as_batch=True)
        with context.begin_transaction():
            context.run_migrations()

if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
