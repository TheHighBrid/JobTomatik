from app.database import sqlalchemy_database_url


def test_bare_postgresql_url_uses_pinned_psycopg2_driver():
    assert (
        sqlalchemy_database_url("postgresql://user:password@db:5432/jobtomatik")
        == "postgresql+psycopg2://user:password@db:5432/jobtomatik"
    )


def test_explicit_database_driver_is_preserved():
    value = "postgresql+psycopg://user:password@db:5432/jobtomatik"
    assert sqlalchemy_database_url(value) == value


def test_sqlite_url_is_preserved():
    value = "sqlite:///./jobtomatik.db"
    assert sqlalchemy_database_url(value) == value
