"""OperationModel list → generated tool + test files (pure)."""

from __future__ import annotations

import dataclasses
import keyword
import logging
import re
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from remote_mcp.sources.openapi.introspect import OperationModel

logger = logging.getLogger(__name__)

TEMPLATES_DIR = Path(__file__).parent.parent.parent / "templates_sources" / "openapi"

# Names that collide with locals the generated tool.py.j2 template introduces
# in every function body (ctx, query, body, client, response, auth_header).
# A spec param with one of these names must be renamed before templating,
# or it either raises a SyntaxError (duplicate argument) or silently shadows
# a template local (data corruption).
_RESERVED = {"ctx", "query", "body", "client", "response", "auth_header"}


@dataclasses.dataclass
class RenderParam:
    """Render-local param representation.

    `name` is the safe (possibly renamed) Python identifier used for the
    function argument. `wire_name` is the original param name as it must
    appear on the wire (query string key / JSON body key / path segment).
    """

    name: str
    wire_name: str
    py_type: str
    required: bool
    location: str  # "path" | "query" | "body"
    description: str = ""


def _env() -> Environment:
    return Environment(
        loader=FileSystemLoader(str(TEMPLATES_DIR)),
        undefined=StrictUndefined,
        keep_trailing_newline=True,
        autoescape=False,
    )


def _group_of(op: OperationModel) -> str:
    raw = op.tags[0] if op.tags else "api"
    group = re.sub(r"[^a-zA-Z0-9]+", "_", raw).strip("_").lower() or "api"
    if group[0].isdigit():
        group = "g_" + group
    if keyword.iskeyword(group) or keyword.issoftkeyword(group):
        group = group + "_"
    return group


def _safe_func_name(name: str) -> str:
    """Sanitize an operationId-derived func_name into a valid, non-keyword
    Python identifier (dots/spaces/etc collapsed, leading digit prefixed,
    keywords suffixed)."""
    name = re.sub(r"[^a-zA-Z0-9_]+", "_", name).strip("_").lower() or "op"
    if name[0].isdigit():
        name = "op_" + name
    if keyword.iskeyword(name) or keyword.issoftkeyword(name):
        name = name + "_"
    return name


def _safe_param_name(name: str) -> str:
    if keyword.iskeyword(name) or keyword.issoftkeyword(name) or name in _RESERVED:
        return name + "_"
    return name


def _dedupe(base: str, used: set[str]) -> str:
    """Return `base` if unused, else `base` (minus a trailing underscore,
    if any) suffixed with `_2`, `_3`, ... until unique."""
    if base not in used:
        return base
    stem = base[:-1] if base.endswith("_") else base
    i = 2
    candidate = f"{stem}_{i}"
    while candidate in used:
        i += 1
        candidate = f"{stem}_{i}"
    return candidate


def _sanitize_summary(summary: str) -> str:
    """Make a spec-provided summary safe to embed in a triple-quoted docstring."""
    collapsed = " ".join(summary.split())  # collapse newlines/tabs/repeats
    collapsed = collapsed.replace("\\", "\\\\")  # escape backslashes
    collapsed = collapsed.replace('"""', "'''")  # neutralize triple-quote breakout
    if collapsed.endswith('"'):
        collapsed += " "  # avoid """...""""
    return collapsed


def _rename_params(op: OperationModel) -> tuple[list[RenderParam], str]:
    """Build render-local params with reserved/keyword-safe, collision-free
    names, and return the path_fstring rewritten to match any renamed path
    params."""
    path_fstring = op.path_fstring
    used: set[str] = set()
    render_params: list[RenderParam] = []
    for p in op.params:
        safe = _dedupe(_safe_param_name(p.name), used)
        used.add(safe)
        if p.location == "path" and safe != p.name:
            path_fstring = path_fstring.replace("{" + p.name + "}", "{" + safe + "}")
        render_params.append(
            RenderParam(
                name=safe,
                # Original spec name (e.g. "petId"), not the renamed/snake_cased
                # python identifier — this is what must appear on the wire.
                wire_name=p.wire_name or p.name,
                py_type=p.py_type,
                required=p.required,
                location=p.location,
                description=p.description,
            )
        )
    return render_params, path_fstring


def _prepare_operations(operations: list[OperationModel]) -> list[OperationModel]:
    """Rewrite operations into templating-safe copies. Never mutates the
    caller's models — every operation and its params list are rebuilt."""
    seen_func_names: dict[str, set[str]] = {}
    prepared: list[OperationModel] = []
    for op in operations:
        group = _group_of(op)
        render_params, path_fstring = _rename_params(op)
        render_params.sort(key=lambda p: not p.required)  # required first, stable
        summary = _sanitize_summary(op.summary or op.operation_id)

        seen = seen_func_names.setdefault(group, set())
        safe_func_name = _safe_func_name(op.func_name)
        func_name = _dedupe(safe_func_name, seen)
        if func_name != op.func_name:
            logger.warning(
                "Duplicate/unsafe func_name %r in group %r; renamed to %r",
                op.func_name,
                group,
                func_name,
            )
        seen.add(func_name)

        prepared.append(
            dataclasses.replace(
                op,
                func_name=func_name,
                summary=summary,
                path_fstring=path_fstring,
                # NOTE: params is annotated list[ParamModel] on OperationModel,
                # but render_params is actually list[RenderParam] here — an
                # intentional widening for templating-local (renamed,
                # wire_name-carrying) param representations. Do not change
                # the introspect.py annotation to match; ParamModel is the
                # spec-fidelity model and must stay pure.
                params=render_params,
            )
        )
    return prepared


def render_openapi_tools(
    api_slug: str,
    operations: list[OperationModel],
    generator_version: str,
    locator: str,
) -> dict[str, str]:
    env = _env()
    tool_tpl = env.get_template("tool.py.j2")
    test_tpl = env.get_template("test_tool.py.j2")

    prepared = _prepare_operations(operations)

    groups: dict[str, list[OperationModel]] = {}
    for op in prepared:
        groups.setdefault(_group_of(op), []).append(op)

    files: dict[str, str] = {f"src/tools/{api_slug}/__init__.py": ""}
    for group, ops in sorted(groups.items()):
        ctx = {
            "api_slug": api_slug,
            "group": group,
            "router_name": f"{api_slug}_{group}_router",
            "operations": ops,
            "generator_version": generator_version,
            "locator": locator,
        }
        files[f"src/tools/{api_slug}/{group}.py"] = tool_tpl.render(**ctx)
        files[f"tests/tools/test_{api_slug}_{group}.py"] = test_tpl.render(**ctx)
    return files
