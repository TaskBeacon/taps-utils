from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .contract_source import resolve_contracts_root

try:
    import yaml  # type: ignore
except ModuleNotFoundError:  # pragma: no cover
    yaml = None


@dataclass
class ContractResult:
    name: str
    status: str  # PASS | WARN | FAIL
    messages: list[str] = field(default_factory=list)
    suggestions: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "status": self.status,
            "messages": list(self.messages),
            "suggestions": list(self.suggestions),
        }


def _read_text_with_fallback(path: Path, *, encodings: tuple[str, ...] = ("utf-8-sig", "utf-8", "cp1252", "latin-1")) -> str:
    last_err: Exception | None = None
    for enc in encodings:
        try:
            return path.read_text(encoding=enc)
        except UnicodeDecodeError as exc:
            last_err = exc
    if last_err is not None:
        raise last_err
    return path.read_text(encoding="utf-8")


def _load_yaml(path: Path) -> Any:
    if yaml is None:  # pragma: no cover
        raise ModuleNotFoundError("PyYAML is required. Install with `pip install pyyaml`.")
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _nested_get(data: Any, dotted: str) -> Any:
    cur = data
    for token in dotted.split("."):
        if not isinstance(cur, dict) or token not in cur:
            return None
        cur = cur[token]
    return cur


def _nested_has(data: Any, dotted: str) -> bool:
    cur = data
    for token in dotted.split("."):
        if not isinstance(cur, dict) or token not in cur:
            return False
        cur = cur[token]
    return True


def _is_number(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _type_ok(value: Any, type_name: str) -> bool:
    t = str(type_name or "").strip().lower()
    if t == "str":
        return isinstance(value, str)
    if t == "int":
        return isinstance(value, int) and not isinstance(value, bool)
    if t == "number":
        return _is_number(value)
    if t == "bool":
        return isinstance(value, bool)
    if t == "mapping":
        return isinstance(value, dict)
    if t == "list":
        return isinstance(value, list)
    if t == "list_str":
        return isinstance(value, list) and all(isinstance(x, str) for x in value)
    if t == "list_int":
        return isinstance(value, list) and all(isinstance(x, int) and not isinstance(x, bool) for x in value)
    if t == "list_number":
        return isinstance(value, list) and all(_is_number(x) for x in value)
    return True


def _validate_value_spec(path: str, value: Any, spec: dict[str, Any]) -> list[str]:
    issues: list[str] = []
    expected_type = spec.get("type")
    if expected_type and not _type_ok(value, str(expected_type)):
        issues.append(f"{path} type mismatch: expected {expected_type}, got {type(value).__name__}")
        return issues

    if isinstance(value, str):
        min_length = spec.get("min_length")
        if min_length is not None:
            try:
                if len(value) < int(min_length):
                    issues.append(f"{path} must have length >= {min_length}")
            except Exception:
                pass

    if isinstance(value, list):
        min_items = spec.get("min_items")
        max_items = spec.get("max_items")
        exact_len = spec.get("exact_len")
        if min_items is not None:
            try:
                if len(value) < int(min_items):
                    issues.append(f"{path} must have at least {min_items} item(s)")
            except Exception:
                pass
        if max_items is not None:
            try:
                if len(value) > int(max_items):
                    issues.append(f"{path} must have at most {max_items} item(s)")
            except Exception:
                pass
        if exact_len is not None:
            try:
                if len(value) != int(exact_len):
                    issues.append(f"{path} must have exactly {exact_len} item(s)")
            except Exception:
                pass

    if isinstance(value, dict):
        min_items = spec.get("min_items")
        if min_items is not None:
            try:
                if len(value) < int(min_items):
                    issues.append(f"{path} must contain at least {min_items} key(s)")
            except Exception:
                pass

    if _is_number(value):
        min_v = spec.get("min")
        max_v = spec.get("max")
        if min_v is not None:
            try:
                if float(value) < float(min_v):
                    issues.append(f"{path} must be >= {min_v}")
            except Exception:
                pass
        if max_v is not None:
            try:
                if float(value) > float(max_v):
                    issues.append(f"{path} must be <= {max_v}")
            except Exception:
                pass

    allowed = spec.get("allowed")
    if allowed is not None:
        try:
            if value not in list(allowed):
                issues.append(f"{path} must be one of {list(allowed)}, got {value!r}")
        except Exception:
            pass

    disallowed = spec.get("disallowed")
    if disallowed is not None:
        try:
            blocked = list(disallowed)
            if isinstance(value, str):
                blocked_lower = [str(x).strip().lower() for x in blocked]
                if value.strip().lower() in blocked_lower:
                    issues.append(f"{path} must not be one of {blocked}, got {value!r}")
            elif value in blocked:
                issues.append(f"{path} must not be one of {blocked}, got {value!r}")
        except Exception:
            pass

    pattern = spec.get("pattern")
    if pattern is not None and isinstance(value, str):
        try:
            if re.search(str(pattern), value) is None:
                issues.append(f"{path} must match pattern {pattern!r}, got {value!r}")
        except Exception:
            pass

    return issues


def _check_value_specs(data: Any, specs: dict[str, Any] | None, *, required: bool) -> tuple[list[str], list[str]]:
    fails: list[str] = []
    warns: list[str] = []
    if not isinstance(specs, dict):
        return fails, warns

    for path, raw_spec in specs.items():
        spec = raw_spec if isinstance(raw_spec, dict) else {}
        exists = _nested_has(data, str(path))
        if not exists:
            msg = f"Missing {'required' if required else 'recommended'} value: {path}"
            if required:
                fails.append(msg)
            else:
                warns.append(msg)
            continue
        value = _nested_get(data, str(path))
        issues = _validate_value_spec(str(path), value, spec)
        for issue in issues:
            if required:
                fails.append(issue)
            else:
                warns.append(issue)
    return fails, warns


def _check_optional_value_specs(data: Any, specs: dict[str, Any] | None) -> tuple[list[str], list[str]]:
    fails: list[str] = []
    warns: list[str] = []
    if not isinstance(specs, dict):
        return fails, warns

    for path, raw_spec in specs.items():
        spec = raw_spec if isinstance(raw_spec, dict) else {}
        exists = _nested_has(data, str(path))
        if not exists:
            continue
        value = _nested_get(data, str(path))
        issues = _validate_value_spec(str(path), value, spec)
        for issue in issues:
            fails.append(issue)
    return fails, warns


def _split_import_path(import_path: str) -> tuple[str | None, str | None]:
    raw = str(import_path or "").strip()
    if not raw:
        return None, None
    if ":" in raw:
        mod_name, attr_name = raw.split(":", 1)
    elif "." in raw:
        mod_name, attr_name = raw.rsplit(".", 1)
    else:
        return None, None
    mod_name = mod_name.strip()
    attr_name = attr_name.strip()
    if not mod_name or not attr_name:
        return None, None
    return mod_name, attr_name


def _extract_class_body(text: str, class_name: str) -> str | None:
    cls_pat = re.compile(rf"^class\s+{re.escape(class_name)}\b[^\n]*:\s*$", re.MULTILINE)
    cls_match = cls_pat.search(text)
    if cls_match is None:
        # fallback for one-line class declarations with trailing comments
        cls_pat = re.compile(rf"^class\s+{re.escape(class_name)}\b[^\n]*:", re.MULTILINE)
        cls_match = cls_pat.search(text)
        if cls_match is None:
            return None
    start = cls_match.end()
    next_cls = re.search(r"^class\s+\w+\b[^\n]*:", text[start:], re.MULTILINE)
    end = len(text) if next_cls is None else (start + next_cls.start())
    return text[start:end]


def _as_lower_str_set(values: Any) -> set[str]:
    out: set[str] = set()
    if not isinstance(values, list):
        return out
    for item in values:
        s = str(item or "").strip().lower()
        if s:
            out.add(s)
    return out


def _normalize_md_col(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(text or "").lower())


def _extract_md_table_headers(text: str) -> list[list[str]]:
    headers: list[list[str]] = []
    lines = text.splitlines()
    for i in range(len(lines) - 1):
        head = lines[i].strip()
        sep = lines[i + 1].strip()
        if not (head.startswith("|") and sep.startswith("|")):
            continue
        if re.match(r"^\|\s*:?-{2,}", sep) is None:
            continue
        cols = [c.strip() for c in head.strip("|").split("|")]
        if cols:
            headers.append(cols)
    return headers


def _md_has_columns(text: str, required: list[str]) -> bool:
    if not required:
        return True
    required_norm = {_normalize_md_col(c) for c in required if str(c or "").strip()}
    if not required_norm:
        return True
    for header in _extract_md_table_headers(text):
        header_norm = {_normalize_md_col(c) for c in header if str(c or "").strip()}
        if required_norm.issubset(header_norm):
            return True
    return False


def _ast_is_nonempty_string(node: ast.AST) -> bool:
    return isinstance(node, ast.Constant) and isinstance(node.value, str) and bool(node.value.strip())


def _check_run_trial_text_localization(text: str, cfg: dict[str, Any]) -> list[str]:
    issues: list[str] = []
    try:
        tree = ast.parse(text)
    except SyntaxError:
        issues.append("src/run_trial.py could not be parsed for text-localization checks.")
        return issues

    forbidden_calls = {
        str(x or "").strip()
        for x in list(cfg.get("forbidden_text_constructor_calls") or [])
        if str(x or "").strip()
    }

    fail_literal_ctor = bool(cfg.get("fail_on_literal_text_constructor", False))
    fail_literal_settext = bool(cfg.get("fail_on_literal_settext", False))
    fail_literal_attr = bool(cfg.get("fail_on_literal_text_attr_assign", False))

    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            fn_name = ""
            if isinstance(node.func, ast.Name):
                fn_name = node.func.id
            elif isinstance(node.func, ast.Attribute):
                fn_name = node.func.attr

            if fail_literal_ctor and fn_name in forbidden_calls:
                for kw in node.keywords:
                    if kw.arg == "text" and _ast_is_nonempty_string(kw.value):
                        issues.append(
                            "src/run_trial.py hardcodes participant-facing text via "
                            f"{fn_name}(text='...'); move text to config stimuli."
                        )
                        break

            if fail_literal_settext and isinstance(node.func, ast.Attribute) and node.func.attr == "setText":
                if node.args and _ast_is_nonempty_string(node.args[0]):
                    issues.append(
                        "src/run_trial.py uses setText('...') with a literal string; "
                        "move participant-facing text to config stimuli."
                    )

        if fail_literal_attr and isinstance(node, ast.Assign) and _ast_is_nonempty_string(node.value):
            for target in node.targets:
                if isinstance(target, ast.Attribute) and target.attr == "text":
                    issues.append(
                        "src/run_trial.py assigns literal participant-facing text to .text; "
                        "move text to config stimuli."
                    )
                    break

    return issues


def _find_visible_show_without_context(text: str) -> list[str]:
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return []

    run_trial_fn = None
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == "run_trial":
            run_trial_fn = node
            break
    if run_trial_fn is None:
        return []

    context_units: set[str] = set()
    unit_stims: dict[str, list[str]] = {}
    unit_labels: dict[str, str] = {}
    warnings: list[str] = []

    def _stmt_call(stmt: ast.stmt) -> ast.Call | None:
        if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call):
            return stmt.value
        if isinstance(stmt, ast.Assign) and isinstance(stmt.value, ast.Call):
            return stmt.value
        return None

    def _kw_expr(call: ast.Call, key: str) -> str:
        for kw in call.keywords:
            if kw.arg == key:
                try:
                    return ast.unparse(kw.value)
                except Exception:  # noqa: BLE001
                    return ""
        return ""

    def _node_name(node: ast.AST) -> str:
        return node.id if isinstance(node, ast.Name) else ""

    def _add_stim_exprs(node: ast.AST) -> list[str]:
        out: list[str] = []
        current = node
        while isinstance(current, ast.Call):
            if isinstance(current.func, ast.Attribute) and current.func.attr == "add_stim" and current.args:
                try:
                    out.append(ast.unparse(current.args[0]))
                except Exception:  # noqa: BLE001
                    pass
                current = current.func.value
            elif isinstance(current.func, ast.Attribute):
                current = current.func.value
            else:
                break
        out.reverse()
        return out

    def _unit_label_expr(node: ast.AST) -> str:
        current = node
        while isinstance(current, ast.Call):
            if isinstance(current.func, ast.Name) and current.func.id in {"StimUnit", "make_unit"}:
                label = _kw_expr(current, "unit_label")
                if label:
                    return label
                if current.args:
                    try:
                        return ast.unparse(current.args[0])
                    except Exception:  # noqa: BLE001
                        return ""
                return ""
            if isinstance(current.func, ast.Attribute):
                current = current.func.value
            else:
                break
        return ""

    def _walk(stmts: list[ast.stmt]) -> None:
        for stmt in stmts:
            if isinstance(stmt, ast.Assign) and len(stmt.targets) == 1 and isinstance(stmt.targets[0], ast.Name):
                var = stmt.targets[0].id
                label = _unit_label_expr(stmt.value)
                if label:
                    unit_labels[var] = label
                stim_exprs = _add_stim_exprs(stmt.value)
                if stim_exprs:
                    unit_stims.setdefault(var, []).extend(stim_exprs)

            if isinstance(stmt, ast.If):
                _walk(stmt.body)
                _walk(stmt.orelse)
                continue
            if isinstance(stmt, (ast.For, ast.AsyncFor, ast.While, ast.With, ast.AsyncWith)):
                _walk(stmt.body)
                _walk(getattr(stmt, "orelse", []))
                continue
            if isinstance(stmt, ast.Try):
                _walk(stmt.body)
                for handler in stmt.handlers:
                    _walk(handler.body)
                _walk(stmt.orelse)
                _walk(stmt.finalbody)
                continue

            call = _stmt_call(stmt)
            if call is None:
                continue
            if isinstance(call.func, ast.Name) and call.func.id == "set_trial_context" and call.args:
                unit_var = _node_name(call.args[0])
                if unit_var:
                    context_units.add(unit_var)
                continue
            if not (isinstance(call.func, ast.Attribute) and call.func.attr == "show"):
                continue

            base = call.func.value
            unit_var = _node_name(base)
            stim_exprs = list(unit_stims.get(unit_var, [])) if unit_var else []
            for expr in _add_stim_exprs(base):
                if expr not in stim_exprs:
                    stim_exprs.append(expr)
            if not stim_exprs:
                continue
            if unit_var and unit_var in context_units:
                continue

            label = _unit_label_expr(base)
            if not label and unit_var:
                label = unit_labels.get(unit_var, "")
            token = str(label or unit_var or "show() phase").strip().strip("'\"")
            warnings.append(token)

    _walk(run_trial_fn.body)
    deduped: list[str] = []
    seen: set[str] = set()
    for item in warnings:
        if not item or item in seen:
            continue
        seen.add(item)
        deduped.append(item)
    return deduped


def _looks_like_mid_identity(value: Any) -> bool:
    low = str(value or "").strip().lower()
    if not low:
        return False
    if "monetary incentive delay" in low:
        return True
    if "incentive delay" in low and "mid" in low:
        return True
    return re.search(r"(?<![a-z0-9])mid(?![a-z0-9])", low) is not None


def _is_mid_task_identity(task_dir: Path) -> bool:
    candidates: list[str] = [task_dir.name]

    taskbeacon_path = task_dir / "taskbeacon.yaml"
    if taskbeacon_path.exists():
        try:
            data = _load_yaml(taskbeacon_path) or {}
            if isinstance(data, dict):
                for key in ("id", "slug", "title"):
                    value = data.get(key)
                    if isinstance(value, str) and value.strip():
                        candidates.append(value)
        except Exception:
            pass

    base_cfg_path = task_dir / "config" / "config.yaml"
    if base_cfg_path.exists():
        try:
            data = _load_yaml(base_cfg_path) or {}
            task_name = _nested_get(data, "task.task_name")
            if isinstance(task_name, str) and task_name.strip():
                candidates.append(task_name)
        except Exception:
            pass

    readme_path = task_dir / "README.md"
    if readme_path.exists():
        try:
            text = _read_text_with_fallback(readme_path)
            if text:
                candidates.append(text[:1200])
        except Exception:
            pass

    return any(_looks_like_mid_identity(item) for item in candidates)


def _check_mid_template_leakage(task_dir: Path) -> tuple[list[str], list[str]]:
    fails: list[str] = []
    warns: list[str] = []

    if _is_mid_task_identity(task_dir):
        return fails, warns

    paths = [
        task_dir / "config" / "config.yaml",
        task_dir / "config" / "config_qa.yaml",
        task_dir / "config" / "config_scripted_sim.yaml",
        task_dir / "config" / "config_sampler_sim.yaml",
        task_dir / "src" / "run_trial.py",
        task_dir / "README.md",
    ]
    chunks: list[str] = []
    for path in paths:
        if not path.exists():
            continue
        try:
            chunks.append(_read_text_with_fallback(path).lower())
        except Exception:
            continue
    if not chunks:
        return fails, warns

    corpus = "\n".join(chunks)
    signatures = {
        "mid_docs": ("monetary incentive delay" in corpus)
        or (re.search(r"(?<![a-z0-9])mid task(?![a-z0-9])", corpus) is not None),
        "mid_stim_ids": all(tok in corpus for tok in ("win_cue", "lose_cue"))
        and ("neutral_cue" in corpus or "neut_cue" in corpus),
        "mid_timing": ("anticipation_duration" in corpus) and ("prefeedback_duration" in corpus),
        "mid_trigger_map": all(tok in corpus for tok in ("win_cue_onset", "lose_cue_onset"))
        and ("neutral_cue_onset" in corpus or "neut_cue_onset" in corpus),
        "mid_scoring": ("target_hit" in corpus) and ("feedback_delta" in corpus),
    }

    matched = sorted([name for name, hit in signatures.items() if hit])
    if len(matched) >= 2:
        fails.append(
            "Detected MID-template leakage in a non-MID task: "
            f"matched signatures {matched}. Remove paradigm-specific MID defaults."
        )
    elif len(matched) == 1:
        warns.append(
            "Found a MID-template marker in a non-MID task "
            f"({matched[0]}). Confirm this is intentional."
        )

    return fails, warns


def _normalize_gitignore_entry(value: str) -> str:
    token = str(value or "").strip().replace("\\", "/")
    if token.startswith("./"):
        token = token[2:]
    return token


def _gitignore_entry_matches(entry: str, option: str) -> bool:
    e = _normalize_gitignore_entry(entry)
    o = _normalize_gitignore_entry(option)
    if not e or not o:
        return False
    if e == o:
        return True
    e_noslash = e.lstrip("/")
    o_noslash = o.lstrip("/")
    if e_noslash == o_noslash:
        return True
    if e_noslash.endswith("/") and e_noslash[:-1] == o_noslash:
        return True
    if o_noslash.endswith("/") and o_noslash[:-1] == e_noslash:
        return True
    return False


def _gitignore_has_any(entries: list[str], options: list[str]) -> bool:
    if not options:
        return False
    for ent in entries:
        for opt in options:
            if _gitignore_entry_matches(ent, opt):
                return True
    return False


def _check_stimulus_contract(task_dir: Path, data: Any, cfg: dict[str, Any]) -> tuple[list[str], list[str]]:
    fails: list[str] = []
    warns: list[str] = []

    stim_cfg = _nested_get(data, "stimuli")
    if not isinstance(stim_cfg, dict):
        fails.append("stimuli must be a mapping of stimulus_name -> spec.")
        return fails, warns

    supported_types = _as_lower_str_set(cfg.get("stim_supported_types"))
    asset_types = _as_lower_str_set(cfg.get("stim_asset_types"))
    any_asset_keys = [str(x) for x in list(cfg.get("stim_asset_path_keys_any") or []) if str(x).strip()]
    if not any_asset_keys:
        any_asset_keys = ["file", "filename", "image", "path"]

    raw_key_map = cfg.get("stim_asset_path_keys_by_type")
    type_key_map: dict[str, list[str]] = {}
    if isinstance(raw_key_map, dict):
        for k, v in raw_key_map.items():
            keys = [str(x) for x in list(v or []) if str(x).strip()]
            if keys:
                type_key_map[str(k).strip().lower()] = keys

    raw_prefixes = list(cfg.get("stim_asset_path_prefixes") or [])
    prefixes = [str(x).replace("\\", "/") for x in raw_prefixes if str(x).strip()]
    if not prefixes:
        prefixes = ["assets/", "./assets/"]

    for stim_name, stim_spec in stim_cfg.items():
        if not isinstance(stim_spec, dict):
            fails.append(f"stimuli.{stim_name} must be a mapping.")
            continue

        raw_type = stim_spec.get("type")
        if not isinstance(raw_type, str) or not raw_type.strip():
            fails.append(f"stimuli.{stim_name} missing required string field: type")
            continue

        stim_type = raw_type.strip().lower()
        if supported_types and stim_type not in supported_types:
            fails.append(
                f"stimuli.{stim_name}.type '{raw_type}' is unsupported. "
                f"Allowed: {sorted(supported_types)}"
            )
            continue

        if stim_type not in asset_types:
            continue

        candidate_keys = type_key_map.get(stim_type, any_asset_keys)
        selected_key = None
        selected_path = None
        for key in candidate_keys:
            value = stim_spec.get(key)
            if isinstance(value, str) and value.strip():
                selected_key = key
                selected_path = value.strip()
                break

        if selected_path is None:
            warns.append(
                f"stimuli.{stim_name} uses asset-backed type '{stim_type}' "
                f"but has no explicit asset path key in {candidate_keys}."
            )
            continue

        norm = selected_path.replace("\\", "/")
        if not any(norm.startswith(p) for p in prefixes):
            warns.append(
                f"stimuli.{stim_name}.{selected_key} should be under assets/ "
                f"(expected prefixes: {prefixes}), got '{selected_path}'."
            )

        if norm.startswith("./"):
            norm = norm[2:]

        rel_path = Path(norm)
        if not rel_path.is_absolute() and norm.startswith("assets/"):
            fs_path = task_dir / rel_path
            if not fs_path.exists():
                warns.append(f"stimuli.{stim_name}.{selected_key} path not found: {fs_path}")

    return fails, warns


def _check_condition_weight_config(data: Any) -> tuple[list[str], list[str]]:
    fails: list[str] = []
    warns: list[str] = []

    task_cfg = _nested_get(data, "task")
    if not isinstance(task_cfg, dict):
        return fails, warns

    conditions = task_cfg.get("conditions")
    if not isinstance(conditions, list):
        return fails, warns
    labels = [str(c) for c in conditions]
    if not labels:
        return fails, warns

    if "condition_weights" not in task_cfg:
        return fails, warns

    raw = task_cfg.get("condition_weights")
    if raw is None:
        # Explicit null means "use even/default generation".
        return fails, warns

    values: list[Any]
    if isinstance(raw, dict):
        keyed = {str(k): v for k, v in raw.items()}
        missing = [label for label in labels if label not in keyed]
        extra = [key for key in keyed if key not in labels]
        if missing:
            fails.append(f"task.condition_weights missing condition key(s): {missing}")
        if extra:
            fails.append(f"task.condition_weights has unknown condition key(s): {extra}")
        values = [keyed.get(label) for label in labels]
    elif isinstance(raw, list):
        if len(raw) != len(labels):
            fails.append(
                "task.condition_weights length mismatch: expected "
                f"{len(labels)} values for conditions {labels}, got {len(raw)}"
            )
        values = list(raw)
    else:
        fails.append("task.condition_weights must be null, list, or mapping keyed by task.conditions.")
        return fails, warns

    numeric: list[float] = []
    for i, value in enumerate(values):
        if value is None:
            continue
        if not _is_number(value):
            fails.append(f"task.condition_weights[{i}] must be numeric, got {type(value).__name__}")
            continue
        val = float(value)
        if val <= 0:
            fails.append(f"task.condition_weights[{i}] must be > 0, got {val}")
        numeric.append(val)

    if numeric and sum(numeric) <= 0:
        fails.append("task.condition_weights sum must be > 0.")

    return fails, warns


def _check_responder_spec(task_dir: Path, data: Any, cfg: dict[str, Any]) -> tuple[list[str], list[str]]:
    fails: list[str] = []
    warns: list[str] = []

    rtype = _nested_get(data, "sim.responder.type")
    if not isinstance(rtype, str) or not rtype.strip():
        fails.append("sim.responder.type is required and must be a non-empty string.")
        return fails, warns

    spec = rtype.strip()
    builtins = _as_lower_str_set(cfg.get("builtin_types"))
    if not builtins:
        builtins = {"scripted", "null"}
    if spec.lower() in builtins:
        return fails, warns

    module_name, class_name = _split_import_path(spec)
    if module_name is None or class_name is None:
        fails.append(
            "sim.responder.type must be a builtin responder or an import path "
            "formatted as 'module.path:ClassName' (or 'module.path.ClassName')."
        )
        return fails, warns

    local_prefixes = [str(x) for x in list(cfg.get("local_module_prefixes") or []) if str(x).strip()]
    if not local_prefixes:
        local_prefixes = ["responders."]
    is_local_prefix = any(module_name.startswith(p) for p in local_prefixes)

    mod_rel = Path(*module_name.split(".")).with_suffix(".py")
    module_path = task_dir / mod_rel

    for rel in list(cfg.get("recommended_paths") or []):
        rp = task_dir / str(rel)
        if not rp.exists():
            warns.append(f"Missing recommended responder path: {rel}")

    if is_local_prefix and not module_path.exists():
        fails.append(
            f"Custom responder module not found for sim.responder.type='{spec}': {module_path}"
        )
        return fails, warns

    if not module_path.exists():
        warns.append(
            f"Responder module '{module_name}' is outside task tree or missing locally; "
            "static method checks skipped."
        )
        return fails, warns

    text = _read_text_with_fallback(module_path)
    cls_body = _extract_class_body(text, class_name)
    if cls_body is None:
        fails.append(f"Class '{class_name}' not found in {module_path}.")
        return fails, warns

    required_methods = [str(x) for x in list(cfg.get("required_methods") or []) if str(x).strip()]
    if not required_methods:
        required_methods = ["act"]
    optional_methods = [str(x) for x in list(cfg.get("optional_methods") or []) if str(x).strip()]

    for method_name in required_methods:
        meth_pat = re.compile(rf"\bdef\s+{re.escape(method_name)}\s*\(")
        if meth_pat.search(cls_body) is None:
            fails.append(
                f"Responder class '{class_name}' missing required method: {method_name}()"
            )

    for method_name in optional_methods:
        meth_pat = re.compile(rf"\bdef\s+{re.escape(method_name)}\s*\(")
        if meth_pat.search(cls_body) is None:
            warns.append(
                f"Responder class '{class_name}' missing optional lifecycle method: {method_name}()"
            )

    rec_tokens_any = [str(x) for x in list(cfg.get("recommended_import_tokens_any") or []) if str(x).strip()]
    if rec_tokens_any and not any(tok in text for tok in rec_tokens_any):
        warns.append(
            f"{module_path} is missing recommended contract import tokens (any): {rec_tokens_any}"
        )

    return fails, warns


def _result(name: str, fails: list[str], warns: list[str], suggestions: list[str] | None = None) -> ContractResult:
    status = "PASS"
    if fails:
        status = "FAIL"
    elif warns:
        status = "WARN"
    messages = [f"FAIL: {m}" for m in fails] + [f"WARN: {m}" for m in warns]
    return ContractResult(name=name, status=status, messages=messages, suggestions=list(suggestions or []))


def _check_required_files(task_dir: Path, cfg: dict[str, Any]) -> ContractResult:
    name = str(cfg.get("name") or "required_files")
    fails: list[str] = []
    warns: list[str] = []
    suggestions: list[str] = []

    for rel in list(cfg.get("required_paths") or []):
        p = task_dir / str(rel)
        if not p.exists():
            fails.append(f"Missing required path: {rel}")
    for rel in list(cfg.get("recommended_paths") or []):
        p = task_dir / str(rel)
        if not p.exists():
            warns.append(f"Missing recommended path: {rel}")

    if fails:
        suggestions.append("Create missing required files/folders to match the standard task skeleton.")
    if warns:
        suggestions.append("Add recommended paths for easier operations and artifact management.")
    return _result(name, fails, warns, suggestions)


def _check_gitignore(task_dir: Path, cfg: dict[str, Any]) -> ContractResult:
    name = str(cfg.get("name") or "gitignore")
    rel = str(cfg.get("file") or ".gitignore")
    path = task_dir / rel
    fails: list[str] = []
    warns: list[str] = []
    suggestions: list[str] = []

    if not path.exists():
        return _result(name, [f"Missing file: {rel}"], [], ["Add .gitignore with task artifact ignore rules."])

    text = _read_text_with_fallback(path)
    entries = [
        ln.strip()
        for ln in text.splitlines()
        if ln.strip() and not ln.strip().startswith("#")
    ]

    def _iter_groups(raw: Any) -> list[tuple[str, list[str]]]:
        out: list[tuple[str, list[str]]] = []
        if not isinstance(raw, list):
            return out
        for i, item in enumerate(raw):
            if isinstance(item, dict):
                gname = str(item.get("name") or f"group_{i+1}")
                opts = [str(x) for x in list(item.get("options") or []) if str(x).strip()]
            elif isinstance(item, list):
                gname = f"group_{i+1}"
                opts = [str(x) for x in item if str(x).strip()]
            else:
                continue
            out.append((gname, opts))
        return out

    required_groups = _iter_groups(cfg.get("required_any_of"))
    recommended_groups = _iter_groups(cfg.get("recommended_any_of"))
    preferred_groups = _iter_groups(cfg.get("preferred_any_of"))

    for gname, opts in required_groups:
        if not _gitignore_has_any(entries, opts):
            fails.append(f".gitignore missing required ignore rule group '{gname}' (any of: {opts})")

    for gname, opts in recommended_groups:
        if not _gitignore_has_any(entries, opts):
            warns.append(f".gitignore missing recommended ignore rule group '{gname}' (any of: {opts})")

    for gname, opts in preferred_groups:
        if not _gitignore_has_any(entries, opts):
            warns.append(f".gitignore missing preferred rule group '{gname}' (any of: {opts})")

    if fails:
        suggestions.append("Add required .gitignore rules to prevent task output artifacts from being committed.")
    if warns:
        suggestions.append("Add recommended .gitignore housekeeping rules for cleaner task repos.")
    return _result(name, fails, warns, suggestions)


def _check_taskbeacon(task_dir: Path, cfg: dict[str, Any]) -> ContractResult:
    name = str(cfg.get("name") or "taskbeacon")
    tb_path = task_dir / "taskbeacon.yaml"
    fails: list[str] = []
    warns: list[str] = []
    suggestions: list[str] = []

    if not tb_path.exists():
        return _result(name, [f"Missing file: {tb_path.name}"], [], ["Create taskbeacon.yaml with required metadata fields."])

    try:
        tb = _load_yaml(tb_path) or {}
    except Exception as exc:
        return _result(name, [f"Could not parse taskbeacon.yaml: {exc}"], [], ["Fix taskbeacon.yaml syntax and retry validation."])

    for key in list(cfg.get("required_keys") or []):
        if not isinstance(tb, dict) or key not in tb:
            fails.append(f"Missing required key: {key}")

    for dotted in list(cfg.get("required_nested_keys") or []):
        if _nested_get(tb, str(dotted)) is None:
            fails.append(f"Missing required nested key: {dotted}")

    for dotted in list(cfg.get("forbidden_nested_keys") or []):
        if _nested_get(tb, str(dotted)) is not None:
            fails.append(f"Forbidden nested key is present: {dotted}")

    maturity = _nested_get(tb, "maturity")
    allowed_maturity = list(cfg.get("allowed_maturity") or [])
    if allowed_maturity and maturity not in allowed_maturity:
        fails.append(f"Invalid maturity '{maturity}'. Allowed: {allowed_maturity}")

    required_version = str(cfg.get("required_contract_version") or "").strip()
    adopted_version = _nested_get(tb, "contracts.taps")
    if required_version and adopted_version != required_version:
        fails.append(f"contracts.taps must be '{required_version}', got '{adopted_version}'.")

    if fails:
        suggestions.append("Update taskbeacon metadata to include all required keys and the adopted contract version.")
    return _result(name, fails, warns, suggestions)


def _check_config_file(task_dir: Path, cfg: dict[str, Any]) -> ContractResult:
    name = str(cfg.get("name") or "config")
    rel = str(cfg.get("file") or "")
    cpath = task_dir / rel
    fails: list[str] = []
    warns: list[str] = []
    suggestions: list[str] = []

    if not cpath.exists():
        return _result(name, [f"Missing file: {rel}"], [], [f"Create {rel} according to the contract."])

    try:
        data = _load_yaml(cpath) or {}
    except Exception as exc:
        return _result(name, [f"Could not parse {rel}: {exc}"], [], ["Fix YAML syntax and retry validation."])

    for sec in list(cfg.get("required_sections") or []):
        if _nested_get(data, str(sec)) is None:
            fails.append(f"Missing required section/key: {sec}")

    for dotted in list(cfg.get("mandatory_nested_keys") or cfg.get("required_nested_keys") or []):
        if _nested_get(data, str(dotted)) is None:
            fails.append(f"Missing required nested key: {dotted}")

    for dotted in list(cfg.get("optional_nested_keys") or []):
        val = _nested_get(data, str(dotted))
        type_specs = cfg.get("optional_type_specs") if isinstance(cfg, dict) else None
        if val is not None and isinstance(type_specs, dict):
            spec = type_specs.get(str(dotted))
            if isinstance(spec, dict):
                issues = _validate_value_spec(str(dotted), val, spec)
                fails.extend(issues)

    for dotted in list(cfg.get("recommended_nested_keys") or []):
        if _nested_get(data, str(dotted)) is None:
            warns.append(f"Missing recommended nested key: {dotted}")

    for dotted in list(cfg.get("forbidden_nested_keys") or []):
        if _nested_has(data, str(dotted)):
            fails.append(f"Forbidden nested key is present: {dotted}")

    req_fails, req_warns = _check_value_specs(
        data,
        cfg.get("mandatory_value_specs")
        if isinstance(cfg, dict)
        else None,
        required=True,
    )
    if not req_fails and not req_warns:
        req_fails, req_warns = _check_value_specs(
            data,
            cfg.get("required_value_specs") if isinstance(cfg, dict) else None,
            required=True,
        )
    opt_fails, opt_warns = _check_optional_value_specs(
        data,
        cfg.get("optional_value_specs") if isinstance(cfg, dict) else None,
    )
    rec_fails, rec_warns = _check_value_specs(
        data,
        cfg.get("recommended_value_specs") if isinstance(cfg, dict) else None,
        required=False,
    )
    fails.extend(req_fails)
    warns.extend(req_warns)
    fails.extend(opt_fails)
    warns.extend(opt_warns)
    fails.extend(rec_fails)
    warns.extend(rec_warns)

    cw_fails, cw_warns = _check_condition_weight_config(data)
    fails.extend(cw_fails)
    warns.extend(cw_warns)

    profile_rules = cfg.get("profile_rules") if isinstance(cfg, dict) else None
    if isinstance(profile_rules, dict):
        base_file = str(profile_rules.get("base_file") or "").strip()
        base_data = None
        if base_file:
            base_path = task_dir / base_file
            if not base_path.exists():
                fails.append(f"profile_rules base_file not found: {base_file}")
            else:
                try:
                    base_data = _load_yaml(base_path) or {}
                except Exception as exc:
                    fails.append(f"profile_rules could not parse base_file {base_file}: {exc}")

        trials_path = str(profile_rules.get("total_trials_path") or "task.total_trials")
        blocks_path = str(profile_rules.get("total_blocks_path") or "task.total_blocks")
        tpb_path = str(profile_rules.get("trial_per_block_path") or "task.trial_per_block")
        conds_path = str(profile_rules.get("condition_list_path") or "task.conditions")

        def _as_int(v: Any) -> int | None:
            try:
                if isinstance(v, bool):
                    return None
                return int(v)
            except Exception:
                return None

        cur_trials = _as_int(_nested_get(data, trials_path))
        cur_blocks = _as_int(_nested_get(data, blocks_path))
        cur_tpb = _as_int(_nested_get(data, tpb_path))
        cur_conds = _nested_get(data, conds_path)
        cond_count = len(cur_conds) if isinstance(cur_conds, list) else None

        if bool(profile_rules.get("require_shorter_than_base", False)) and base_data is not None:
            base_trials = _as_int(_nested_get(base_data, trials_path))
            if cur_trials is None:
                fails.append(f"profile_rules missing numeric value: {trials_path}")
            elif base_trials is None:
                fails.append(f"profile_rules missing numeric value in base: {trials_path}")
            elif cur_trials >= base_trials:
                fails.append(
                    f"smoke profile must be shorter than base: {trials_path}={cur_trials} "
                    f"(base={base_trials})"
                )

        if bool(profile_rules.get("require_trials_cover_conditions", False)):
            if cur_trials is None:
                fails.append(f"profile_rules missing numeric value: {trials_path}")
            elif cond_count is None:
                fails.append(f"profile_rules missing condition list: {conds_path}")
            elif cur_trials < cond_count:
                fails.append(
                    f"smoke profile too short: {trials_path}={cur_trials} is less than "
                    f"number of conditions ({cond_count})"
                )

        if bool(profile_rules.get("require_trial_per_block_consistency", False)):
            if cur_trials is not None and cur_blocks is not None and cur_tpb is not None:
                expected = cur_blocks * cur_tpb
                if expected != cur_trials:
                    warns.append(
                        f"{trials_path} ({cur_trials}) != {blocks_path}*{tpb_path} "
                        f"({cur_blocks}*{cur_tpb}={expected})"
                    )

        max_trials = _as_int(profile_rules.get("recommended_max_total_trials"))
        if max_trials is not None and cur_trials is not None and cur_trials > max_trials:
            warns.append(
                f"smoke profile is longer than recommended: {trials_path}={cur_trials} "
                f"(recommended <= {max_trials})"
            )

        max_blocks = _as_int(profile_rules.get("recommended_max_total_blocks"))
        if max_blocks is not None and cur_blocks is not None and cur_blocks > max_blocks:
            warns.append(
                f"smoke profile uses many blocks: {blocks_path}={cur_blocks} "
                f"(recommended <= {max_blocks})"
            )

    if name == "config_base":
        has_controller = _nested_has(data, "controller")
        if has_controller:
            utils_path = task_dir / "src" / "utils.py"
            if not utils_path.exists():
                fails.append("controller is configured but src/utils.py is missing.")
            else:
                utils_text = _read_text_with_fallback(utils_path).lower()
                if "controller" not in utils_text:
                    warns.append("controller is configured but src/utils.py has no obvious controller implementation token.")

        stim_fails, stim_warns = _check_stimulus_contract(task_dir, data, cfg)
        fails.extend(stim_fails)
        warns.extend(stim_warns)

    if fails:
        suggestions.append(f"Update {rel} to satisfy required keys and value constraints.")
    if warns:
        suggestions.append(f"Improve {rel} to include recommended QA/sim metadata for better auditability.")
    return _result(name, fails, warns, suggestions)


def _check_runtime_main(task_dir: Path, cfg: dict[str, Any]) -> ContractResult:
    name = str(cfg.get("name") or "runtime_main")
    path = task_dir / str(cfg.get("file") or "main.py")
    fails: list[str] = []
    warns: list[str] = []
    suggestions: list[str] = []

    if not path.exists():
        return _result(name, [f"Missing file: {path.name}"], [], ["Create a task entrypoint main.py."])

    text = _read_text_with_fallback(path)
    low = text.lower()
    for token in list(cfg.get("required_mode_tokens") or []):
        if str(token).lower() not in low:
            fails.append(f"Missing required mode token in main.py: {token}")

    for fn in list(cfg.get("required_functions") or []):
        pat = re.compile(rf"def\s+{re.escape(str(fn))}\s*\(")
        if pat.search(text) is None:
            fails.append(f"Missing required function definition: {fn}()")

    for s in list(cfg.get("required_strings_all") or []):
        if str(s) not in text:
            fails.append(f"Missing required main.py token: {s}")

    any_required = list(cfg.get("required_strings_any") or [])
    if any_required and not any(str(s) in text for s in any_required):
        fails.append(f"main.py should include one of: {any_required}")

    if bool(cfg.get("required_main_guard", False)):
        if '__name__' not in text or "main()" not in text:
            fails.append("main.py should include the __name__ == '__main__' guard and call main().")

    any_recommended = list(cfg.get("recommended_strings_any") or [])
    if any_recommended and not any(str(s) in text for s in any_recommended):
        warns.append(f"main.py is missing recommended runtime helpers: {any_recommended}")

    mid_fails, mid_warns = _check_mid_template_leakage(task_dir)
    fails.extend(mid_fails)
    warns.extend(mid_warns)

    if fails:
        suggestions.append("Use standardized task options + runtime context wiring in main.py.")
    if mid_fails:
        suggestions.append(
            "Replace MID-specific defaults in config/readme/run_trial with paradigm-neutral template placeholders."
        )
    return _result(name, fails, warns, suggestions)


def _check_responder_context(task_dir: Path, cfg: dict[str, Any]) -> ContractResult:
    name = str(cfg.get("name") or "responder_context")
    path = task_dir / str(cfg.get("file") or "src/run_trial.py")
    fails: list[str] = []
    warns: list[str] = []
    suggestions: list[str] = []

    if not path.exists():
        return _result(name, [f"Missing file: {path}"], [], ["Create src/run_trial.py with standardized trial context wiring."])

    text = _read_text_with_fallback(path)
    low = text.lower()
    set_ctx_count = len(re.findall(r"\bset_trial_context\s*\(", text))
    capture_count = len(re.findall(r"\bcapture_response\s*\(", text))
    phase_values = {
        str(m.group(1) or "").strip().lower()
        for m in re.finditer(r"\bphase\s*=\s*['\"]([^'\"]+)['\"]", text)
        if str(m.group(1) or "").strip()
    }

    req_fn = cfg.get("required_function")
    if req_fn:
        pat = re.compile(rf"def\s+{re.escape(str(req_fn))}\s*\((.*?)\)\s*:", re.DOTALL)
        m = pat.search(text)
        if m is None:
            fails.append(f"Missing required function definition: {req_fn}()")
        else:
            sig = m.group(1)
            for arg in list(cfg.get("required_signature_args") or []):
                if re.search(rf"\b{re.escape(str(arg))}\b", sig) is None:
                    fails.append(f"run_trial signature missing required argument: {arg}")

    req_all = list(cfg.get("required_strings_all") or [])
    for s in req_all:
        if str(s) not in text:
            fails.append(f"Missing required run_trial token: {s}")

    fails.extend(_check_run_trial_text_localization(text, cfg))
    visible_without_context = _find_visible_show_without_context(text)
    for token in visible_without_context:
        warns.append(
            "Participant-visible phase appears to call show() without preceding set_trial_context(...): "
            f"{token}"
        )

    req_any = list(cfg.get("required_strings_any") or [])
    if req_any and not any(str(s) in text for s in req_any):
        fails.append(f"Missing required responder context helper usage (any): {req_any}")

    for token in list(cfg.get("required_context_fields_any") or []):
        if str(token) not in text:
            fails.append(f"Missing required trial context field argument: {token}")

    min_set_ctx = cfg.get("required_set_trial_context_min")
    if min_set_ctx is not None:
        try:
            need = int(min_set_ctx)
            if set_ctx_count < need:
                fails.append(
                    f"set_trial_context(...) call count too low: {set_ctx_count} < required {need}"
                )
        except Exception:
            pass

    min_capture = cfg.get("required_capture_response_min")
    if min_capture is not None:
        try:
            need = int(min_capture)
            if capture_count < need:
                fails.append(
                    f"capture_response(...) call count too low: {capture_count} < required {need}"
                )
        except Exception:
            pass

    for phase in list(cfg.get("required_context_phase_values") or []):
        p = str(phase)
        if p.strip().lower() not in phase_values:
            fails.append(f"Missing set_trial_context phase value: {p}")

    required_phase_any = {
        str(x or "").strip().lower()
        for x in list(cfg.get("required_context_phase_values_any") or [])
        if str(x or "").strip()
    }
    if required_phase_any and phase_values.isdisjoint(required_phase_any):
        fails.append(
            "Missing required context phase (any): "
            f"expected one of {sorted(required_phase_any)}, got {sorted(phase_values) or 'none'}"
        )

    required_phase_tokens_any = [
        str(x or "").strip().lower()
        for x in list(cfg.get("required_context_phase_tokens_any") or [])
        if str(x or "").strip()
    ]
    if required_phase_tokens_any:
        has_required_token = any(
            any(tok in phase for tok in required_phase_tokens_any)
            for phase in phase_values
        )
        if not has_required_token:
            fails.append(
                "Missing required context phase token (any): "
                f"expected one of {sorted(required_phase_tokens_any)}, got {sorted(phase_values) or 'none'}"
            )

    forbidden_phase = {
        str(x or "").strip().lower()
        for x in list(cfg.get("forbidden_context_phase_values") or [])
        if str(x or "").strip()
    }
    hit_forbidden = sorted(phase_values.intersection(forbidden_phase))
    if hit_forbidden:
        fails.append(f"Found forbidden context phase value(s): {hit_forbidden}")

    stages = [str(x).lower() for x in list(cfg.get("required_stage_tokens_in_order") or [])]
    if stages:
        positions: list[int] = []
        missing: list[str] = []
        for s in stages:
            idx = low.find(s)
            if idx < 0:
                missing.append(s)
            else:
                positions.append(idx)
        if missing:
            fails.append(f"Missing required trial stage token(s): {missing}")
        elif positions != sorted(positions):
            fails.append(f"Trial stage tokens should appear in order: {stages}")

    for token in list(cfg.get("recommended_context_fields_any") or []):
        if str(token) not in text:
            warns.append(f"Missing recommended trial context field argument: {token}")

    recommended_phase_any = {
        str(x or "").strip().lower()
        for x in list(cfg.get("recommended_context_phase_values_any") or [])
        if str(x or "").strip()
    }
    if recommended_phase_any and phase_values.isdisjoint(recommended_phase_any):
        warns.append(
            "No recommended phase labels found (any): "
            f"{sorted(recommended_phase_any)}; got {sorted(phase_values) or 'none'}"
        )

    recommended_phase_tokens_any = [
        str(x or "").strip().lower()
        for x in list(cfg.get("recommended_context_phase_tokens_any") or [])
        if str(x or "").strip()
    ]
    if recommended_phase_tokens_any:
        has_recommended_token = any(
            any(tok in phase for tok in recommended_phase_tokens_any)
            for phase in phase_values
        )
        if not has_recommended_token:
            warns.append(
                "No recommended phase tokens found (any): "
                f"{sorted(recommended_phase_tokens_any)}; got {sorted(phase_values) or 'none'}"
            )

    required_stage_any = [str(x).strip().lower() for x in list(cfg.get("required_stage_tokens_any") or []) if str(x).strip()]
    if required_stage_any and not any(tok in low for tok in required_stage_any):
        fails.append(f"Missing required trial stage token (any): {required_stage_any}")

    recommended_stage_any = [str(x).strip().lower() for x in list(cfg.get("recommended_stage_tokens_any") or []) if str(x).strip()]
    if recommended_stage_any and not any(tok in low for tok in recommended_stage_any):
        warns.append(f"Missing recommended trial stage token (any): {recommended_stage_any}")

    if fails:
        suggestions.append("Call set_trial_context(...) with required fields before response windows.")
    if visible_without_context:
        suggestions.append("Emit set_trial_context(...) for every participant-visible phase, not only response windows.")
    if warns:
        suggestions.append("Include condition/block/task_factors context for richer simulation and audits.")
    return _result(name, fails, warns, suggestions)


def _check_readme_meta(task_dir: Path, cfg: dict[str, Any]) -> ContractResult:
    name = str(cfg.get("name") or "readme_meta")
    path = task_dir / str(cfg.get("file") or "README.md")
    fails: list[str] = []
    warns: list[str] = []
    suggestions: list[str] = []

    if not path.exists():
        return _result(name, [f"Missing file: {path.name}"], [], ["Add README.md with metadata table."])

    text = _read_text_with_fallback(path)
    for field_name in list(cfg.get("required_table_fields") or []):
        pat = re.compile(rf"^\|\s*{re.escape(str(field_name))}\s*\|", re.MULTILINE)
        if pat.search(text) is None:
            fails.append(f"Missing required README metadata row: {field_name}")

    for field_name in list(cfg.get("recommended_table_fields") or []):
        pat = re.compile(rf"^\|\s*{re.escape(str(field_name))}\s*\|", re.MULTILINE)
        if pat.search(text) is None:
            warns.append(f"Missing recommended README metadata row: {field_name}")

    for section in list(cfg.get("required_sections") or []):
        section_text = str(section)
        if section_text not in text:
            fails.append(f"Missing required README section heading: {section_text}")

    for section in list(cfg.get("recommended_subsections") or []):
        section_text = str(section)
        if section_text not in text:
            warns.append(f"Missing recommended README subsection heading: {section_text}")

    if fails:
        suggestions.append("Add required metadata rows to the README table for consistent audits.")
        suggestions.append("Add missing required README headings to match the standard reproducibility layout.")
    return _result(name, fails, warns, suggestions)


def _check_changelog(task_dir: Path, cfg: dict[str, Any]) -> ContractResult:
    name = str(cfg.get("name") or "changelog")
    path = task_dir / str(cfg.get("file") or "CHANGELOG.md")
    fails: list[str] = []
    warns: list[str] = []
    suggestions: list[str] = []

    if not path.exists():
        return _result(name, [f"Missing file: {path.name}"], [], ["Add CHANGELOG.md to track task evolution."])

    text = _read_text_with_fallback(path)
    for raw_pat in list(cfg.get("required_patterns") or []):
        pat = re.compile(str(raw_pat), re.MULTILINE)
        if pat.search(text) is None:
            fails.append(f"Missing required changelog pattern: {raw_pat}")

    for sec in list(cfg.get("recommended_sections") or []):
        if f"### {sec}" not in text and f"## {sec}" not in text:
            warns.append(f"Missing recommended changelog section: {sec}")

    if fails:
        suggestions.append("Follow the changelog format `## [version] - YYYY-MM-DD` with clear section headings.")
    return _result(name, fails, warns, suggestions)


def _check_reference_artifacts(task_dir: Path, cfg: dict[str, Any]) -> ContractResult:
    name = str(cfg.get("name") or "reference_artifacts")
    fails: list[str] = []
    warns: list[str] = []
    suggestions: list[str] = []

    for rel in list(cfg.get("required_files") or []):
        path = task_dir / str(rel)
        if not path.exists():
            fails.append(f"Missing required reference artifact: {rel}")

    refs_yaml_cfg = cfg.get("references_yaml") if isinstance(cfg.get("references_yaml"), dict) else {}
    refs_yaml_rel = str(refs_yaml_cfg.get("file") or "references/references.yaml")
    refs_yaml_path = task_dir / refs_yaml_rel
    refs_yaml: dict[str, Any] | None = None
    if refs_yaml_path.exists():
        try:
            loaded = _load_yaml(refs_yaml_path) or {}
            refs_yaml = loaded if isinstance(loaded, dict) else {}
        except Exception as exc:
            fails.append(f"Could not parse {refs_yaml_rel}: {exc}")

    if isinstance(refs_yaml, dict):
        for key in list(refs_yaml_cfg.get("required_top_level_keys") or []):
            if key not in refs_yaml:
                fails.append(f"{refs_yaml_rel} missing required key: {key}")

        papers = refs_yaml.get("papers")
        if not isinstance(papers, list):
            fails.append(f"{refs_yaml_rel} key 'papers' must be a list")
        else:
            min_items = refs_yaml_cfg.get("papers_min_items")
            try:
                if min_items is not None and len(papers) < int(min_items):
                    fails.append(f"{refs_yaml_rel} papers must contain at least {int(min_items)} item(s)")
            except Exception:
                pass

            required_paper_keys = [str(x) for x in list(refs_yaml_cfg.get("required_paper_keys") or []) if str(x).strip()]
            for idx, paper in enumerate(papers):
                if not isinstance(paper, dict):
                    fails.append(f"{refs_yaml_rel} papers[{idx}] must be a mapping")
                    continue
                for key in required_paper_keys:
                    if key not in paper:
                        fails.append(f"{refs_yaml_rel} papers[{idx}] missing required key: {key}")

    for spec in list(cfg.get("markdown_specs") or []):
        if not isinstance(spec, dict):
            continue
        rel = str(spec.get("file") or "").strip()
        if not rel:
            continue
        path = task_dir / rel
        if not path.exists():
            continue

        text = _read_text_with_fallback(path)
        for heading in [str(x) for x in list(spec.get("required_headings") or []) if str(x).strip()]:
            if heading not in text:
                fails.append(f"{rel} missing required heading: {heading}")

        required_cols = [str(x) for x in list(spec.get("required_table_columns") or []) if str(x).strip()]
        if required_cols and not _md_has_columns(text, required_cols):
            fails.append(f"{rel} missing required table columns: {required_cols}")

        for marker in [str(x) for x in list(spec.get("forbidden_markers") or []) if str(x).strip()]:
            if re.search(rf"\b{re.escape(marker)}\b", text):
                fails.append(f"{rel} contains forbidden marker: {marker}")

    if fails:
        suggestions.append(
            "Align references artifacts to the contract schema (required headings, table columns, and references.yaml keys)."
        )
    return _result(name, fails, warns, suggestions)


def _check_artifacts(task_dir: Path, cfg: dict[str, Any]) -> ContractResult:
    name = str(cfg.get("name") or "artifacts")
    fails: list[str] = []
    warns: list[str] = []
    suggestions: list[str] = []

    qa_dir = task_dir / "outputs" / "qa"
    sim_dir = task_dir / "outputs" / "sim"

    if qa_dir.exists():
        for fname in list(cfg.get("qa_required_filenames") or []):
            if not (qa_dir / str(fname)).exists():
                fails.append(f"Missing expected QA artifact in outputs/qa: {fname}")
    else:
        warns.append("outputs/qa not found; QA artifact checks skipped.")

    if sim_dir.exists():
        for pat in list(cfg.get("sim_recommended_patterns") or []):
            matches = list(sim_dir.glob(str(pat)))
            if not matches:
                warns.append(f"No sim artifact matching pattern in outputs/sim: {pat}")
    else:
        warns.append("outputs/sim not found; sim artifact checks skipped.")

    if fails:
        suggestions.append("Run QA and ensure required QA artifacts are written to outputs/qa.")
    if warns:
        suggestions.append("Run representative QA/sim sessions so artifact conventions are exercised.")
    return _result(name, fails, warns, suggestions)


def _check_responder_plugin(task_dir: Path, cfg: dict[str, Any]) -> ContractResult:
    name = str(cfg.get("name") or "responder_plugin")
    rel = str(cfg.get("file") or "config/config_sampler_sim.yaml")
    cpath = task_dir / rel
    fails: list[str] = []
    warns: list[str] = []
    suggestions: list[str] = []

    if not cpath.exists():
        return _result(name, [f"Missing file: {rel}"], [], [f"Create {rel} to define sim responder plugin settings."])

    try:
        data = _load_yaml(cpath) or {}
    except Exception as exc:
        return _result(name, [f"Could not parse {rel}: {exc}"], [], ["Fix YAML syntax and retry validation."])

    rf, rw = _check_responder_spec(task_dir, data, cfg)
    fails.extend(rf)
    warns.extend(rw)

    if fails:
        suggestions.append(
            "Use sim.responder.type as builtin (scripted/null) or local import path "
            "under responders/ with a class implementing act(...)."
        )
    if warns:
        suggestions.append(
            "Prefer task-local responder classes in responders/ and include optional lifecycle methods "
            "for sampler/session consistency."
        )
    return _result(name, fails, warns, suggestions)


def _contract_files_for(name: str) -> str:
    mapping = {
        "required_files": "required_files.yaml",
        "gitignore": "gitignore.yaml",
        "taskbeacon": "taskbeacon.yaml",
        "config_base": "config.yaml",
        "config_qa": "config_qa.yaml",
        "config_scripted_sim": "config_scripted_sim.yaml",
        "config_sampler_sim": "config_sampler_sim.yaml",
        "responder_plugin": "responder_plugin.yaml",
        "runtime_main": "runtime_main.yaml",
        "responder_context": "responder_context.yaml",
        "readme_meta": "readme_meta.yaml",
        "changelog": "changelog.yaml",
        "reference_artifacts": "reference_artifacts.yaml",
        "artifacts": "artifacts.yaml",
    }
    if name not in mapping:
        raise KeyError(f"Unknown contract id: {name}")
    return mapping[name]


def _run_checks(task_dir: Path, contracts_root: Path) -> list[ContractResult]:
    manifest = _load_yaml(contracts_root / "manifest.yaml") or {}
    contract_ids = list(manifest.get("contracts") or [])
    results: list[ContractResult] = []

    for cid in contract_ids:
        contract_cfg = _load_yaml(contracts_root / _contract_files_for(str(cid))) or {}
        if cid == "required_files":
            results.append(_check_required_files(task_dir, contract_cfg))
        elif cid == "gitignore":
            results.append(_check_gitignore(task_dir, contract_cfg))
        elif cid == "taskbeacon":
            results.append(_check_taskbeacon(task_dir, contract_cfg))
        elif cid == "config_base":
            results.append(_check_config_file(task_dir, contract_cfg))
        elif cid == "config_qa":
            results.append(_check_config_file(task_dir, contract_cfg))
        elif cid == "config_scripted_sim":
            results.append(_check_config_file(task_dir, contract_cfg))
        elif cid == "config_sampler_sim":
            results.append(_check_config_file(task_dir, contract_cfg))
        elif cid == "responder_plugin":
            results.append(_check_responder_plugin(task_dir, contract_cfg))
        elif cid == "runtime_main":
            results.append(_check_runtime_main(task_dir, contract_cfg))
        elif cid == "responder_context":
            results.append(_check_responder_context(task_dir, contract_cfg))
        elif cid == "readme_meta":
            results.append(_check_readme_meta(task_dir, contract_cfg))
        elif cid == "changelog":
            results.append(_check_changelog(task_dir, contract_cfg))
        elif cid == "reference_artifacts":
            results.append(_check_reference_artifacts(task_dir, contract_cfg))
        elif cid == "artifacts":
            results.append(_check_artifacts(task_dir, contract_cfg))
        else:  # pragma: no cover
            results.append(
                ContractResult(
                    name=str(cid),
                    status="WARN",
                    messages=[f"WARN: No checker implemented for contract id '{cid}'."],
                    suggestions=["Implement checker or remove unknown contract id from manifest."],
                )
            )
    return results


def _detect_contract_version(task_dir: Path) -> str | None:
    tb_path = task_dir / "taskbeacon.yaml"
    if not tb_path.exists() or yaml is None:
        return None
    try:
        data = _load_yaml(tb_path) or {}
    except Exception:
        return None
    value = _nested_get(data, "contracts.taps")
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def run_validator(
    task_dir: Path,
    *,
    contracts_version: str,
    strict_warn: bool = False,
    contracts_root: str | Path | None = None,
) -> dict[str, Any]:
    contracts_root = resolve_contracts_root(contracts_version, contracts_root=contracts_root)

    results = _run_checks(task_dir, contracts_root)
    fail_count = sum(1 for r in results if r.status == "FAIL")
    warn_count = sum(1 for r in results if r.status == "WARN")
    pass_count = sum(1 for r in results if r.status == "PASS")
    exit_code = 0
    if fail_count > 0:
        exit_code = 1
    elif strict_warn and warn_count > 0:
        exit_code = 2

    return {
        "task_dir": str(task_dir),
        "contracts_version": contracts_version,
        "summary": {
            "pass": pass_count,
            "warn": warn_count,
            "fail": fail_count,
        },
        "results": [r.to_dict() for r in results],
        "exit_code": exit_code,
    }


def _print_report(report: dict[str, Any]) -> None:
    print(
        f"[taps-validate] task={report['task_dir']} contracts={report['contracts_version']}"
    )
    for row in list(report.get("results") or []):
        status = row.get("status", "UNKNOWN")
        name = row.get("name", "unnamed")
        marker = {"PASS": "+", "WARN": "!", "FAIL": "x"}.get(status, "?")
        print(f"{marker} [{status}] {name}")
        for msg in list(row.get("messages") or []):
            print(f"  - {msg}")
        for sug in list(row.get("suggestions") or []):
            print(f"  suggestion: {sug}")

    summary = report.get("summary", {})
    print(
        "[taps-validate] summary: "
        f"PASS={summary.get('pass', 0)} WARN={summary.get('warn', 0)} FAIL={summary.get('fail', 0)}"
    )


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="taps-validate",
        description="Validate a TAPS task package against strict versioned TAPS contracts.",
    )
    parser.add_argument("task", help="Path to task directory, e.g. T000006-mid")
    parser.add_argument(
        "--contracts-version",
        default=None,
        help="Contracts version (default: from taskbeacon.yaml or v0.1.0).",
    )
    parser.add_argument(
        "--contracts-root",
        default=None,
        help="Path to a contracts root or a specific version folder.",
    )
    parser.add_argument(
        "--strict-warn",
        action="store_true",
        help="Return non-zero when WARN-level findings exist.",
    )
    parser.add_argument(
        "--json-report",
        default=None,
        help="Optional path to write a JSON validation report.",
    )
    ns = parser.parse_args(argv)

    task_dir = Path(ns.task).expanduser().resolve()
    if not task_dir.exists() or not task_dir.is_dir():
        raise SystemExit(f"Task path not found or not a directory: {task_dir}")

    if yaml is None:  # pragma: no cover
        raise SystemExit("PyYAML is required for validation. Install with `pip install pyyaml`.")

    version = str(ns.contracts_version or _detect_contract_version(task_dir) or "v0.1.0")
    report = run_validator(
        task_dir,
        contracts_version=version,
        strict_warn=bool(ns.strict_warn),
        contracts_root=ns.contracts_root,
    )
    _print_report(report)

    if ns.json_report:
        out = Path(ns.json_report).expanduser().resolve()
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, ensure_ascii=True, indent=2), encoding="utf-8")
        print(f"[taps-validate] report_json={out}")

    raise SystemExit(int(report.get("exit_code", 0)))


if __name__ == "__main__":
    main()
