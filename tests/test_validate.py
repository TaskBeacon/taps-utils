from pathlib import Path

from taps_utils.validate import _detect_contract_version, run_validator


def write_contract(root: Path) -> Path:
    version_root = root / "v0.1.0"
    version_root.mkdir(parents=True)
    (version_root / "manifest.yaml").write_text("contract_version: v0.1.0\ncontracts:\n  - taskbeacon\n", encoding="utf-8")
    (version_root / "taskbeacon.yaml").write_text(
        "\n".join(
            [
                "name: taskbeacon",
                "required_keys: [id, slug, title, acquisition, variant, maturity]",
                "required_nested_keys: [version.release_tag, contracts.taps]",
                "forbidden_nested_keys: [contracts.psyflow_taps, contracts.psyflow_web_taps]",
                "required_contract_version: v0.1.0",
            ]
        ),
        encoding="utf-8",
    )
    return root


def write_task(root: Path, contract_line: str) -> None:
    (root / "taskbeacon.yaml").write_text(
        "\n".join(
            [
                "id: T000000",
                "slug: demo",
                "title: Demo",
                "acquisition: behavior",
                "variant: baseline",
                "maturity: draft",
                "version:",
                "  release_tag: ''",
                "contracts:",
                f"  {contract_line}",
            ]
        ),
        encoding="utf-8",
    )


def test_detects_only_canonical_taps_contract(tmp_path):
    write_task(tmp_path, "taps: v0.1.0")

    assert _detect_contract_version(tmp_path) == "v0.1.0"


def test_does_not_detect_old_python_key(tmp_path):
    write_task(tmp_path, "psyflow_taps: v0.1.0")

    assert _detect_contract_version(tmp_path) is None


def test_old_python_key_fails_validation(tmp_path):
    contracts_root = write_contract(tmp_path / "contracts")
    task_root = tmp_path / "task"
    task_root.mkdir()
    write_task(task_root, "psyflow_taps: v0.1.0")

    report = run_validator(task_root, contracts_version="v0.1.0", contracts_root=contracts_root)

    assert report["summary"]["fail"] > 0


def test_old_web_key_fails_validation(tmp_path):
    contracts_root = write_contract(tmp_path / "contracts")
    task_root = tmp_path / "task"
    task_root.mkdir()
    write_task(task_root, "psyflow_web_taps: v0.1.0")

    report = run_validator(task_root, contracts_version="v0.1.0", contracts_root=contracts_root)

    assert report["summary"]["fail"] > 0
