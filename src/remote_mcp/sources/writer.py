"""All-or-nothing file writes for source generators."""

from __future__ import annotations

import contextlib
from pathlib import Path


def _resolve_target(project_dir: Path, rel: str) -> Path:
    target = (project_dir / Path(rel)).resolve()
    if not target.is_relative_to(project_dir):
        raise ValueError(f"Generated path escapes project dir: {rel!r}")
    return target


def _new_parent_dirs(target: Path) -> list[Path]:
    """Return ancestor dirs of ``target`` that do not yet exist, deepest first."""
    dirs: list[Path] = []
    d = target.parent
    while not d.exists():
        dirs.append(d)
        d = d.parent
    return dirs


def diff_summary(project_dir: Path, files: dict[str, str]) -> dict[str, str]:
    project_dir = Path(project_dir).resolve()
    out: dict[str, str] = {}
    for rel, content in files.items():
        target = _resolve_target(project_dir, rel)
        if not target.exists():
            out[rel] = "new"
        elif target.read_text(encoding="utf-8") == content:
            out[rel] = "unchanged"
        else:
            out[rel] = "changed"
    return out


def stage_and_write(project_dir: Path, files: dict[str, str]) -> list[Path]:
    project_dir = Path(project_dir).resolve()
    backups: dict[Path, str | None] = {}  # None = file did not exist
    written: list[Path] = []
    created_dirs: list[Path] = []
    seen_dirs: set[Path] = set()
    try:
        for rel, content in files.items():
            target = _resolve_target(project_dir, rel)
            for d in _new_parent_dirs(target):
                if d not in seen_dirs:
                    seen_dirs.add(d)
                    created_dirs.append(d)
            backups[target] = target.read_text(encoding="utf-8") if target.exists() else None
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8", newline="\n")
            written.append(target)
    except BaseException as exc:
        failed: list[Path] = []
        for target, previous in backups.items():
            try:
                if previous is None:
                    target.unlink(missing_ok=True)
                else:
                    target.write_text(previous, encoding="utf-8", newline="\n")
            except OSError:
                failed.append(target)
        for d in sorted(created_dirs, key=lambda p: len(p.parts), reverse=True):
            with contextlib.suppress(OSError):
                d.rmdir()
        if failed:
            raise RuntimeError(f"Rollback incomplete; manual cleanup needed for: {failed}") from exc
        raise
    return written
