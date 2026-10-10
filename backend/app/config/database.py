from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, DeclarativeBase
from app.config.config import Config

DATABASE_URL = Config.DB_URL

def _initialize_mysql_utc(connection, _connection_record):
    """Initialize a new physical connection without committing any transaction."""
    cursor = connection.cursor()
    try:
        cursor.execute("SET SESSION time_zone = '+00:00'")
    finally:
        cursor.close()


def create_app_engine(url, **options):
    """Use UTC for every new MySQL pool connection; other dialects are unchanged."""
    configured_engine = create_engine(url, **options)
    if configured_engine.dialect.name == "mysql":
        event.listen(configured_engine, "connect", _initialize_mysql_utc)
    return configured_engine


engine = create_app_engine(DATABASE_URL)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()

    try:
        yield db
    finally:
        db.close()
