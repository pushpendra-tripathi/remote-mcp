from __future__ import annotations

import keyword
import re
from datetime import datetime, timezone
from pathlib import Path

import typer
from rich.console import Console
from rich.panel import Panel

from remote_mcp.scaffold import scaffold_project, scaffold_tool
from remote_mcp.sources.manifest import (
    GeneratedFile,
    ManifestError,
    SourceEntry,
    hash_bytes,
    load_manifest,
    save_manifest,
    upsert_source,
)
from remote_mcp.sources.selection import Candidate, SelectionError, resolve_selection
from remote_mcp.sources.writer import diff_summary, stage_and_write

console = Console()

app = typer.Typer(
    name="remote-mcp",
    add_completion=False,
    no_args_is_help=True,
    help="Scaffold a production-ready remote MCP server.",
)

add_app = typer.Typer(
    name="add",
    no_args_is_help=True,
    help="Add a new component (e.g. tool) to an existing scaffolded project.",
)
app.add_typer(add_app, name="add")


# kebab-case: starts with lowercase letter, lowercase/digit/hyphen, no double hyphen,
# does not end with hyphen. Length 2-64 (length enforced separately in validator).
_KEBAB_RE = re.compile(r"^[a-z](?:[a-z0-9]*(?:-[a-z0-9]+)*)$")
_SNAKE_RE = re.compile(r"^[a-z_][a-z0-9_]*$")
_AUTH_MODES = ("none", "passthrough", "jwt")


def _validate_project_name(name: str) -> str:
    name = name.strip()
    if not name:
        raise typer.BadParameter("Project name cannot be empty.")
    if len(name) < 2:
        raise typer.BadParameter("Project name too short (min 2 chars).")
    if len(name) > 64:
        raise typer.BadParameter("Project name too long (max 64 chars).")
    if not _KEBAB_RE.match(name):
        raise typer.BadParameter(
            f"Invalid project name: {name!r}. "
            "Must be kebab-case: lowercase letters, digits, hyphens; "
            "start with a letter; no leading/trailing/double hyphens."
        )
    slug = name.replace("-", "_")
    if keyword.iskeyword(slug) or keyword.issoftkeyword(slug):
        raise typer.BadParameter(f"Project name conflicts with Python keyword: {slug!r}.")
    return name


def _require_scaffolded_project(project_dir: Path) -> None:
    if not (
        (project_dir / "src" / "server.py").exists()
        and (project_dir / "src" / "core" / "handlers.py").exists()
    ):
        console.print(
            f"[red]Error: {project_dir} is not a scaffolded remote-mcp project. "
            "Run `remote-mcp new` first.[/red]"
        )
        raise typer.Exit(1)


def _print_generation_result(
    files: dict[str, str], summary: dict[str, str], mount_lines: list[str]
) -> None:
    for rel, status in summary.items():
        style = {"new": "green", "changed": "yellow", "unchanged": "dim"}[status]
        console.print(f"  [{style}]{status:9}[/{style}] {rel}")
    console.print(
        Panel(
            "\n".join(f"  [cyan]{line}[/cyan]" for line in mount_lines),
            title="[bold]Mount in src/server.py[/bold]",
            border_style="green",
        )
    )


def _validate_tool_name(name: str) -> str:
    name = name.strip().replace("-", "_")
    if not name:
        raise typer.BadParameter("Tool name cannot be empty.")
    if not _SNAKE_RE.match(name):
        raise typer.BadParameter(
            f"Invalid tool name: {name!r}. Must be snake_case (lowercase letters, digits, underscores; "
            "start with a letter or underscore)."
        )
    if keyword.iskeyword(name) or keyword.issoftkeyword(name):
        raise typer.BadParameter(f"Tool name conflicts with Python keyword: {name!r}.")
    return name


def version_callback(value: bool) -> None:
    if value:
        from remote_mcp import __version__

        typer.echo(f"remote-mcp {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: bool = typer.Option(
        None,
        "--version",
        "-V",
        callback=version_callback,
        is_eager=True,
        help="Show version and exit.",
    ),
) -> None:
    pass


def derive_context(
    project_name: str,
    service_name: str,
    auth_mode: str = "passthrough",
    github_owner: str = "",
    legacy_sse: bool = False,
) -> dict[str, str | bool]:
    project_slug = project_name.replace("-", "_")
    class_prefix = "".join(w.capitalize() for w in project_name.split("-"))
    return {
        "project_name": project_name,
        "project_slug": project_slug,
        "service_name": service_name,
        "class_prefix": class_prefix,
        "auth_mode": auth_mode,
        "github_owner": github_owner.strip() or "YOUR-GITHUB-USERNAME",
        "legacy_sse": legacy_sse,
    }


def _default_service_name(project_name: str) -> str:
    return " ".join(w.capitalize() for w in project_name.split("-"))


@app.command()
def new(
    project_name: str = typer.Argument(..., help="Project directory name (kebab-case)"),
    service_name: str | None = typer.Option(
        None,
        "--service-name",
        "-s",
        help="Human-readable service name (default: derived from project_name).",
    ),
    into: Path | None = typer.Option(
        None, "--into", help="Target directory (default: ./<project_name>)."
    ),
    yes: bool = typer.Option(
        False, "--yes", "-y", help="Skip interactive prompts; use defaults / provided flags."
    ),
    auth_mode: str = typer.Option(
        "passthrough",
        "--auth-mode",
        help="Default auth mode written to the project: none | passthrough | jwt.",
    ),
    github_owner: str = typer.Option(
        "",
        "--github-owner",
        help="GitHub user/org for the MCP registry namespace (io.github.<owner>).",
    ),
    legacy_sse: bool = typer.Option(
        False,
        "--legacy-sse",
        help="Also serve the deprecated SSE transport at /sse (compat only).",
    ),
) -> None:
    """Scaffold a new FastMCP remote server."""
    console.print("\n[bold blue]FastMCP Remote Server Generator[/bold blue]\n")

    if not yes:
        project_name = typer.prompt("Project name", default=project_name)
    project_name = _validate_project_name(project_name)

    if service_name is None:
        default_sn = _default_service_name(project_name)
        service_name = default_sn if yes else typer.prompt("Service name", default=default_sn)
    service_name = service_name.strip() or _default_service_name(project_name)

    if not yes:
        auth_mode = typer.prompt("Auth mode (none/passthrough/jwt)", default=auth_mode)
        github_owner = typer.prompt(
            "GitHub owner for MCP registry (blank to skip)", default=github_owner
        )
    auth_mode = auth_mode.strip().lower()
    if auth_mode not in _AUTH_MODES:
        raise typer.BadParameter(
            f"Invalid auth mode: {auth_mode!r}. Choose from: {', '.join(_AUTH_MODES)}."
        )

    target_dir = into if into is not None else Path(project_name)

    context = derive_context(
        project_name,
        service_name,
        auth_mode=auth_mode,
        github_owner=github_owner,
        legacy_sse=legacy_sse,
    )

    console.print(f"\nScaffolding [cyan]{project_name}[/cyan] into [cyan]{target_dir}[/cyan]...")

    try:
        scaffold_project(target_dir=target_dir, context=context)
    except FileExistsError as exc:
        console.print(f"[red]Error: {exc}[/red]")
        raise typer.Exit(1) from exc

    console.print("[green]✓ Scaffold complete[/green]")

    next_steps = (
        f"  [cyan]cd {target_dir}[/cyan]\n"
        f"  [cyan]python -m venv venv && source venv/bin/activate[/cyan]\n"
        f'  [cyan]pip install -e ".\\[dev]"[/cyan]\n'
        f"  [cyan]cp env.example .env[/cyan]\n"
        f"  [cyan]uvicorn asgi:application --reload --port 8001 --lifespan on[/cyan]\n"
        f"  [dim]No OAuth backend yet? Set AUTH_MODE=none in .env for local dev.[/dim]"
    )
    console.print(Panel(next_steps, title="[bold]Done! Next steps[/bold]", border_style="green"))


@add_app.command("tool")
def add_tool_cmd(
    tool_name: str = typer.Argument(..., help="Tool name (snake_case)"),
    project_dir: Path = typer.Option(
        Path("."), "--project-dir", "-p", help="Project directory (default: cwd)."
    ),
) -> None:
    """Add a new tool stub to an existing scaffolded project."""
    tool_name = _validate_tool_name(tool_name)

    if not (project_dir / "src" / "server.py").exists():
        console.print(
            f"[red]Error: {project_dir} does not look like a scaffolded remote-mcp project "
            "(no src/server.py).[/red]"
        )
        raise typer.Exit(1)

    try:
        created_path = scaffold_tool(project_dir=project_dir, tool_name=tool_name)
    except FileExistsError as exc:
        console.print(f"[red]Error: {exc}[/red]")
        raise typer.Exit(1) from exc

    console.print(f"[green]✓ Created {created_path}[/green]")
    console.print(
        Panel(
            f"  [cyan]from src.tools.{tool_name} import {tool_name}_router[/cyan]\n"
            f"  [cyan]mcp.mount({tool_name}_router)[/cyan]",
            title="[bold]Mount in src/server.py[/bold]",
            border_style="green",
        )
    )


@add_app.command("openapi")
def add_openapi_cmd(
    spec_source: str = typer.Argument(..., help="Path or URL to an OpenAPI 3.x document."),
    project_dir: Path = typer.Option(Path("."), "--project-dir", "-p"),
    name: str | None = typer.Option(
        None, "--name", help="Source name / package dir (default: derived from spec title)."
    ),
    include: list[str] = typer.Option([], "--include", help="operationId glob(s)."),
    exclude: list[str] = typer.Option([], "--exclude", help="operationId glob(s) to drop."),
    tag: list[str] = typer.Option([], "--tag", help="Select whole OpenAPI tag(s)."),
    yes: bool = typer.Option(False, "--yes", "-y", help="Non-interactive; needs --include/--tag."),
) -> None:
    """Generate MCP tools from an OpenAPI spec. Requires: pip install 'remote-mcp[openapi]'."""
    _require_scaffolded_project(project_dir)
    from remote_mcp import __version__
    from remote_mcp.sources.openapi.introspect import (
        IntrospectionError,
        extract_operations,
        load_spec,
    )
    from remote_mcp.sources.openapi.render import _group_of, render_openapi_tools

    try:
        spec, spec_hash = load_spec(spec_source)
        operations = extract_operations(spec)

        # selection.Candidate.group is a single string, so filtering by tags
        # there would only ever match an operation's *first* tag. Pre-filter
        # on the full tag set here instead, then let resolve_selection's tag
        # matching (tags=[]) be a no-op pass-through.
        if tag:
            tag_set = set(tag)
            operations_for_selection = [op for op in operations if tag_set & set(op.tags)]
            if not operations_for_selection:
                available = sorted({t for op in operations for t in op.tags})
                console.print(
                    f"[red]Error: --tag matched no operations. "
                    f"Available tags: {', '.join(available) if available else '(none)'}[/red]"
                )
                raise typer.Exit(1)
            # --tag alone must still satisfy resolve_selection's "needs
            # --include or --tag" non-interactive check.
            resolve_include = include or ["*"]
        else:
            operations_for_selection = operations
            resolve_include = include

        candidates = [
            Candidate(
                id=op.operation_id,
                label=f"{op.method.upper()} {op.path}",
                group=op.tags[0] if op.tags else "",
            )
            for op in operations_for_selection
        ]
        chosen = resolve_selection(
            candidates, include=resolve_include, exclude=exclude, tags=[], yes=yes
        )
    except (IntrospectionError, SelectionError) as exc:
        console.print(f"[red]Error: {exc}[/red]")
        raise typer.Exit(1) from exc

    chosen_ids = {c.id for c in chosen}
    selected_ops = [op for op in operations if op.operation_id in chosen_ids]
    try:
        api_slug = _validate_tool_name(
            name
            or re.sub(r"[^a-z0-9]+", "_", spec.get("info", {}).get("title", "api").lower()).strip(
                "_"
            )
        )
    except typer.BadParameter as exc:
        console.print(
            f"[red]Error: cannot derive a valid source name from the spec title; "
            f"pass --name. ({exc.message})[/red]"
        )
        raise typer.Exit(1) from exc

    files = render_openapi_tools(api_slug, selected_ops, __version__, spec_source)
    summary = diff_summary(project_dir, files)

    try:
        manifest = load_manifest(project_dir)
    except ManifestError as exc:
        console.print(f"[red]Error: {exc}[/red]")
        raise typer.Exit(2) from exc

    try:
        stage_and_write(project_dir, files)
    except ValueError as exc:
        console.print(f"[red]Error: {exc}[/red]")
        raise typer.Exit(1) from exc

    upsert_source(
        manifest,
        SourceEntry(
            kind="openapi",
            name=api_slug,
            locator=spec_source,
            source_sha256=spec_hash,
            selected=sorted(chosen_ids),
            generated_files=[
                GeneratedFile(path=rel, sha256=hash_bytes(content.encode("utf-8")))
                for rel, content in files.items()
            ],
            generated_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            generator_version=__version__,
        ),
    )
    save_manifest(project_dir, manifest)

    groups = sorted({_group_of(op) for op in selected_ops})
    mount_lines: list[str] = []
    for g in groups:
        mount_lines.append(f"from src.tools.{api_slug}.{g} import {api_slug}_{g}_router")
    mount_lines += [f"mcp.mount({api_slug}_{g}_router)" for g in groups]
    _print_generation_result(files, summary, mount_lines)


_WRITE_OPS = ("insert", "update")


def _parse_allow_write(specs: list[str]) -> dict[str, set[str]]:
    out: dict[str, set[str]] = {}
    for spec in specs:
        table, sep, op = spec.partition(":")
        if not sep or op not in _WRITE_OPS:
            raise typer.BadParameter(
                f"--allow-write expects TABLE:OP with OP in {{{', '.join(_WRITE_OPS)}}}; got {spec!r}."
            )
        out.setdefault(table, set()).add(op)
    return out


def _display_locator(sanitized_dsn: str, dialect: str) -> str:
    """A locator safe to embed in generated files (docstrings/headers).

    `sanitize_dsn` only strips authentication credentials, so a local sqlite
    path (which carries none) passes through unchanged — collapse it to just
    the filename so an absolute, machine-specific path never ends up in
    generated source. The manifest keeps the full sanitized DSN: `doctor
    --refresh` re-introspects from it, and a basename-only sqlite path would
    silently create an empty database in whatever directory doctor runs from.
    """
    if dialect != "sqlite":
        return sanitized_dsn
    scheme, sep, rest = sanitized_dsn.partition("://")
    if not sep:
        return sanitized_dsn
    return f"{scheme}:///{Path(rest.lstrip('/')).name}"


@add_app.command("database")
def add_database_cmd(
    dsn: str = typer.Argument(..., help="Database DSN: sqlite:/// | postgresql:// | mysql://"),
    project_dir: Path = typer.Option(Path("."), "--project-dir", "-p"),
    include: list[str] = typer.Option([], "--include", help="Table-name glob(s)."),
    exclude: list[str] = typer.Option([], "--exclude", help="Table-name glob(s) to drop."),
    schema: str | None = typer.Option(
        None, "--schema", help="DB schema (driver default if unset)."
    ),
    allow_write: list[str] = typer.Option(
        [], "--allow-write", help="Enable a write tool: TABLE:OP, OP in {insert, update}."
    ),
    yes: bool = typer.Option(False, "--yes", "-y", help="Non-interactive; needs --include."),
) -> None:
    """Generate read-only DB tools from a live schema. Requires: pip install 'remote-mcp[db]'."""
    _require_scaffolded_project(project_dir)
    try:
        writes = _parse_allow_write(allow_write)
    except typer.BadParameter as exc:
        console.print(f"[red]Error: {exc.message}[/red]")
        raise typer.Exit(1) from exc
    from remote_mcp import __version__
    from remote_mcp.sources import IntrospectionError
    from remote_mcp.sources.database.introspect import (
        dialect_of,
        introspect_database,
        sanitize_dsn,
        schema_fingerprint,
    )
    from remote_mcp.sources.database.render import render_database_tools

    try:
        dialect = dialect_of(dsn)
        tables = introspect_database(dsn, schema=schema)
        candidates = [
            Candidate(id=t.name, label=f"{t.name} ({len(t.columns)} cols)") for t in tables
        ]
        chosen = resolve_selection(candidates, include=include, exclude=exclude, tags=[], yes=yes)
    except (IntrospectionError, SelectionError) as exc:
        console.print(f"[red]Error: {exc}[/red]")
        raise typer.Exit(1) from exc

    chosen_names = {c.id for c in chosen}
    selected = [t for t in tables if t.name in chosen_names]
    unknown_writes = set(writes) - chosen_names
    if unknown_writes:
        console.print(
            f"[red]Error: --allow-write names tables outside the selection: "
            f"{', '.join(sorted(unknown_writes))}[/red]"
        )
        raise typer.Exit(1)

    manifest_locator = sanitize_dsn(dsn)
    files = render_database_tools(
        selected, writes, dialect, __version__, _display_locator(manifest_locator, dialect)
    )
    summary = diff_summary(project_dir, files)

    try:
        manifest = load_manifest(project_dir)
    except ManifestError as exc:
        console.print(f"[red]Error: {exc}[/red]")
        raise typer.Exit(2) from exc

    try:
        stage_and_write(project_dir, files)
    except ValueError as exc:
        console.print(f"[red]Error: {exc}[/red]")
        raise typer.Exit(1) from exc

    upsert_source(
        manifest,
        SourceEntry(
            kind="database",
            name="db",
            locator=manifest_locator,
            source_sha256=schema_fingerprint(selected),
            selected=sorted(chosen_names),
            generated_files=[
                GeneratedFile(path=rel, sha256=hash_bytes(content.encode("utf-8")))
                for rel, content in files.items()
            ],
            generated_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            generator_version=__version__,
        ),
    )
    save_manifest(project_dir, manifest)

    driver = {"sqlite": "aiosqlite", "postgresql": "asyncpg", "mysql": "aiomysql"}[dialect]
    _print_generation_result(
        files,
        summary,
        [
            "from src.tools.db.tools import db_router",
            "mcp.mount(db_router)",
            f"# then: pip install {driver}   and set DATABASE_URL in your deploy env",
        ],
    )
    console.print(
        "[yellow]Reminder:[/yellow] db tools act as the SERVER (server-side credentials), "
        "not as the caller. Set DATABASE_URL in the deploy environment; it is never "
        "written into generated files."
    )

    env_example = project_dir / "env.example"
    if env_example.exists() and "DATABASE_URL" not in env_example.read_text(encoding="utf-8"):
        env_example.open("a", encoding="utf-8").write(
            "\n# Database tools (added by `remote-mcp add database`)\n"
            "DATABASE_URL=\n"
            "DB_MAX_ROWS=200\n"
            "DB_STATEMENT_TIMEOUT_MS=5000\n"
        )
