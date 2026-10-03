from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker
from app.config import get_settings


def sqlalchemy_database_url(database_url: str) -> str:
    """Bind bare PostgreSQL URLs to the driver installed by this repository.

    SQLAlchemy 2.1 resolves ``postgresql://`` to psycopg 3, while JobTomatik's
    pinned runtime dependency is ``psycopg2-binary``. Preserve explicit driver
    URLs and make the repository's existing bare Compose URL deterministic.
    """

    if database_url.startswith("postgresql://"):
        return "postgresql+psycopg2://" + database_url.removeprefix("postgresql://")
    return database_url


settings = get_settings()
database_url = sqlalchemy_database_url(settings.database_url)
connect_args = {"check_same_thread": False} if database_url.startswith("sqlite") else {}
engine = create_engine(database_url, pool_pre_ping=True, connect_args=connect_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
