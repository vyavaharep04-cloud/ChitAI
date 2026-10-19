"""The run manifest (M8 Stage 5).

Written *last*, so a directory without `manifest.json` is an incomplete run. It records what was
run (the configuration's canonical hash, seeds, counts by status) and what was produced (every
file with its SHA-256 and size), so a later run of the same configuration can be compared byte
for byte. It contains no clock time and no directory path; the only machine-specific part is the
`environment` block (Python version and implementation), kept apart from everything else.
"""

from __future__ import annotations

import hashlib
import json
import platform
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from .. import __version__

MANIFEST_SCHEMA_VERSION = 1
MANIFEST_NAME = "manifest.json"


def file_digest(path: Path) -> tuple[str, int]:
    """(SHA-256 hex digest, size in bytes) of a file, read in chunks."""
    digest = hashlib.sha256()
    size = 0
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def text_digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def build_manifest(
    *, config_canonical: str, config_data: Mapping[str, Any], directory: Path, file_names: list[str],
    status_counts: Mapping[str, int],
) -> dict[str, Any]:  # fmt: skip
    files = {}
    for name in sorted(file_names):
        digest, size = file_digest(directory / name)
        files[name] = {"sha256": digest, "bytes": size}
    return {
        "manifest_schema_version": MANIFEST_SCHEMA_VERSION,
        "chitai_version": __version__,
        "config_sha256": text_digest(config_canonical),
        "batch_seed": config_data["batch_seed"],
        "game_count": config_data["game_count"],
        "games_per_seed": config_data["games_per_seed"],
        "rotate_seats": config_data["rotate_seats"],
        "num_players": config_data["num_players"],
        "num_rounds": config_data["num_rounds"],
        "status_counts": dict(status_counts),
        "files": files,
        "environment": {"python": platform.python_version(), "implementation": platform.python_implementation()},
    }


def manifest_text(manifest: Mapping[str, Any]) -> str:
    return json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=True, allow_nan=False) + "\n"


__all__ = ["MANIFEST_NAME", "MANIFEST_SCHEMA_VERSION", "build_manifest", "file_digest", "manifest_text", "text_digest"]
