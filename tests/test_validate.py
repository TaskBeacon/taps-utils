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


def write_profile_contract(root: Path) -> Path:
    version_root = root / "v0.2.0"
    (version_root / "common").mkdir(parents=True)
    (version_root / "profiles" / "web").mkdir(parents=True)
    (version_root / "profiles" / "psyflow").mkdir(parents=True)
    (version_root / "manifest.yaml").write_text(
        "\n".join(
            [
                "contract_version: v0.2.0",
                "profile_key: runtime.profile",
                "profiles: [psyflow, web]",
                "common_contracts:",
                "  - taskbeacon",
                "profile_contracts:",
                "  web:",
                "    - required_files",
                "    - config_web",
                "    - runtime_main_ts",
                "    - runtime_trial_ts",
                "  psyflow:",
                "    - required_files",
            ]
        ),
        encoding="utf-8",
    )
    (version_root / "common" / "taskbeacon.yaml").write_text(
        "\n".join(
            [
                "name: taskbeacon",
                "required_keys: [id, slug, title, acquisition, variant, maturity]",
                "required_nested_keys: [version.release_tag, contracts.taps, runtime.profile]",
                "required_contract_version: v0.2.0",
                "allowed_maturity: [prototype, draft, smoke_tested]",
                "allowed_runtime_profiles: [psyflow, web]",
            ]
        ),
        encoding="utf-8",
    )
    (version_root / "profiles" / "web" / "required_files.yaml").write_text(
        "\n".join(
            [
                "name: required_files",
                "required_paths:",
                "  - config/config.yaml",
                "  - main.ts",
                "  - src/run_trial.ts",
                "  - taskbeacon.yaml",
                "  - README.md",
            ]
        ),
        encoding="utf-8",
    )
    (version_root / "profiles" / "web" / "config_web.yaml").write_text(
        "\n".join(
            [
                "name: config_web",
                "file: config/config.yaml",
                "required_sections: [window, task, timing, stimuli, triggers]",
                "mandatory_nested_keys: [task.task_name, task.key_list, triggers.map]",
            ]
        ),
        encoding="utf-8",
    )
    (version_root / "profiles" / "web" / "runtime_main_ts.yaml").write_text(
        "\n".join(
            [
                "name: runtime_main_ts",
                "file: main.ts",
                "required_strings_all: [psyflow-web, mountTaskApp]",
                "required_function_tokens_any:",
                "  - export async function run",
            ]
        ),
        encoding="utf-8",
    )
    (version_root / "profiles" / "web" / "runtime_trial_ts.yaml").write_text(
        "\n".join(
            [
                "name: runtime_trial_ts",
                "file: src/run_trial.ts",
                "required_strings_all: [set_trial_context, TrialBuilder]",
                "required_function_tokens_any:",
                "  - export function run_trial",
            ]
        ),
        encoding="utf-8",
    )
    (version_root / "profiles" / "psyflow" / "required_files.yaml").write_text(
        "name: required_files\nrequired_paths: [main.py]\n",
        encoding="utf-8",
    )
    return root


def write_web_task(root: Path, *, include_profile: bool = True) -> None:
    (root / "config").mkdir()
    (root / "src").mkdir()
    runtime_lines = ["runtime:", "  profile: web"] if include_profile else []
    (root / "taskbeacon.yaml").write_text(
        "\n".join(
            [
                "id: H000000",
                "slug: demo",
                "title: Demo",
                "acquisition: behavior",
                "variant: html",
                "maturity: prototype",
                "version:",
                "  release_tag: '0.1.0'",
                "contracts:",
                "  taps: v0.2.0",
                *runtime_lines,
            ]
        ),
        encoding="utf-8",
    )
    (root / "README.md").write_text("# Demo\n", encoding="utf-8")
    (root / "main.ts").write_text(
        'import { mountTaskApp } from "psyflow-web";\nexport async function run(root: HTMLElement) { mountTaskApp; }\n',
        encoding="utf-8",
    )
    (root / "src" / "run_trial.ts").write_text(
        'import { set_trial_context, TrialBuilder } from "psyflow-web";\nexport function run_trial(trial: TrialBuilder) { set_trial_context; return trial; }\n',
        encoding="utf-8",
    )
    (root / "config" / "config.yaml").write_text(
        "\n".join(
            [
                "window: {size: [800, 600]}",
                "task:",
                "  task_name: demo",
                "  key_list: [f, j]",
                "timing: {}",
                "stimuli: {}",
                "triggers:",
                "  map: {}",
            ]
        ),
        encoding="utf-8",
    )


def test_v020_web_profile_validates_typescript_layout(tmp_path):
    contracts_root = write_profile_contract(tmp_path / "contracts")
    task_root = tmp_path / "task"
    task_root.mkdir()
    write_web_task(task_root)

    report = run_validator(task_root, contracts_version="v0.2.0", contracts_root=contracts_root)

    assert report["summary"]["fail"] == 0
    assert [row["name"] for row in report["results"]] == [
        "taskbeacon",
        "required_files",
        "config_web",
        "runtime_main_ts",
        "runtime_trial_ts",
    ]


def test_v020_requires_runtime_profile(tmp_path):
    contracts_root = write_profile_contract(tmp_path / "contracts")
    task_root = tmp_path / "task"
    task_root.mkdir()
    write_web_task(task_root, include_profile=False)

    report = run_validator(task_root, contracts_version="v0.2.0", contracts_root=contracts_root)

    assert report["summary"]["fail"] == 1
    assert report["results"][0]["name"] == "profile"
    assert "runtime.profile" in report["results"][0]["messages"][0]
