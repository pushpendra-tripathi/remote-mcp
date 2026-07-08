"""End-to-end: new project + openapi + database sources, then doctor.

This is slow because it builds a venv and installs the generated project
(FastMCP + aiosqlite). Skip in fast loops:
    pytest -m "not slow"
"""

from __future__ import annotations

import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

from remote_mcp.cli import app
from tests.test_e2e import _install_venv

runner = CliRunner()
FIXTURE = Path(__file__).parent / "fixtures" / "petstore.json"


def test_full_source_flow(tmp_path):
    proj = tmp_path / "acme"
    # 1. scaffold shell
    result = runner.invoke(
        app, ["new", "acme", "--yes", "--into", str(proj), "--auth-mode", "none"]
    )
    assert result.exit_code == 0, result.output

    # 2. add openapi source
    result = runner.invoke(
        app, ["add", "openapi", str(FIXTURE), "-p", str(proj), "--tag", "pets", "-y"]
    )
    assert result.exit_code == 0, result.output

    # 3. add database source
    db = tmp_path / "shop.db"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE orders (id INTEGER PRIMARY KEY, customer TEXT NOT NULL)")
    conn.close()
    result = runner.invoke(
        app, ["add", "database", f"sqlite:///{db}", "-p", str(proj), "--include", "*", "-y"]
    )
    assert result.exit_code == 0, result.output

    # 4. zero runtime dependency on remote_mcp
    hits = [
        p for p in (proj / "src").rglob("*.py") if "remote_mcp" in p.read_text(encoding="utf-8")
    ]
    assert hits == []

    # 5. doctor: clean -> exit 0
    assert runner.invoke(app, ["doctor", "-p", str(proj)]).exit_code == 0

    # 6. modify a generated file -> doctor exit 1, file named
    target = proj / "src" / "tools" / "db" / "tools.py"
    target.write_text(target.read_text(encoding="utf-8") + "\n# local edit\n", encoding="utf-8")
    drift = runner.invoke(app, ["doctor", "-p", str(proj)])
    assert drift.exit_code == 1
    assert "tools.py" in drift.output

    # 7. generated python is importable-quality: syntax check every file
    for p in (proj / "src").rglob("*.py"):
        subprocess.run([sys.executable, "-m", "py_compile", str(p)], check=True)


@pytest.mark.slow
@pytest.mark.timeout(600)
def test_full_source_flow_generated_suite_passes(tmp_path):
    """Full e2e: scaffold + both sources + pip install + run the generated suite.

    Skipped unless explicitly selected with `pytest -m slow` because it
    downloads FastMCP and its deps and installs aiosqlite for the db tools.
    """
    # Default (passthrough) auth mode, matching tests/test_e2e.py's install+run
    # convention: the scaffold's own generated auth-middleware tests assume
    # passthrough is the configured default, so exercising the source
    # generators here shouldn't be conflated with that unrelated scaffold
    # concern (see BLOCKED note in the task report re: auth-mode "none").
    proj = tmp_path / "acme"
    result = runner.invoke(app, ["new", "acme", "--yes", "--into", str(proj)])
    assert result.exit_code == 0, result.output

    result = runner.invoke(
        app, ["add", "openapi", str(FIXTURE), "-p", str(proj), "--tag", "pets", "-y"]
    )
    assert result.exit_code == 0, result.output

    db = tmp_path / "shop.db"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE orders (id INTEGER PRIMARY KEY, customer TEXT NOT NULL)")
    conn.close()
    result = runner.invoke(
        app, ["add", "database", f"sqlite:///{db}", "-p", str(proj), "--include", "*", "-y"]
    )
    assert result.exit_code == 0, result.output

    py = _install_venv(proj)
    pip = py.parent / ("pip.exe" if sys.platform == "win32" else "pip")
    subprocess.run([str(pip), "install", "aiosqlite"], check=True, timeout=120)

    result = subprocess.run(
        [str(py), "-m", "pytest", "tests/", "-v"],
        cwd=proj,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=180,
    )
    assert result.returncode == 0, f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
