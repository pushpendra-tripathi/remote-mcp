"""DSN → TableModel list via SQLAlchemy inspection. Runs only inside this CLI."""

from __future__ import annotations

from dataclasses import dataclass, field

from remote_mcp.sources import IntrospectionError
from remote_mcp.sources.manifest import hash_bytes

_PY_TYPES = {"str", "int", "float", "bool", "bytes"}
_DIALECTS = {
    "sqlite": "sqlite",
    "postgresql": "postgresql",
    "postgres": "postgresql",
    "mysql": "mysql",
}


@dataclass
class ColumnModel:
    name: str
    py_type: str
    nullable: bool
    primary_key: bool


@dataclass
class TableModel:
    name: str
    columns: list[ColumnModel] = field(default_factory=list)

    @property
    def pk(self) -> ColumnModel | None:
        return next((c for c in self.columns if c.primary_key), None)


def dialect_of(dsn: str) -> str:
    scheme = dsn.split("://", 1)[0].split("+", 1)[0].lower()
    if scheme not in _DIALECTS:
        raise IntrospectionError(
            f"Unsupported database scheme {scheme!r}. Supported: sqlite, postgresql, mysql."
        )
    return _DIALECTS[scheme]


def sanitize_dsn(dsn: str) -> str:
    scheme, sep, rest = dsn.partition("://")
    if not sep:
        return dsn
    authority, slash, path = rest.partition("/")
    if "@" in authority:
        authority = authority.rsplit("@", 1)[1]
    return f"{scheme}://{authority}{slash}{path}"


def introspect_database(dsn: str, schema: str | None = None) -> list[TableModel]:
    dialect_of(dsn)  # validates the scheme early
    try:
        import sqlalchemy
        from sqlalchemy import inspect as sa_inspect
    except ImportError as exc:  # pragma: no cover
        raise IntrospectionError(
            "Database support needs extras: pip install 'remote-mcp[db]'"
        ) from exc

    engine = None
    try:
        engine = sqlalchemy.create_engine(dsn)
        inspector = sa_inspect(engine)
        tables: list[TableModel] = []
        for table_name in sorted(inspector.get_table_names(schema=schema)):
            pk_cols = set(
                inspector.get_pk_constraint(table_name, schema=schema).get(
                    "constrained_columns", []
                )
            )
            columns = []
            for col in inspector.get_columns(table_name, schema=schema):
                try:
                    py_type = col["type"].python_type.__name__
                except NotImplementedError:
                    py_type = "str"
                columns.append(
                    ColumnModel(
                        name=col["name"],
                        py_type=py_type if py_type in _PY_TYPES else "str",
                        nullable=bool(col.get("nullable", True)),
                        primary_key=col["name"] in pk_cols,
                    )
                )
            tables.append(TableModel(name=table_name, columns=columns))
        return tables
    except IntrospectionError:
        raise
    except Exception as exc:
        raise IntrospectionError(
            f"Could not introspect database at {sanitize_dsn(dsn)}: {type(exc).__name__}"
        ) from exc
    finally:
        if engine is not None:
            engine.dispose()


def schema_fingerprint(tables: list[TableModel]) -> str:
    canonical = ";".join(
        f"{t.name}({','.join(f'{c.name}:{c.py_type}:{int(c.nullable)}:{int(c.primary_key)}' for c in t.columns)})"
        for t in tables
    )
    return hash_bytes(canonical.encode("utf-8"))
