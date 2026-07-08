import json
import sqlite3
from pathlib import Path

import pytest
from typer.testing import CliRunner

from remote_mcp import __version__
from remote_mcp.cli import app
from remote_mcp.sources.doctor import run_doctor
from remote_mcp.sources.manifest import (
    GeneratedFile,
    Manifest,
    ManifestError,
    SourceEntry,
    hash_bytes,
    save_manifest,
)

runner = CliRunner()


def project_with_manifest(tmp_path: Path, generator_version=__version__) -> Path:
    proj = tmp_path / "proj"
    (proj / "src" / "core").mkdir(parents=True)
    (proj / "src" / "server.py").write_text("# server", encoding="utf-8")
    (proj / "src" / "core" / "handlers.py").write_text("# handlers", encoding="utf-8")
    tool = proj / "src" / "tools" / "x" / "a.py"
    tool.parent.mkdir(parents=True)
    tool.write_bytes(
        b"print(1)\n"
    )  # explicit LF bytes: hash below assumes LF, not platform newline
    entry = SourceEntry(
        kind="openapi",
        name="x",
        locator="spec.json",
        source_sha256="abc",
        selected=["op"],
        generated_files=[GeneratedFile(path="src/tools/x/a.py", sha256=hash_bytes(b"print(1)\n"))],
        generated_at="2026-07-02T00:00:00Z",
        generator_version=generator_version,
    )
    save_manifest(proj, Manifest(sources=[entry]))
    return proj


def test_clean_project(tmp_path):
    report = run_doctor(project_with_manifest(tmp_path))
    assert report.has_drift is False
    src = report.sources[0]
    assert src.files[0].status == "clean"
    assert src.source_drift == "skipped"  # no --refresh


def test_modified_file_detected(tmp_path):
    proj = project_with_manifest(tmp_path)
    (proj / "src/tools/x/a.py").write_text("print(2)\n", encoding="utf-8")
    report = run_doctor(proj)
    assert report.has_drift and report.sources[0].files[0].status == "modified"


def test_missing_file_detected(tmp_path):
    proj = project_with_manifest(tmp_path)
    (proj / "src/tools/x/a.py").unlink()
    report = run_doctor(proj)
    assert report.has_drift and report.sources[0].files[0].status == "missing"


def test_version_drift_detected(tmp_path):
    proj = project_with_manifest(tmp_path, generator_version="0.0.0-sentinel")
    report = run_doctor(proj)
    assert report.has_drift and "0.0.0-sentinel" in report.sources[0].version_drift


def test_no_manifest_raises(tmp_path):
    (tmp_path / "src" / "core").mkdir(parents=True)
    with pytest.raises(ManifestError):
        run_doctor(tmp_path)


def test_cli_exit_codes_and_json(tmp_path):
    proj = project_with_manifest(tmp_path)
    ok = runner.invoke(app, ["doctor", "-p", str(proj), "--json"])
    assert ok.exit_code == 0
    payload = json.loads(ok.output)
    assert payload["has_drift"] is False

    (proj / "src/tools/x/a.py").write_text("changed", encoding="utf-8")
    drift = runner.invoke(app, ["doctor", "-p", str(proj)])
    assert drift.exit_code == 1

    empty = tmp_path / "empty"
    (empty / "src" / "core").mkdir(parents=True)
    (empty / "src" / "server.py").write_text("#", encoding="utf-8")
    (empty / "src" / "core" / "handlers.py").write_text("#", encoding="utf-8")
    err = runner.invoke(app, ["doctor", "-p", str(empty)])
    assert err.exit_code == 2


def test_refresh_missing_sqlite_db_unreachable(tmp_path):
    proj = project_with_manifest(tmp_path)
    missing_db = tmp_path / "does-not-exist.sqlite"
    entry = SourceEntry(
        kind="database",
        name="db",
        locator=f"sqlite:///{missing_db}",
        source_sha256="abc",
        selected=["t"],
        generated_files=[],
        generated_at="2026-07-02T00:00:00Z",
        generator_version=__version__,
    )
    save_manifest(proj, Manifest(sources=[entry]))

    report = run_doctor(proj, refresh=True)

    assert report.sources[0].source_drift == "unreachable"
    assert not missing_db.exists()


def test_refresh_relative_locator_resolved_from_project_dir(tmp_path, monkeypatch):
    from remote_mcp.sources.database.introspect import introspect_database, schema_fingerprint

    proj = project_with_manifest(tmp_path)
    db_path = proj / "data.db"
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE t (id INTEGER PRIMARY KEY)")
    conn.commit()
    conn.close()

    tables = introspect_database(f"sqlite:///{db_path}")
    digest = schema_fingerprint(tables)

    entry = SourceEntry(
        kind="database",
        name="db",
        locator="sqlite:///data.db",  # relative to proj, not to cwd
        source_sha256=digest,
        selected=[t.name for t in tables],
        generated_files=[],
        generated_at="2026-07-02T00:00:00Z",
        generator_version=__version__,
    )
    save_manifest(proj, Manifest(sources=[entry]))

    monkeypatch.chdir(tmp_path)  # cwd != proj: relative locator must resolve against proj
    report = run_doctor(proj, refresh=True)

    assert report.sources[0].source_drift == "current"


def test_non_project_dir_exits_2(tmp_path):
    empty = tmp_path / "not-a-project"
    empty.mkdir()
    result = runner.invoke(app, ["doctor", "-p", str(empty)])
    assert result.exit_code == 2

    missing = tmp_path / "does-not-exist"
    result = runner.invoke(app, ["doctor", "-p", str(missing)])
    assert result.exit_code == 2
