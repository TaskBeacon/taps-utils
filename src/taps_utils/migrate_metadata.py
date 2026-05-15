from __future__ import annotations

import argparse
import re
from dataclasses import dataclass
from pathlib import Path

import yaml


OLD_KEYS = ("psyflow_taps", "psyflow_web_taps")


@dataclass
class MigrationResult:
    path: Path
    changed: bool
    message: str


def scan_taskbeacon_files(root: Path) -> list[Path]:
    root = root.expanduser().resolve()
    files: list[Path] = []
    for child in root.iterdir():
        if child.is_dir() and (child.name.startswith("T") or child.name.startswith("H")):
            path = child / "taskbeacon.yaml"
            if path.exists():
                files.append(path)
    return sorted(files, key=lambda p: p.parent.name)


def _infer_profile(path: Path) -> str | None:
    name = path.parent.name
    if name.startswith("T"):
        return "psyflow"
    if name.startswith("H"):
        return "web"
    return None


def migrate_file(
    path: Path,
    *,
    write: bool,
    version: str | None = None,
    profile: str | None = None,
) -> MigrationResult:
    text = path.read_text(encoding="utf-8")
    data = yaml.safe_load(text)
    if not isinstance(data, dict):
        return MigrationResult(path, False, "not a mapping")
    contracts = data.get("contracts")
    if not isinstance(contracts, dict):
        return MigrationResult(path, False, "missing contracts mapping")

    old_line = re.compile(r"^(\s*)(psyflow_taps|psyflow_web_taps):\s*(\S+)\s*$")
    taps_line = re.compile(r"^\s*taps:\s*\S+\s*$")
    lines = text.splitlines()
    has_taps = any(taps_line.match(line) for line in lines)
    old_matches = [(idx, match) for idx, line in enumerate(lines) if (match := old_line.match(line))]
    requested_version = str(version).strip() if version else None
    requested_profile = str(profile).strip() if profile else None
    if not old_matches and requested_version is None and requested_profile is None:
        return MigrationResult(path, False, "no old contract key found")

    new_lines: list[str] = []
    replaced = False
    changed = False
    for idx, line in enumerate(lines):
        match = old_line.match(line)
        if match is not None:
            if has_taps:
                changed = True
                continue
            if not replaced:
                indent, _old_key, old_version = match.groups()
                new_lines.append(f"{indent}taps: {requested_version or old_version}")
                replaced = True
                changed = True
            continue

        if requested_version is not None and taps_line.match(line):
            indent = line[: len(line) - len(line.lstrip())]
            new_line = f"{indent}taps: {requested_version}"
            new_lines.append(new_line)
            changed = changed or new_line != line
            continue

        new_lines.append(line)

    if requested_profile is not None:
        profile_line = re.compile(r"^(\s*)profile:\s*\S+\s*$")
        runtime_line = re.compile(r"^\s*runtime:\s*$")
        has_runtime = any(runtime_line.match(line) for line in new_lines)
        updated_profile = False
        with_profile: list[str] = []
        for line in new_lines:
            match = profile_line.match(line)
            if match is not None and has_runtime:
                indent = match.group(1)
                new_line = f"{indent}profile: {requested_profile}"
                with_profile.append(new_line)
                changed = changed or new_line != line
                updated_profile = True
            else:
                with_profile.append(line)
        new_lines = with_profile

        if not updated_profile:
            if has_runtime:
                inserted: list[str] = []
                for line in new_lines:
                    inserted.append(line)
                    if runtime_line.match(line):
                        inserted.append(f"  profile: {requested_profile}")
                        changed = True
                        updated_profile = True
                new_lines = inserted
            else:
                new_lines.extend(["runtime:", f"  profile: {requested_profile}"])
                changed = True

    new_text = "\n".join(new_lines).rstrip() + "\n"
    if write:
        path.write_text(new_text, encoding="utf-8")
    if old_matches:
        old_version = old_matches[0][1].group(3)
        msg = "removed old keys; kept contracts.taps" if has_taps else f"set contracts.taps -> {requested_version or old_version}"
    elif requested_version or requested_profile:
        msg = "updated"
        if requested_version:
            msg += f" contracts.taps -> {requested_version}"
        if requested_profile:
            msg += f" runtime.profile -> {requested_profile}"
    else:
        msg = "no changes"
    return MigrationResult(path, changed, msg)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="taps-migrate-metadata")
    parser.add_argument("root", help="TaskBeacon workspace root or a single task directory.")
    parser.add_argument("--write", action="store_true", help="Write changes. Omit for dry-run.")
    parser.add_argument("--task", action="append", default=[], help="Specific task directory name to migrate.")
    parser.add_argument("--version", default=None, help="Set contracts.taps to this version.")
    parser.add_argument("--profile", default=None, help="Set runtime.profile to this value.")
    parser.add_argument("--infer-profile", action="store_true", help="Infer runtime.profile from T*/H* task directory prefix.")
    ns = parser.parse_args(argv)

    root = Path(ns.root).expanduser().resolve()
    if (root / "taskbeacon.yaml").exists():
        files = [root / "taskbeacon.yaml"]
    else:
        files = scan_taskbeacon_files(root)
        if ns.task:
            wanted = set(ns.task)
            files = [p for p in files if p.parent.name in wanted]

    changed = 0
    for path in files:
        profile = ns.profile
        if ns.infer_profile and profile is None:
            profile = _infer_profile(path)
        result = migrate_file(path, write=bool(ns.write), version=ns.version, profile=profile)
        if result.changed:
            changed += 1
        action = "WRITE" if ns.write else "DRY"
        print(f"[{action}] {path}: {result.message}")
    print(f"[taps-migrate-metadata] files={len(files)} changed={changed} write={bool(ns.write)}")
