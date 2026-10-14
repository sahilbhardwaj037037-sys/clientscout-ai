from sqlalchemy import create_engine, event
from sqlalchemy.engine import URL
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from app.core.settings import DB_PATH


class Base(DeclarativeBase):
    pass


def make_engine(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(URL.create('sqlite', database=str(path)), connect_args={'check_same_thread': False, 'timeout': 10})

    @event.listens_for(engine, 'connect')
    def configure_sqlite(connection, _):
        connection.isolation_level = None
        connection.execute('PRAGMA foreign_keys=ON')
        connection.execute('PRAGMA busy_timeout=10000')
    @event.listens_for(engine, 'begin')
    def begin_sqlite(connection):
        connection.exec_driver_sql('BEGIN')
    return engine


engine = make_engine(DB_PATH)
SessionLocal = sessionmaker(engine, expire_on_commit=False)


def get_session():
    with SessionLocal() as session:
        yield session
