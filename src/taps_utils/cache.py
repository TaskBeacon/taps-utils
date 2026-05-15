from __future__ import annotations

import os
from pathlib import Path


def cache_root() -> Path:
    override = os.environ.get("TAPS_CACHE_DIR")
    if override:
        return Path(override).expanduser().resolve()
    return Path.home() / ".cache" / "taskbeacon" / "taps"


def cached_version_root(version: str) -> Path:
    return cache_root() / "contracts" / version
