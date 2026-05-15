from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


class ProfileResolutionError(ValueError):
    """Raised when a profile-aware contract cannot select a runtime profile."""


def _nested_get(data: Any, dotted: str) -> Any:
    cur = data
    for token in dotted.split("."):
        if not isinstance(cur, dict) or token not in cur:
            return None
        cur = cur[token]
    return cur


def resolve_task_profile(task_dir: Path, *, allowed_profiles: list[str]) -> str:
    path = task_dir / "taskbeacon.yaml"
    if not path.exists():
        raise ProfileResolutionError("taskbeacon.yaml is required to resolve runtime.profile.")

    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    profile = _nested_get(data, "runtime.profile")
    if not isinstance(profile, str) or not profile.strip():
        raise ProfileResolutionError("runtime.profile is required for profile-aware TAPS contracts.")

    profile = profile.strip()
    if allowed_profiles and profile not in allowed_profiles:
        raise ProfileResolutionError(
            f"Unknown runtime.profile '{profile}'. Allowed profiles: {allowed_profiles}"
        )
    return profile


def profile_contract_ids(manifest: dict[str, Any], profile: str) -> list[str]:
    profile_contracts = manifest.get("profile_contracts")
    if not isinstance(profile_contracts, dict) or profile not in profile_contracts:
        raise ProfileResolutionError(f"Unknown runtime.profile '{profile}'.")

    common = [str(cid) for cid in list(manifest.get("common_contracts") or [])]
    selected = [str(cid) for cid in list(profile_contracts.get(profile) or [])]
    return common + selected
