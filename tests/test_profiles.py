from pathlib import Path

import pytest

from taps_utils.profiles import ProfileResolutionError, profile_contract_ids, resolve_task_profile


def test_resolve_task_profile_reads_runtime_profile(tmp_path: Path):
    task = tmp_path / "task"
    task.mkdir()
    (task / "taskbeacon.yaml").write_text(
        "\n".join(
            [
                "contracts:",
                "  taps: v0.2.0",
                "runtime:",
                "  profile: web",
            ]
        ),
        encoding="utf-8",
    )

    assert resolve_task_profile(task, allowed_profiles=["psyflow", "web"]) == "web"


def test_resolve_task_profile_rejects_missing_profile(tmp_path: Path):
    task = tmp_path / "task"
    task.mkdir()
    (task / "taskbeacon.yaml").write_text("contracts:\n  taps: v0.2.0\n", encoding="utf-8")

    with pytest.raises(ProfileResolutionError, match="runtime.profile"):
        resolve_task_profile(task, allowed_profiles=["psyflow", "web"])


def test_profile_contract_ids_merges_common_and_selected_profile():
    manifest = {
        "common_contracts": ["taskbeacon"],
        "profile_contracts": {
            "psyflow": ["required_files", "runtime_main"],
            "web": ["required_files", "runtime_main_ts"],
        },
    }

    assert profile_contract_ids(manifest, "web") == ["taskbeacon", "required_files", "runtime_main_ts"]


def test_profile_contract_ids_rejects_unknown_profile():
    manifest = {
        "common_contracts": ["taskbeacon"],
        "profile_contracts": {"web": ["required_files"]},
    }

    with pytest.raises(ProfileResolutionError, match="Unknown runtime.profile"):
        profile_contract_ids(manifest, "godot")
