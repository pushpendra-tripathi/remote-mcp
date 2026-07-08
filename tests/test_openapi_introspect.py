from pathlib import Path

import pytest

from remote_mcp.sources.openapi.introspect import (
    IntrospectionError,
    extract_operations,
    load_spec,
)

FIXTURE = Path(__file__).parent / "fixtures" / "petstore.json"


def test_load_spec_returns_dict_and_hash():
    spec, digest = load_spec(str(FIXTURE))
    assert spec["info"]["title"] == "Petstore"
    assert len(digest) == 64


def test_load_spec_rejects_non_openapi3(tmp_path):
    bad = tmp_path / "swagger.json"
    bad.write_text('{"swagger": "2.0", "paths": {}}', encoding="utf-8")
    with pytest.raises(IntrospectionError, match="OpenAPI 3"):
        load_spec(str(bad))


def test_extract_operations_models():
    spec, _ = load_spec(str(FIXTURE))
    ops = {o.operation_id: o for o in extract_operations(spec)}
    assert set(ops) == {"listPets", "createPet", "getPetById"}  # no-operationId skipped

    lp = ops["listPets"]
    assert lp.method == "get" and lp.func_name == "list_pets"
    assert lp.params[0].name == "limit" and lp.params[0].py_type == "int"
    assert lp.params[0].required is False and lp.params[0].location == "query"

    gp = ops["getPetById"]
    assert gp.path == "/pets/{petId}"
    assert gp.path_fstring == "/pets/{pet_id}"
    assert gp.params[0].name == "pet_id" and gp.params[0].required is True

    cp = ops["createPet"]
    body = {p.name: p for p in cp.params if p.location == "body"}
    assert body["name"].required is True and body["tag"].required is False
    # required-first ordering
    assert [p.required for p in cp.params] == sorted([p.required for p in cp.params], reverse=True)


def test_ref_parameter_resolved():
    spec = {
        "openapi": "3.0.0",
        "info": {"title": "T", "version": "1"},
        "components": {
            "parameters": {
                "PetId": {
                    "name": "petId",
                    "in": "path",
                    "required": True,
                    "schema": {"type": "string"},
                }
            }
        },
        "paths": {
            "/pets/{petId}": {
                "get": {
                    "operationId": "getPet",
                    "parameters": [{"$ref": "#/components/parameters/PetId"}],
                }
            }
        },
    }
    ops = extract_operations(spec)
    assert len(ops) == 1
    assert len(ops[0].params) == 1
    assert ops[0].params[0].name == "pet_id"
    assert ops[0].params[0].location == "path"


def test_external_ref_raises():
    spec = {
        "openapi": "3.0.0",
        "paths": {
            "/x": {
                "get": {
                    "operationId": "getX",
                    "parameters": [{"$ref": "http://x/y.json#/z"}],
                }
            }
        },
    }
    with pytest.raises(IntrospectionError, match="External"):
        extract_operations(spec)


def test_unresolvable_ref_raises():
    spec = {
        "openapi": "3.0.0",
        "paths": {
            "/x": {
                "get": {
                    "operationId": "getX",
                    "parameters": [{"$ref": "#/components/parameters/Nope"}],
                }
            }
        },
    }
    with pytest.raises(IntrospectionError, match="Unresolvable"):
        extract_operations(spec)


def test_operation_param_overrides_path_param():
    spec = {
        "openapi": "3.0.0",
        "paths": {
            "/items/{itemId}": {
                "parameters": [
                    {
                        "name": "itemId",
                        "in": "path",
                        "required": True,
                        "schema": {"type": "string"},
                    }
                ],
                "get": {
                    "operationId": "getItem",
                    "parameters": [
                        {
                            "name": "itemId",
                            "in": "path",
                            "required": True,
                            "schema": {"type": "integer"},
                        }
                    ],
                },
            }
        },
    }
    ops = extract_operations(spec)
    assert len(ops) == 1
    params = ops[0].params
    assert len(params) == 1
    assert params[0].py_type == "int"


def test_acronym_snake_case():
    spec = {
        "openapi": "3.0.0",
        "paths": {
            "/status": {
                "get": {"operationId": "getHTTPStatus"},
            }
        },
    }
    ops = extract_operations(spec)
    assert ops[0].func_name == "get_http_status"


def test_header_param_skipped():
    spec = {
        "openapi": "3.0.0",
        "paths": {
            "/x": {
                "get": {
                    "operationId": "getX",
                    "parameters": [
                        {"name": "q", "in": "query", "schema": {"type": "string"}},
                        {"name": "X-Token", "in": "header", "schema": {"type": "string"}},
                    ],
                }
            }
        },
    }
    ops = extract_operations(spec)
    params = ops[0].params
    assert len(params) == 1
    assert params[0].name == "q"
    assert params[0].location == "query"


def test_ref_body_schema_resolved():
    spec = {
        "openapi": "3.0.0",
        "components": {
            "schemas": {
                "NewPet": {
                    "type": "object",
                    "required": ["name"],
                    "properties": {
                        "name": {"type": "string"},
                        "tag": {"type": "string"},
                    },
                }
            }
        },
        "paths": {
            "/pets": {
                "post": {
                    "operationId": "createPet",
                    "requestBody": {
                        "content": {
                            "application/json": {"schema": {"$ref": "#/components/schemas/NewPet"}}
                        }
                    },
                }
            }
        },
    }
    ops = extract_operations(spec)
    body = {p.name: p for p in ops[0].params if p.location == "body"}
    assert body["name"].required is True
    assert body["tag"].required is False


def test_non_utf8_spec_raises(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_bytes(b"\xff\xfe invalid")
    with pytest.raises(IntrospectionError, match="UTF-8"):
        load_spec(str(bad))


def test_wire_name_preserved():
    spec, _ = load_spec(str(FIXTURE))
    ops = {o.operation_id: o for o in extract_operations(spec)}

    gp = ops["getPetById"]
    assert gp.params[0].name == "pet_id"
    assert gp.params[0].wire_name == "petId"

    cp = ops["createPet"]
    body = {p.name: p for p in cp.params if p.location == "body"}
    assert body["name"].wire_name == "name"
    assert body["tag"].wire_name == "tag"
