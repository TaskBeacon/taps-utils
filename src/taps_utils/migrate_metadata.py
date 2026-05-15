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


def migrate_file(path: Path, *, write: bool) -> MigrationResult:
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
    if not old_matches:
        return MigrationResult(path, False, "no old contract key found")

    new_lines: list[str] = []
    replaced = False
    for idx, line in enumerate(lines):
        match = old_line.match(line)
        if match is None:
            new_lines.append(line)
            continue
        if has_taps:
            continue
        if not replaced:
            indent, _old_key, version = match.groups()
            new_lines.append(f"{indent}taps: {version}")
            replaced = True
    new_text = "\n".join(new_lines).rstrip() + "\n"
    if write:
        path.write_text(new_text, encoding="utf-8")
    version = old_matches[0][1].group(3)
    return MigrationResult(path, True, "removed old keys; kept contracts.taps" if has_taps else f"set contracts.taps -> {version}")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="taps-migrate-metadata")
    parser.add_argument("root", help="TaskBeacon workspace root or a single task directory.")
    parser.add_argument("--write", action="store_true", help="Write changes. Omit for dry-run.")
    parser.add_argument("--task", action="append", default=[], help="Specific task directory name to migrate.")
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
        result = migrate_file(path, write=bool(ns.write))
        if result.changed:
            changed += 1
        action = "WRITE" if ns.write else "DRY"
        print(f"[{action}] {path}: {result.message}")
    print(f"[taps-migrate-metadata] files={len(files)} changed={changed} write={bool(ns.write)}")
