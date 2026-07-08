"""TableModel list → generated db module, tools, and tests (pure)."""

from __future__ import annotations

import dataclasses
import keyword
import re
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from remote_mcp.sources.database.introspect import ColumnModel, TableModel

TEMPLATES_DIR = Path(__file__).parent.parent.parent / "templates_sources" / "database"

_PLACEHOLDERS = {
    "sqlite": lambda i: "?",
    "postgresql": lambda i: f"${i}",
    "mysql": lambda i: "%s",
}

# Names that collide with locals the generated tools.py.j2 template introduces
# in every function body (ctx, limit, offset, order_by, column, value, sql,
# updates, total). A column/pk used as a bare parameter name equal to one of
# these would either raise a SyntaxError (a real Python keyword) or silently
# shadow a template local (data corruption) — rename before templating.
_RESERVED = {
    "ctx",
    "limit",
    "offset",
    "order_by",
    "column",
    "value",
    "sql",
    "updates",
    "total",
}


@dataclasses.dataclass
class RenderColumn:
    """Render-local column representation.

    `name` is the safe (possibly renamed) Python identifier used for
    generated function parameters and dict keys. `wire_name` is the
    original database column name, used only inside SQL (as a quoted
    identifier) and in the caller-facing ORDER_BY_COLUMNS allowlist.
    """

    name: str
    wire_name: str
    py_type: str
    nullable: bool
    primary_key: bool


@dataclasses.dataclass
class RenderTable:
    """Render-local table representation, built fresh per render call.

    Never mutates the caller's TableModel — every attribute the templates
    need is precomputed here instead of being set ad-hoc on the model.
    """

    name: str  # safe identifier fragment for composite function names
    wire_name: str  # original table name — used in SQL + allowlist keys
    columns: list[RenderColumn]
    pk: RenderColumn | None
    order_by_default: str
    write_ops: set[str]
    list_sql_by_order: str  # pre-rendered Python dict-literal source text
    limit_params: str
    get_sql: str  # pre-rendered Python string-literal source text ("" if no pk)
    search_sql_by_column: str  # pre-rendered Python dict-literal source text
    search_params: str
    insert_columns: list[RenderColumn]
    insert_sql: str  # pre-rendered Python string-literal source text
    update_columns: list[RenderColumn]
    update_sql_by_column: str  # pre-rendered Python dict-literal source text


def _q(identifier: str, dialect: str) -> str:
    if dialect == "mysql":
        return "`" + identifier.replace("`", "``") + "`"
    return '"' + identifier.replace('"', '""') + '"'


def _dict_src(pairs: dict[str, str]) -> str:
    """Render a str->str mapping as Python source text using repr() for both
    key and value.

    Deliberately NOT `json.dumps` (Jinja's `tojson` filter): JSON always
    escapes an embedded `"` as `\\"`, which would turn a quoted-identifier
    SQL string like `FROM "orders"` into `FROM \\"orders\\"` in the
    generated file. `repr()` instead picks whichever quote delimiter avoids
    escaping, so the ANSI-quoted identifiers survive intact and remain
    trivially ast-parseable.
    """
    body = ", ".join(f"{k!r}: {v!r}" for k, v in pairs.items())
    return "{" + body + "}"


def _safe_table_name(name: str) -> str:
    """Sanitize a table name into a valid identifier *fragment* for
    embedding in composite function names (list_<x>, get_<x>_by_<y>, ...).

    Fragments are always embedded with a leading prefix (list_, get_, ...),
    so a Python-keyword collision is harmless here (`list_class` is not
    itself a keyword) — only characters that would break tokenization, or a
    leading digit, need guarding.
    """
    frag = re.sub(r"[^a-zA-Z0-9_]+", "_", name).strip("_") or "t"
    if frag[0].isdigit():
        frag = "_" + frag
    return frag


def _safe_column_ident(name: str) -> str:
    """Sanitize a column name into a safe, non-keyword, non-reserved Python
    identifier for use as an actual function parameter (get_/update_'s pk
    param, insert/update column params) — unlike table fragments, these
    *are* used standalone as bare identifiers, so keyword/reserved-local
    collisions must be renamed, not just character-sanitized.
    """
    frag = re.sub(r"[^a-zA-Z0-9_]+", "_", name).strip("_") or "c"
    if frag[0].isdigit():
        frag = "_" + frag
    if keyword.iskeyword(frag) or keyword.issoftkeyword(frag) or frag in _RESERVED:
        frag = frag + "_"
    return frag


def _render_column(col: ColumnModel) -> RenderColumn:
    return RenderColumn(
        name=_safe_column_ident(col.name),
        wire_name=col.name,
        py_type=col.py_type,
        nullable=col.nullable,
        primary_key=col.primary_key,
    )


def _prepare_table(table: TableModel, dialect: str, write_ops: set[str]) -> RenderTable:
    ph = _PLACEHOLDERS[dialect]
    tq = _q(table.name, dialect)
    render_columns = [_render_column(c) for c in table.columns]
    pk = next((c for c in render_columns if c.primary_key), None)

    cols_sql = ", ".join(_q(c.wire_name, dialect) for c in render_columns)

    order_by_default = (pk or render_columns[0]).wire_name

    # One pre-built statement per allowed order_by / search column: identifiers
    # are baked at generation time (quoted, using the original wire name),
    # values bound at runtime via placeholders.
    list_sql_by_order = _dict_src(
        {
            c.wire_name: (
                f"SELECT {cols_sql} FROM {tq} ORDER BY {_q(c.wire_name, dialect)} "
                f"LIMIT {ph(1)} OFFSET {ph(2)}"
            )
            for c in render_columns
        }
    )

    get_sql = ""
    if pk:
        get_sql = repr(f"SELECT {cols_sql} FROM {tq} WHERE {_q(pk.wire_name, dialect)} = {ph(1)}")

    search_sql_by_column = _dict_src(
        {
            c.wire_name: (
                f"SELECT {cols_sql} FROM {tq} WHERE {_q(c.wire_name, dialect)} = {ph(1)} "
                f"LIMIT {ph(2)}"
            )
            for c in render_columns
        }
    )

    insert_columns = [c for c in render_columns if not c.primary_key]
    insert_columns.sort(key=lambda c: c.nullable)  # required (NOT NULL) first
    insert_sql = repr(
        f"INSERT INTO {tq} ({', '.join(_q(c.wire_name, dialect) for c in insert_columns)}) "
        f"VALUES ({', '.join(ph(i + 1) for i in range(len(insert_columns)))})"
    )

    update_columns = [c for c in render_columns if not c.primary_key]
    update_sql_by_column = "{}"
    if pk:
        update_sql_by_column = _dict_src(
            {
                # Keyed by the *safe* param name (not wire_name): the template
                # builds its `updates` dict with these same safe names as keys
                # (see tools.py.j2), and looks this SQL dict up by that key.
                c.name: (
                    f"UPDATE {tq} SET {_q(c.wire_name, dialect)} = {ph(1)} "
                    f"WHERE {_q(pk.wire_name, dialect)} = {ph(2)}"
                )
                for c in update_columns
            }
        )

    return RenderTable(
        name=_safe_table_name(table.name),
        wire_name=table.name,
        columns=render_columns,
        pk=pk,
        order_by_default=order_by_default,
        write_ops=write_ops,
        list_sql_by_order=list_sql_by_order,
        limit_params="limit, offset",
        get_sql=get_sql,
        search_sql_by_column=search_sql_by_column,
        search_params="value, limit",
        insert_columns=insert_columns,
        insert_sql=insert_sql,
        update_columns=update_columns,
        update_sql_by_column=update_sql_by_column,
    )


def render_database_tools(
    tables: list[TableModel],
    writes: dict[str, set[str]],
    dialect: str,
    generator_version: str,
    locator: str,
) -> dict[str, str]:
    env = Environment(
        loader=FileSystemLoader(str(TEMPLATES_DIR)),
        undefined=StrictUndefined,
        keep_trailing_newline=True,
        autoescape=False,
    )
    prepared = [_prepare_table(t, dialect, writes.get(t.name, set())) for t in tables]
    ctx = {
        "tables": prepared,
        "dialect": dialect,
        "generator_version": generator_version,
        "locator": locator,
    }
    return {
        "src/tools/db/__init__.py": "",
        "src/tools/db/db.py": env.get_template("db.py.j2").render(**ctx),
        "src/tools/db/tools.py": env.get_template("tools.py.j2").render(**ctx),
        "tests/tools/test_db_tools.py": env.get_template("test_tools.py.j2").render(**ctx),
    }
