import ast

from remote_mcp.sources.database.introspect import ColumnModel, TableModel
from remote_mcp.sources.database.render import render_database_tools

ORDERS = TableModel(
    name="orders",
    columns=[
        ColumnModel("id", "int", nullable=False, primary_key=True),
        ColumnModel("customer", "str", nullable=False, primary_key=False),
        ColumnModel("total", "float", nullable=True, primary_key=False),
    ],
)


def render(writes=None, dialect="sqlite"):
    return render_database_tools(
        [ORDERS],
        writes or {},
        dialect,
        generator_version="1.0.0",
        locator="sqlite:///shop.db",
    )


def test_file_layout():
    files = render()
    assert set(files) == {
        "src/tools/db/__init__.py",
        "src/tools/db/db.py",
        "src/tools/db/tools.py",
        "tests/tools/test_db_tools.py",
    }


def test_read_tools_generated_and_valid():
    mod = render()["src/tools/db/tools.py"]
    tree = ast.parse(mod)
    funcs = {n.name for n in ast.walk(tree) if isinstance(n, ast.AsyncFunctionDef)}
    assert {"list_orders", "get_orders_by_id", "search_orders"} <= funcs
    assert "insert_orders" not in funcs  # read-only default
    assert "remote_mcp" not in mod
    assert '"orders": ("id", "customer", "total", )' in mod  # order_by allowlist constant


def test_sql_is_parameterized_sqlite():
    mod = render()["src/tools/db/tools.py"]
    assert 'FROM "orders"' in mod
    assert "?" in mod  # sqlite placeholders
    assert ".format(" not in mod and "% (" not in mod  # no runtime interpolation


def test_write_optin_generates_named_tools():
    mod = render(writes={"orders": {"insert", "update"}})["src/tools/db/tools.py"]
    funcs = {n.name for n in ast.walk(ast.parse(mod)) if isinstance(n, ast.AsyncFunctionDef)}
    assert {"insert_orders", "update_orders_by_id"} <= funcs
    # insert requires non-nullable columns as required params
    assert "async def insert_orders(ctx: Context, customer: str" in mod


def test_postgres_placeholders():
    mod = render(dialect="postgresql")["src/tools/db/tools.py"]
    assert "$1" in mod


def test_db_module_and_test_file_valid():
    files = render()
    ast.parse(files["src/tools/db/db.py"])
    ast.parse(files["tests/tools/test_db_tools.py"])
    assert "DB_MAX_ROWS" in files["src/tools/db/db.py"]
    assert "db_statement_timeout_ms" in files["src/tools/db/db.py"]


# --- Hardening: identifiers that collide with Python keywords/reserved
# template locals, or contain characters illegal in Python identifiers, must
# never break codegen. SQL keeps the original (wire) name, quoted; only the
# generated Python identifiers get renamed. ---


def _render_one(table, writes=None, dialect="sqlite"):
    return render_database_tools(
        [table],
        writes or {},
        dialect,
        generator_version="1.0.0",
        locator="test",
    )


def test_table_named_class_is_ast_parseable():
    table = TableModel(
        name="class",
        columns=[
            ColumnModel("id", "int", nullable=False, primary_key=True),
            ColumnModel("label", "str", nullable=True, primary_key=False),
        ],
    )
    files = _render_one(table, writes={"class": {"insert", "update"}})
    mod = files["src/tools/db/tools.py"]
    tree = ast.parse(mod)  # must compile despite table name == python keyword
    funcs = {n.name for n in ast.walk(tree) if isinstance(n, ast.AsyncFunctionDef)}
    assert {"list_class", "get_class_by_id", "search_class", "insert_class"} <= funcs
    assert 'FROM "class"' in mod  # wire name preserved, quoted, in SQL
    ast.parse(files["tests/tools/test_db_tools.py"])


def test_pk_named_from_renames_param_not_sql():
    table = TableModel(
        name="events",
        columns=[
            ColumnModel("from", "str", nullable=False, primary_key=True),
            ColumnModel("to", "str", nullable=True, primary_key=False),
        ],
    )
    files = _render_one(table, writes={"events": {"update"}})
    mod = files["src/tools/db/tools.py"]
    tree = ast.parse(mod)  # `from` as a bare param name would be a SyntaxError
    funcs = {n.name for n in ast.walk(tree) if isinstance(n, ast.AsyncFunctionDef)}
    assert any(f.startswith("get_events_by_from") for f in funcs)
    assert any(f.startswith("update_events_by_from") for f in funcs)
    assert "from:" not in mod  # never a bare `from` parameter
    assert 'WHERE "from" =' in mod  # SQL uses the original wire name, quoted
    ast.parse(files["tests/tools/test_db_tools.py"])


def test_column_named_limit_renames_param_not_sql():
    table = TableModel(
        name="sessions",
        columns=[
            ColumnModel("id", "int", nullable=False, primary_key=True),
            ColumnModel("limit", "int", nullable=True, primary_key=False),
        ],
    )
    files = _render_one(table, writes={"sessions": {"insert", "update"}})
    mod = files["src/tools/db/tools.py"]
    tree = ast.parse(mod)
    src = mod
    # the bare parameter `limit` is reserved for list_/search_'s row cap —
    # a column named "limit" must not shadow it in insert_/update_ signatures
    insert_fn = next(
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.AsyncFunctionDef) and n.name == "insert_sessions"
    )
    arg_names = {a.arg for a in insert_fn.args.args}
    assert "limit" not in arg_names
    assert '"limit"' in src  # wire name still quoted in SQL/allowlist
    ast.parse(files["tests/tools/test_db_tools.py"])


def test_table_named_with_digits_and_dashes_is_ast_parseable():
    table = TableModel(
        name="2fa-codes",
        columns=[
            ColumnModel("id", "int", nullable=False, primary_key=True),
            ColumnModel("code", "str", nullable=False, primary_key=False),
        ],
    )
    files = _render_one(table, writes={"2fa-codes": {"insert"}})
    mod = files["src/tools/db/tools.py"]
    ast.parse(mod)  # must compile despite hyphen/leading-digit table name
    assert 'FROM "2fa-codes"' in mod  # wire name preserved, quoted
    ast.parse(files["tests/tools/test_db_tools.py"])


def test_embedded_quote_identifier_escaped():
    """SQL injection: embedded ANSI quote in column name must be escaped."""
    table = TableModel(
        name="orders",
        columns=[
            ColumnModel('id" OR 1=1 OR "id', "int", nullable=False, primary_key=True),
            ColumnModel("customer", "str", nullable=False, primary_key=False),
        ],
    )
    files = _render_one(table, writes={}, dialect="sqlite")
    mod = files["src/tools/db/tools.py"]
    ast.parse(mod)  # must compile
    # Rendered SQL must contain the ESCAPED (doubled) form: "id"" OR 1=1 OR ""id"
    assert '"id"" OR 1=1 OR ""id"' in mod
    # Must NOT contain the raw breakout sequence
    assert '"id" OR 1=1 OR "id"' not in mod


def test_embedded_backtick_mysql_escaped():
    """SQL injection: embedded backtick in column name must be escaped for MySQL."""
    table = TableModel(
        name="orders",
        columns=[
            ColumnModel("x`y", "int", nullable=False, primary_key=True),
            ColumnModel("value", "str", nullable=False, primary_key=False),
        ],
    )
    files = _render_one(table, writes={}, dialect="mysql")
    mod = files["src/tools/db/tools.py"]
    ast.parse(mod)  # must compile
    # Rendered SQL must contain the ESCAPED (doubled) form: `x``y`
    assert "`x``y`" in mod
    # Must NOT contain raw backtick that would break out
    assert "`x`y`" not in mod
