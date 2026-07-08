import sqlite3

import pytest

from remote_mcp.sources import IntrospectionError
from remote_mcp.sources.database.introspect import (
    dialect_of,
    introspect_database,
    sanitize_dsn,
    schema_fingerprint,
)


@pytest.fixture()
def fixture_db(tmp_path):
    db = tmp_path / "shop.db"
    conn = sqlite3.connect(db)
    conn.executescript(
        """
        CREATE TABLE orders (
            id INTEGER PRIMARY KEY,
            customer TEXT NOT NULL,
            total REAL,
            paid BOOLEAN NOT NULL DEFAULT 0
        );
        CREATE TABLE customers (id INTEGER PRIMARY KEY, email TEXT NOT NULL);
        """
    )
    conn.close()
    return f"sqlite:///{db}"


def test_introspects_tables_and_columns(fixture_db):
    tables = {t.name: t for t in introspect_database(fixture_db)}
    assert set(tables) == {"orders", "customers"}
    orders = tables["orders"]
    cols = {c.name: c for c in orders.columns}
    assert cols["id"].primary_key and cols["id"].py_type == "int"
    assert cols["customer"].py_type == "str" and cols["customer"].nullable is False
    assert cols["total"].py_type == "float" and cols["total"].nullable is True
    assert orders.pk.name == "id"


def test_fingerprint_changes_with_schema(fixture_db):
    before = schema_fingerprint(introspect_database(fixture_db))
    import sqlalchemy

    eng = sqlalchemy.create_engine(fixture_db)
    with eng.connect() as c:
        c.execute(sqlalchemy.text("ALTER TABLE orders ADD COLUMN note TEXT"))
        c.commit()
    after = schema_fingerprint(introspect_database(fixture_db))
    assert before != after


def test_sanitize_dsn_strips_credentials():
    assert (
        sanitize_dsn("postgresql://user:secret@db.host:5432/mydb")
        == "postgresql://db.host:5432/mydb"
    )


def test_sanitize_dsn_password_with_at_signs():
    assert (
        sanitize_dsn("postgresql://user:sec@ret@db.host:5432/mydb")
        == "postgresql://db.host:5432/mydb"
    )
    assert sanitize_dsn("postgresql://user:P@ssw0rd@db.host/mydb") == "postgresql://db.host/mydb"


def test_sanitize_dsn_no_credentials_unchanged():
    assert sanitize_dsn("sqlite:///path/to.db") == "sqlite:///path/to.db"
    assert sanitize_dsn("postgresql://db.host:5432/mydb") == "postgresql://db.host:5432/mydb"
    assert sanitize_dsn("not-a-dsn") == "not-a-dsn"


def test_dialect_of():
    assert dialect_of("sqlite:///x.db") == "sqlite"
    assert dialect_of("postgresql://h/db") == "postgresql"
    assert dialect_of("mysql://h/db") == "mysql"
    with pytest.raises(IntrospectionError):
        dialect_of("oracle://h/db")


def test_unreachable_dsn_raises_without_credentials():
    with pytest.raises(IntrospectionError) as exc:
        introspect_database("postgresql://user:secret@127.0.0.1:1/none")
    assert "secret" not in str(exc.value)
