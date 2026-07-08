import json

import pytest

from remote_mcp.sources.manifest import (
    GeneratedFile,
    Manifest,
    ManifestError,
    SourceEntry,
    hash_bytes,
    load_manifest,
    save_manifest,
    upsert_source,
)


def make_entry(name="petstore"):
    return SourceEntry(
        kind="openapi",
        name=name,
        locator="https://example.com/openapi.json",
        source_sha256="abc123",
        selected=["listPets"],
        generated_files=[GeneratedFile(path="src/tools/petstore/pets.py", sha256="def456")],
        generated_at="2026-07-02T00:00:00Z",
        generator_version="1.0.0",
    )


def test_round_trip(tmp_path):
    m = Manifest(sources=[make_entry()])
    save_manifest(tmp_path, m)
    loaded = load_manifest(tmp_path)
    assert loaded == m
    raw = json.loads((tmp_path / "sources.lock.json").read_text())
    assert raw["version"] == 1
    assert raw["sources"][0]["generated_files"][0]["path"] == "src/tools/petstore/pets.py"


def test_load_missing_returns_empty(tmp_path):
    assert load_manifest(tmp_path) == Manifest(sources=[])


def test_load_corrupt_raises(tmp_path):
    (tmp_path / "sources.lock.json").write_text("{not json", encoding="utf-8")
    with pytest.raises(ManifestError):
        load_manifest(tmp_path)


def test_upsert_replaces_same_kind_and_name(tmp_path):
    m = Manifest(sources=[make_entry()])
    newer = make_entry()
    newer.source_sha256 = "zzz"
    upsert_source(m, newer)
    assert len(m.sources) == 1
    assert m.sources[0].source_sha256 == "zzz"
    upsert_source(m, make_entry(name="other"))
    assert len(m.sources) == 2


def test_hash_bytes_stable():
    assert hash_bytes(b"x") == hash_bytes(b"x")
    assert hash_bytes(b"x") != hash_bytes(b"y")
