from __future__ import annotations

import os
import shutil
import tempfile
import urllib.request
import zipfile
from collections.abc import Callable
from pathlib import Path

from .cache import cached_version_root


class ContractResolutionError(FileNotFoundError):
    """Raised when a requested TAPS contract version cannot be resolved."""


DownloadFn = Callable[[str, Path], None]


def _version_root(candidate: Path, version: str) -> Path:
    candidate = candidate.expanduser().resolve()
    if candidate.name == version and (candidate / "manifest.yaml").exists():
        return candidate
    return candidate / version


def _require_existing(path: Path, version: str) -> Path:
    if (path / "manifest.yaml").exists():
        return path
    raise ContractResolutionError(
        f"Could not resolve TAPS contracts for {version}. "
        "Provide --contracts-root, set TAPS_CONTRACTS_ROOT, "
        f"or run `taps-contracts fetch {version}`."
    )


def resolve_contracts_root(version: str, *, contracts_root: str | Path | None = None) -> Path:
    if contracts_root is not None:
        return _require_existing(_version_root(Path(contracts_root), version), version)
    env_root = os.environ.get("TAPS_CONTRACTS_ROOT")
    if env_root:
        return _require_existing(_version_root(Path(env_root), version), version)
    return _require_existing(cached_version_root(version), version)


def default_contract_zip_url(version: str) -> str:
    return f"https://github.com/TaskBeacon/taps/archive/refs/tags/contracts-{version}.zip"


def _download(url: str, target: Path) -> None:
    with urllib.request.urlopen(url, timeout=30) as response:
        target.write_bytes(response.read())


def fetch_contracts(
    version: str,
    *,
    url: str | None = None,
    downloader: DownloadFn | None = None,
    force: bool = False,
) -> Path:
    destination = cached_version_root(version)
    if destination.exists() and not force:
        return _require_existing(destination, version)

    downloader = downloader or _download
    source_url = url or default_contract_zip_url(version)
    destination.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory() as td:
        zip_path = Path(td) / "contracts.zip"
        extract_root = Path(td) / "extract"
        downloader(source_url, zip_path)
        with zipfile.ZipFile(zip_path) as zf:
            zf.extractall(extract_root)
        matches = [
            p for p in extract_root.rglob("manifest.yaml")
            if p.parent.name == version and p.parent.parent.name == "contracts"
        ]
        if not matches:
            raise ContractResolutionError(f"Downloaded archive did not contain contracts/{version}/manifest.yaml")
        if destination.exists():
            shutil.rmtree(destination)
        shutil.copytree(matches[0].parent, destination)

    return _require_existing(destination, version)
