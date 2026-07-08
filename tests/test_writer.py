from pathlib import Path

import pytest

from remote_mcp.sources.writer import diff_summary, stage_and_write


def test_writes_and_creates_dirs(tmp_path):
    written = stage_and_write(tmp_path, {"src/tools/x/a.py": "print(1)\n"})
    assert (tmp_path / "src/tools/x/a.py").read_text() == "print(1)\n"
    assert written == [tmp_path / "src/tools/x/a.py"]


def test_overwrite_existing(tmp_path):
    (tmp_path / "a.py").write_text("old")
    stage_and_write(tmp_path, {"a.py": "new"})
    assert (tmp_path / "a.py").read_text() == "new"


def test_failure_restores_previous_state(tmp_path, monkeypatch):
    (tmp_path / "a.py").write_text("old")
    import remote_mcp.sources.writer as writer_mod

    real_write_text = writer_mod.Path.write_text
    calls = {"n": 0}

    def flaky(self, *args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 2:
            raise OSError("disk full")
        return real_write_text(self, *args, **kwargs)

    monkeypatch.setattr(writer_mod.Path, "write_text", flaky)
    with pytest.raises(OSError):
        stage_and_write(tmp_path, {"a.py": "new", "b.py": "x"})
    assert (tmp_path / "a.py").read_text() == "old"  # restored
    assert not (tmp_path / "b.py").exists()


def test_diff_summary(tmp_path):
    (tmp_path / "same.py").write_text("s")
    (tmp_path / "diff.py").write_text("old")
    got = diff_summary(tmp_path, {"same.py": "s", "diff.py": "new", "fresh.py": "f"})
    assert got == {"same.py": "unchanged", "diff.py": "changed", "fresh.py": "new"}


def test_returns_absolute_paths_for_relative_project_dir(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = stage_and_write(Path("."), {"a.py": "x"})
    assert all(p.is_absolute() for p in result)


def test_traversal_key_rejected(tmp_path):
    proj = tmp_path / "proj"
    proj.mkdir()
    with pytest.raises(ValueError):
        stage_and_write(proj, {"../escape.py": "x"})
    assert (tmp_path.parent / "escape.py").exists() is False


def test_absolute_key_rejected(tmp_path):
    with pytest.raises(ValueError):
        stage_and_write(tmp_path, {"/abs/path.py": "x"})


def test_rollback_removes_created_dirs(tmp_path, monkeypatch):
    proj = tmp_path / "proj"
    proj.mkdir()
    import remote_mcp.sources.writer as writer_mod

    real_write_text = writer_mod.Path.write_text
    calls = {"n": 0}

    def flaky(self, *args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 2:
            raise OSError("disk full")
        return real_write_text(self, *args, **kwargs)

    monkeypatch.setattr(writer_mod.Path, "write_text", flaky)
    with pytest.raises(OSError):
        stage_and_write(proj, {"a/b/first.py": "x", "second.py": "y"})
    assert not (proj / "a").exists()


def test_traversal_mid_batch_rolls_back(tmp_path):
    proj = tmp_path / "proj"
    proj.mkdir()
    with pytest.raises(ValueError):
        stage_and_write(proj, {"first.py": "x", "../x.py": "y"})
    assert not (proj / "first.py").exists()
    assert (tmp_path.parent / "x.py").exists() is False
