"""OpenAPI 3.x → OperationModel list. Runs only inside this CLI."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from remote_mcp.sources import IntrospectionError
from remote_mcp.sources.manifest import hash_bytes

logger = logging.getLogger(__name__)

_TYPE_MAP = {
    "string": "str",
    "integer": "int",
    "number": "float",
    "boolean": "bool",
    "array": "list",
    "object": "dict",
}
_METHODS = ("get", "post", "put", "patch", "delete")
_CAMEL_RE = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")


@dataclass
class ParamModel:
    name: str
    py_type: str
    required: bool
    location: str  # "path" | "query" | "body"
    description: str = ""
    wire_name: str = ""


@dataclass
class OperationModel:
    operation_id: str
    func_name: str
    method: str
    path: str
    path_fstring: str
    summary: str
    tags: list[str] = field(default_factory=list)
    params: list[ParamModel] = field(default_factory=list)


def _snake(name: str) -> str:
    return _CAMEL_RE.sub("_", name).replace("-", "_").lower()


def _resolve_ref(spec: dict, obj: dict) -> dict:
    ref = obj.get("$ref")
    if not ref:
        return obj
    if not ref.startswith("#/"):
        raise IntrospectionError(f"External $ref not supported: {ref}")
    node: Any = spec
    for part in ref[2:].split("/"):
        try:
            node = node[part]
        except (KeyError, TypeError) as exc:
            raise IntrospectionError(f"Unresolvable $ref: {ref}") from exc
    return _resolve_ref(spec, node) if isinstance(node, dict) else node


def load_spec(source: str) -> tuple[dict, str]:
    if source.startswith(("http://", "https://")):
        try:
            import httpx
        except ImportError as exc:  # pragma: no cover
            raise IntrospectionError(
                "OpenAPI support needs extras: pip install 'remote-mcp[openapi]'"
            ) from exc
        try:
            resp = httpx.get(source, follow_redirects=True, timeout=30)
            resp.raise_for_status()
            raw = resp.content
        except httpx.HTTPError as exc:
            raise IntrospectionError(f"Could not fetch spec: {exc}") from exc
    else:
        path = Path(source)
        if not path.exists():
            raise IntrospectionError(f"Spec file not found: {source}")
        raw = path.read_bytes()

    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise IntrospectionError("Spec is not valid UTF-8.") from exc

    try:
        spec = json.loads(text)
    except json.JSONDecodeError:
        try:
            import yaml
        except ImportError as exc:  # pragma: no cover
            raise IntrospectionError(
                "YAML spec needs extras: pip install 'remote-mcp[openapi]'"
            ) from exc
        try:
            spec = yaml.safe_load(text)
        except yaml.YAMLError as exc:
            raise IntrospectionError(f"Spec is neither valid JSON nor YAML: {exc}") from exc

    if not isinstance(spec, dict) or not str(spec.get("openapi", "")).startswith("3"):
        raise IntrospectionError("Not an OpenAPI 3.x document (missing 'openapi: 3.*').")
    return spec, hash_bytes(raw)


def _body_params(spec: dict, operation: dict) -> list[ParamModel]:
    request_body = _resolve_ref(spec, operation.get("requestBody", {}))
    content = request_body.get("content", {}).get("application/json", {})
    schema = _resolve_ref(spec, content.get("schema", {}))
    if content and "properties" not in schema:
        logger.warning(
            "requestBody schema %r has no 'properties' (non-object body): no body params generated",
            schema.get("type", schema),
        )
    required = set(schema.get("required", []))
    out = []
    for prop, prop_schema in schema.get("properties", {}).items():
        out.append(
            ParamModel(
                name=_snake(prop),
                py_type=_TYPE_MAP.get(prop_schema.get("type", ""), "str"),
                required=prop in required,
                location="body",
                description=prop_schema.get("description", ""),
                wire_name=prop,
            )
        )
    return out


def extract_operations(spec: dict) -> list[OperationModel]:
    ops: list[OperationModel] = []
    for path, path_item in spec.get("paths", {}).items():
        for method in _METHODS:
            operation = path_item.get(method)
            if operation is None:
                continue
            op_id = operation.get("operationId")
            if not op_id:
                logger.warning("Skipping %s %s: no operationId", method.upper(), path)
                continue
            merged: dict[tuple[str, str], dict] = {}
            for p in [_resolve_ref(spec, p) for p in path_item.get("parameters", [])] + [
                _resolve_ref(spec, p) for p in operation.get("parameters", [])
            ]:
                merged[(p["name"], p["in"])] = p
            params: list[ParamModel] = []
            for p in merged.values():
                if p["in"] in ("header", "cookie"):
                    logger.warning(
                        "Skipping %s param %r on %s %s: header/cookie params are not generated",
                        p["in"],
                        p["name"],
                        method.upper(),
                        path,
                    )
                    continue
                params.append(
                    ParamModel(
                        name=_snake(p["name"]),
                        py_type=_TYPE_MAP.get(p.get("schema", {}).get("type", ""), "str"),
                        required=bool(p.get("required", False)) or p["in"] == "path",
                        location="path" if p["in"] == "path" else "query",
                        description=p.get("description", ""),
                        wire_name=p["name"],
                    )
                )
            params.extend(_body_params(spec, operation))
            params.sort(key=lambda p: not p.required)  # required first, stable
            path_fstring = re.sub(r"\{([^}]+)\}", lambda m: "{" + _snake(m.group(1)) + "}", path)
            ops.append(
                OperationModel(
                    operation_id=op_id,
                    func_name=_snake(op_id),
                    method=method,
                    path=path,
                    path_fstring=path_fstring,
                    summary=operation.get("summary", ""),
                    tags=list(operation.get("tags", [])),
                    params=params,
                )
            )
    return ops
