"""Shared selection engine: glob filtering + interactive picker.

Both `add openapi` and `add database` resolve their candidate sets through
resolve_selection(), so flags and the interactive picker share one code path.
"""

from __future__ import annotations

import difflib
import fnmatch
import sys
from dataclasses import dataclass

import typer
from rich.console import Console
from rich.table import Table

console = Console()


class SelectionError(Exception):
    """Selection resolved to nothing usable; message is user-facing."""


@dataclass(frozen=True)
class Candidate:
    id: str
    label: str
    group: str = ""


def filter_candidates(
    candidates: list[Candidate],
    include: list[str],
    exclude: list[str],
    tags: list[str],
) -> list[Candidate]:
    result = candidates
    if tags:
        result = [c for c in result if c.group in tags]
    if include:
        result = [c for c in result if any(fnmatch.fnmatch(c.id, g) for g in include)]
    if exclude:
        result = [c for c in result if not any(fnmatch.fnmatch(c.id, g) for g in exclude)]
    return result


def _nearest_misses(candidates: list[Candidate], patterns: list[str]) -> list[str]:
    names = [c.id for c in candidates]
    misses: list[str] = []
    for pat in patterns:
        misses.extend(difflib.get_close_matches(pat.strip("*"), names, n=3, cutoff=0.5))
    return list(dict.fromkeys(misses))


def prompt_selection(candidates: list[Candidate]) -> list[Candidate]:
    """Numbered multi-select on a TTY. Accepts e.g. '1,3-5' or 'all'."""
    table = Table(title="Available items")
    table.add_column("#", justify="right")
    table.add_column("id")
    table.add_column("label")
    table.add_column("group")
    for i, c in enumerate(candidates, start=1):
        table.add_row(str(i), c.id, c.label, c.group)
    console.print(table)

    raw = typer.prompt("Select (e.g. 1,3-5 or 'all')", default="all").strip().lower()
    if raw == "all":
        return list(candidates)
    picked: set[int] = set()
    try:
        for part in raw.split(","):
            part = part.strip()
            if "-" in part:
                lo, _, hi = part.partition("-")
                picked.update(range(int(lo), int(hi) + 1))
            elif part:
                picked.add(int(part))
    except ValueError:
        raise SelectionError(
            f"Invalid selection input: {raw!r}. Use e.g. '1,3-5' or 'all'."
        ) from None
    out = [candidates[i - 1] for i in sorted(picked) if 1 <= i <= len(candidates)]
    if not out:
        raise SelectionError("Nothing selected.")
    return out


def resolve_selection(
    candidates: list[Candidate],
    *,
    include: list[str],
    exclude: list[str],
    tags: list[str],
    yes: bool,
) -> list[Candidate]:
    if not candidates:
        raise SelectionError("Source contains no selectable items.")
    has_selectors = bool(include or tags)
    if yes and not has_selectors:
        raise SelectionError("Non-interactive mode requires --include or --tag.")
    if has_selectors:
        chosen = filter_candidates(candidates, include, exclude, tags)
        if not chosen:
            hint = _nearest_misses(candidates, include + tags)
            suffix = f" Did you mean: {', '.join(hint)}?" if hint else ""
            raise SelectionError(f"Selection matched nothing.{suffix}")
        return chosen
    if not sys.stdin.isatty():
        raise SelectionError("Non-interactive mode requires --include or --tag.")
    chosen = filter_candidates(candidates, [], exclude, [])
    if not chosen:
        raise SelectionError("All candidates were excluded; nothing to select.")
    return prompt_selection(chosen)
