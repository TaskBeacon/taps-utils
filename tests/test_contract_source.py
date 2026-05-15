from pathlib import Path
import zipfile

import pytest

from taps_utils.contract_source import ContractResolutionError, fetch_contracts, resolve_contracts_root


def make_contract(root: Path, version: str = "v0.1.0") -> Path:
    version_root = root / version
    version_root.mkdir(parents=True)
    (version_root / "manifest.yaml").write_text("contract_version: v0.1.0\ncontracts: []\n", encoding="utf-8")
    return version_root


def test_explicit_root_can_point_to_contracts_root(tmp_path):
    make_contract(tmp_path)

    assert resolve_contracts_root("v0.1.0", contracts_root=tmp_path) == tmp_path / "v0.1.0"


def test_explicit_root_can_point_to_version_root(tmp_path):
    version_root = make_contract(tmp_path)

    assert resolve_contracts_root("v0.1.0", contracts_root=version_root) == version_root


def test_missing_contract_reports_actionable_error(monkeypatch, tmp_path):
    monkeypatch.setenv("TAPS_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.delenv("TAPS_CONTRACTS_ROOT", raising=False)

    with pytest.raises(ContractResolutionError) as exc:
        resolve_contracts_root("v0.1.0")

    assert "taps-contracts fetch v0.1.0" in str(exc.value)


def test_fetch_contracts_extracts_requested_version(monkeypatch, tmp_path):
    zip_path = tmp_path / "source.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("taps-contracts-v0.1.0/contracts/v0.1.0/manifest.yaml", "contract_version: v0.1.0\ncontracts: []\n")
        zf.writestr("taps-contracts-v0.1.0/contracts/v0.1.0/taskbeacon.yaml", "name: taskbeacon\n")
    monkeypatch.setenv("TAPS_CACHE_DIR", str(tmp_path / "cache"))

    def fake_download(url: str, target: Path) -> None:
        target.write_bytes(zip_path.read_bytes())

    resolved = fetch_contracts("v0.1.0", downloader=fake_download)

    assert (resolved / "manifest.yaml").exists()
    assert (resolved / "taskbeacon.yaml").exists()
