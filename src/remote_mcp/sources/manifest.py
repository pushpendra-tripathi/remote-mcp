"""sources.lock.json — records what was generated, from what, by which version.

Read and written only by this CLI; the generated project never reads it at
runtime. `doctor` diffs reality against it.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

MANIFEST_NAME = "sources.lock.json"


class ManifestError(Exception):
    pass


@dataclass
class GeneratedFile:
    path: str
    sha256: str


@dataclass
class SourceEntry:
    kind: str
    name: str
    locator: str
    source_sha256: str
    selected: list[str]
    generated_files: list[GeneratedFile]
    generated_at: str
    generator_version: str


@dataclass
class Manifest:
    version: int = 1
    sources: list[SourceEntry] = field(default_factory=list)


def hash_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def load_manifest(project_dir: Path) -> Manifest:
    path = Path(project_dir) / MANIFEST_NAME
    if not path.exists():
        return Manifest()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        sources = [
            SourceEntry(
                **{
                    **s,
                    "generated_files": [GeneratedFile(**f) for f in s["generated_files"]],
                }
            )
            for s in raw["sources"]
        ]
        return Manifest(version=raw["version"], sources=sources)
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        raise ManifestError(f"Corrupt {MANIFEST_NAME}: {exc}") from exc


def save_manifest(project_dir: Path, manifest: Manifest) -> None:
    path = Path(project_dir) / MANIFEST_NAME
    path.write_text(json.dumps(asdict(manifest), indent=2) + "\n", encoding="utf-8")


def upsert_source(manifest: Manifest, entry: SourceEntry) -> None:
    for i, existing in enumerate(manifest.sources):
        if (existing.kind, existing.name) == (entry.kind, entry.name):
            manifest.sources[i] = entry
            return
    manifest.sources.append(entry)
