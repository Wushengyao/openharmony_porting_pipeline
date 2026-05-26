#!/usr/bin/env python3
"""Apply a controlled OpenHarmony target base-binding patch.

This tool is intentionally narrower than the execution assistant planner.  It
can stage, optionally apply, and optionally build-test the first patch needed
to make a target product visible: productdefine, vendor product config, board
binding config, and SoC binding config.  It does not import firmware, prebuilts,
bootloader images, kernel modules, or closed-driver payloads.
"""

from __future__ import annotations

import argparse
import copy
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time
from typing import Any

import yaml


TEXT_ENCODING = "utf-8"
DEFAULT_BUILD_TIMEOUT_SEC = 3600
TEXT_CLOSURE_SUFFIXES = {
    ".c",
    ".cc",
    ".cfg",
    ".conf",
    ".cpp",
    ".crt",
    ".cxx",
    ".gn",
    ".gni",
    ".h",
    ".hcs",
    ".hpp",
    ".idl",
    ".ini",
    ".json",
    ".map",
    ".md",
    ".para",
    ".patch",
    ".rc",
    ".sh",
    ".txt",
    ".xml",
}
TEXT_CLOSURE_FILENAMES = {
    "BUILD.gn",
    "Kconfig",
    "Makefile",
}


def now() -> str:
    return datetime.now().astimezone().strftime("%Y-%m-%dT%H:%M:%S%z")


def read_yaml(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding=TEXT_ENCODING, errors="ignore")) or {}
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a YAML mapping")
    return data


def read_json(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding=TEXT_ENCODING, errors="ignore"))
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return data


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fp:
        for chunk in iter(lambda: fp.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def mkdir_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def write_bytes(path: Path, data: bytes) -> None:
    mkdir_parent(path)
    path.write_bytes(data)


def apply_mode(path: Path, mode: int | None) -> None:
    if mode is None:
        return
    path.chmod(mode)


def executable_source_mode(source_label: str, force_executable: bool = False) -> int | None:
    if force_executable:
        return 0o775
    try:
        source_path = Path(source_label)
    except Exception:
        return None
    if not source_path.is_file():
        return None
    mode = source_path.stat().st_mode & 0o777
    if mode & 0o111:
        return mode
    return None


def clean_str(value: Any, default: str = "unknown") -> str:
    if isinstance(value, str) and value.strip():
        return value.strip()
    if value is not None and not isinstance(value, (dict, list, tuple, set)):
        text = str(value).strip()
        if text:
            return text
    return default


def normalize_rel(path: str) -> str:
    rel = path.strip().replace("\\", "/")
    rel = rel.lstrip("/")
    parts = []
    for part in rel.split("/"):
        if part in ("", "."):
            continue
        if part == "..":
            raise ValueError(f"path escapes workspace: {path}")
        parts.append(part)
    return "/".join(parts)


def copy_action(rel_path: str, role: str, phase: str, reason: str) -> dict[str, Any]:
    return {
        "path": normalize_rel(rel_path),
        "source_path": normalize_rel(rel_path),
        "content_source": "target_source_root",
        "source_role": role,
        "phase": phase,
        "reason": reason,
        "dependency_policy": "text_only",
    }


def workspace_transform_action(rel_path: str, role: str, phase: str, reason: str) -> dict[str, Any]:
    return {
        "path": normalize_rel(rel_path),
        "source_path": normalize_rel(rel_path),
        "content_source": "workspace_transform",
        "source_role": role,
        "phase": phase,
        "reason": reason,
        "dependency_policy": "text_only",
    }


def target_source_transform_action(rel_path: str, role: str, phase: str, reason: str) -> dict[str, Any]:
    return {
        "path": normalize_rel(rel_path),
        "source_path": normalize_rel(rel_path),
        "content_source": "target_source_transform",
        "source_role": role,
        "phase": phase,
        "reason": reason,
        "dependency_policy": "text_only",
    }


def generated_fake_interface_action(
    rel_path: str,
    role: str,
    phase: str,
    reason: str,
    content: str,
    missing_dependency: str,
    provenance_path: str,
    follow_up: str = "replace with provenance-checked vendor/third-party dependency before runtime validation",
) -> dict[str, Any]:
    return {
        "path": normalize_rel(rel_path),
        "source_path": "generated",
        "content_source": "generated_fake_interface",
        "source_role": role,
        "phase": phase,
        "reason": reason,
        "dependency_policy": "compile_only_fake_interface",
        "generated_text": content,
        "fake_interface": {
            "missing_dependency": missing_dependency,
            "provenance_path": provenance_path,
            "scope": "compile_only",
            "runtime_status": "not_functional",
            "follow_up": follow_up,
        },
    }


def workspace_fake_binary_action(
    rel_path: str,
    source_path: str,
    role: str,
    phase: str,
    reason: str,
    missing_dependency: str,
    provenance_path: str,
    follow_up: str,
) -> dict[str, Any]:
    return {
        "path": normalize_rel(rel_path),
        "source_path": normalize_rel(source_path),
        "content_source": "workspace_fake_binary_from_existing",
        "source_role": role,
        "phase": phase,
        "reason": reason,
        "dependency_policy": "compile_only_fake_binary_placeholder",
        "fake_interface": {
            "missing_dependency": missing_dependency,
            "provenance_path": provenance_path,
            "scope": "compile_only_binary_placeholder",
            "runtime_status": "wrong_architecture_not_functional",
            "follow_up": follow_up,
        },
    }


def build_productdefine(product: str, seed: dict[str, Any], vendor_config: dict[str, Any]) -> dict[str, Any]:
    allowed_keys = [
        "product_name",
        "device_company",
        "target_cpu",
        "board",
        "type",
        "version",
        "api_version",
        "enable_ramdisk",
        "enable_absystem",
        "build_selinux",
        "build_seccomp",
        "inherit",
        "subsystems",
    ]
    product_config: dict[str, Any] = {}
    for key in allowed_keys:
        if key in vendor_config:
            product_config[key] = vendor_config[key]
    product_config["product_name"] = product
    product_config.setdefault("device_company", clean_str(seed.get("vendor"), clean_str(vendor_config.get("device_company"), "unknown")))
    product_config.setdefault("target_cpu", clean_str(seed.get("architecture"), clean_str(vendor_config.get("target_cpu"), "unknown")))
    product_config.setdefault("board", clean_str(seed.get("board"), clean_str(vendor_config.get("board"), product)))
    product_config.setdefault("type", clean_str(vendor_config.get("type"), "standard"))
    product_config.setdefault("version", clean_str(vendor_config.get("version"), "3.0"))
    product_config.setdefault("subsystems", [])
    return product_config


def productdefine_bytes(product_config: dict[str, Any]) -> bytes:
    return (json.dumps(product_config, ensure_ascii=False, indent=2) + "\n").encode(TEXT_ENCODING)


def collect_workspace_component_features(workspace: Path, target: dict[str, str]) -> dict[str, set[str] | None]:
    component_features: dict[str, set[str] | None] = {}
    excluded_roots = {
        ".git",
        "out",
        "prebuilts",
        "node_modules",
        ".repo",
    }
    for dirpath, dirnames, filenames in os.walk(workspace):
        rel_dir = Path(dirpath).resolve().relative_to(workspace).as_posix() if Path(dirpath).resolve() != workspace else ""
        if "/fake_components/" in f"/{rel_dir}/":
            dirnames[:] = []
            continue
        first = rel_dir.split("/", 1)[0] if rel_dir else ""
        if first in excluded_roots:
            dirnames[:] = []
            continue
        dirnames[:] = [name for name in dirnames if name not in excluded_roots]
        if "bundle.json" not in filenames:
            continue
        bundle_path = Path(dirpath) / "bundle.json"
        try:
            data = read_json(bundle_path)
        except Exception:
            continue
        component = data.get("component")
        if isinstance(component, dict):
            name = clean_str(component.get("name"), "")
            if name:
                features = component.get("features")
                feature_set: set[str] = set()
                if isinstance(features, list):
                    feature_set = {clean_str(feature, "") for feature in features if clean_str(feature, "")}
                component_features[name] = feature_set

    product = clean_str(target.get("product"), "unknown")
    board = clean_str(target.get("board"), product)
    if product != "unknown":
        component_features[f"product_{product}"] = None
    if board != "unknown":
        component_features[f"device_{board}"] = None
    return component_features


def feature_name(feature: Any) -> str:
    text = clean_str(feature, "")
    if "=" in text:
        text = text.split("=", 1)[0].strip()
    return text


def component_key(subsystem: str, component: str) -> str:
    return f"{subsystem}:{component}"


def safe_path_segment(value: str) -> str:
    text = re.sub(r"[^A-Za-z0-9_.+-]+", "_", value.strip())
    return text or "unknown"


def collect_config_component_entries(config: dict[str, Any]) -> list[dict[str, str]]:
    entries: list[dict[str, str]] = []
    subsystems = config.get("subsystems")
    if not isinstance(subsystems, list):
        return entries
    for subsystem in subsystems:
        if not isinstance(subsystem, dict):
            continue
        subsystem_name = clean_str(subsystem.get("subsystem"), "")
        components = subsystem.get("components")
        if not subsystem_name or not isinstance(components, list):
            continue
        for component in components:
            if not isinstance(component, dict):
                continue
            component_name = clean_str(component.get("component"), "")
            if component_name:
                entries.append({"subsystem": subsystem_name, "component": component_name})
    return entries


def collect_declared_target_components(product_config: dict[str, Any], target_root: Path) -> list[dict[str, str]]:
    entries = collect_config_component_entries(product_config)
    seen_inherit: set[str] = set()
    for item in product_config.get("inherit") or []:
        if not isinstance(item, str) or not item.strip().endswith(".json"):
            continue
        inherit_rel = normalize_rel(item)
        if inherit_rel in seen_inherit:
            continue
        seen_inherit.add(inherit_rel)
        inherit_path = target_root / inherit_rel
        if not inherit_path.is_file():
            continue
        try:
            inherit_config = read_json(inherit_path)
        except Exception:
            continue
        entries.extend(collect_config_component_entries(inherit_config))

    deduped: list[dict[str, str]] = []
    seen_keys: set[str] = set()
    for entry in entries:
        key = component_key(entry["subsystem"], entry["component"])
        if key not in seen_keys:
            deduped.append(entry)
            seen_keys.add(key)
    return deduped


def read_subsystem_paths(workspace: Path) -> dict[str, str]:
    config_path = workspace / "build/subsystem_config.json"
    if not config_path.is_file():
        return {}
    try:
        data = read_json(config_path)
    except Exception:
        return {}
    paths: dict[str, str] = {}
    for key, value in data.items():
        if not isinstance(value, dict):
            continue
        name = clean_str(value.get("name"), clean_str(key, ""))
        path = clean_str(value.get("path"), "")
        if name and path:
            paths[name] = normalize_rel(path)
    return paths


def generated_fake_component_bundle_action(
    vendor: str,
    product: str,
    subsystem: str,
    component: str,
    subsystem_base_path: str,
) -> dict[str, Any]:
    fake_rel = (
        f"{normalize_rel(subsystem_base_path)}/fake_components/"
        f"{safe_path_segment(vendor)}_{safe_path_segment(product)}/{safe_path_segment(component)}/bundle.json"
    )
    bundle = {
        "name": f"@ohos/{component}_fake_for_{product}",
        "description": (
            "Compile-only fake component registry generated by the OpenHarmony "
            "porting assistant. It preserves product selection while the real "
            "source or third-party dependency is missing."
        ),
        "version": "0.0.0-porting-fake",
        "license": "Apache License 2.0",
        "publishAs": "code-segment",
        "segment": {"destPath": fake_rel.rsplit("/", 1)[0]},
        "dirs": {},
        "scripts": {},
        "component": {
            "name": component,
            "subsystem": subsystem,
            "syscap": [],
            "features": [],
            "adapted_system_type": ["standard"],
            "rom": "0KB",
            "ram": "0KB",
            "deps": {"components": [], "third_party": []},
            "build": {"sub_component": [], "inner_kits": [], "test": []},
        },
    }
    return generated_fake_interface_action(
        fake_rel,
        "fake_component_registry",
        "L2_missing_source_component_stub",
        (
            f"Create a compile-only fake bundle registry for missing component "
            f"{subsystem}:{component} so product configuration remains unchanged."
        ),
        json.dumps(bundle, ensure_ascii=False, indent=2) + "\n",
        f"OpenHarmony component registry/source for {subsystem}:{component}",
        f"target product configuration declares {subsystem}:{component}",
        f"replace fake registry with the real {subsystem}:{component} source component or remove only after a product-scope decision",
    )


def is_text_closure_file(path: Path) -> bool:
    return (
        path.name in TEXT_CLOSURE_FILENAMES
        or path.suffix.lower() in TEXT_CLOSURE_SUFFIXES
        or path.name.startswith("fstab.")
        or path.name.endswith("defconfig")
        or path.name.endswith(".config")
    )


def collect_ohos_build_module_dirs(ohos_build_path: Path, label_prefix: str) -> list[str]:
    if not ohos_build_path.is_file():
        return []
    try:
        data = read_json(ohos_build_path)
    except Exception:
        return []
    parts = data.get("parts")
    if not isinstance(parts, dict):
        return []
    dirs: list[str] = []
    prefix = f"//{normalize_rel(label_prefix)}"
    for part in parts.values():
        if not isinstance(part, dict):
            continue
        module_list = part.get("module_list")
        if not isinstance(module_list, list):
            continue
        for module in module_list:
            if not isinstance(module, str) or not module.startswith(prefix):
                continue
            module_path = module.split(":", 1)[0]
            if module_path.startswith("//"):
                module_path = module_path[2:]
            try:
                rel_path = normalize_rel(module_path)
            except ValueError:
                continue
            if rel_path and rel_path not in dirs:
                dirs.append(rel_path)
    return dirs


def collect_local_gn_dependency_dirs(build_gn_path: Path, owner_rel: str) -> list[str]:
    return collect_gn_dependency_dirs(build_gn_path, owner_rel, [])


def resolve_relative_gn_label(owner_rel: str, label_path: str) -> str:
    owner_parts = normalize_rel(owner_rel).split("/") if owner_rel else []
    parts = [part for part in owner_parts if part]
    for part in label_path.strip().replace("\\", "/").split("/"):
        if part in ("", "."):
            continue
        if part == "..":
            if not parts:
                raise ValueError(f"path escapes workspace: {label_path}")
            parts.pop()
            continue
        parts.append(part)
    return "/".join(parts)


def replace_gn_label_variables(label_path: str, variable_paths: dict[str, str] | None) -> str:
    if not variable_paths:
        return label_path
    resolved = label_path
    replacements: dict[str, str] = {}
    for name, value in variable_paths.items():
        clean_name = name.strip()
        if not clean_name:
            continue
        replacements[f"${{{clean_name}}}"] = value
        replacements[f"${clean_name}"] = value
    for token, value in sorted(replacements.items(), key=lambda item: len(item[0]), reverse=True):
        resolved = resolved.replace(token, value)
    return resolved


def collect_gn_dependency_dirs(
    build_gn_path: Path,
    owner_rel: str,
    absolute_prefixes: list[str],
    variable_paths: dict[str, str] | None = None,
) -> list[str]:
    if not build_gn_path.is_file():
        return []
    text = build_gn_path.read_text(encoding=TEXT_ENCODING, errors="ignore")
    dirs: list[str] = []
    normalized_prefixes = [normalize_rel(prefix) for prefix in absolute_prefixes]
    for label in re.findall(r'"([^"]+:[^"]+)"', text):
        label_path = replace_gn_label_variables(label.split(":", 1)[0].strip(), variable_paths)
        if label_path.startswith("//"):
            try:
                module_dir = normalize_rel(label_path[2:])
            except ValueError:
                continue
            if normalized_prefixes and not any(
                module_dir == prefix or module_dir.startswith(f"{prefix}/")
                for prefix in normalized_prefixes
            ):
                continue
        else:
            try:
                module_dir = resolve_relative_gn_label(owner_rel, label_path)
            except ValueError:
                continue
        if module_dir not in dirs:
            dirs.append(module_dir)
    return dirs


def collect_webview_dependency_dirs(target_root: Path) -> list[str]:
    build_gn = target_root / "base/web/webview/ohos_nweb/BUILD.gn"
    dirs = collect_gn_dependency_dirs(
        build_gn,
        "base/web/webview/ohos_nweb",
        ["base/web/webview"],
        {
            "webview_path": "//base/web/webview",
            "webview_root_path": "//base/web/webview",
        },
    )
    return [item for item in dirs if item != "base/web/webview/ohos_nweb"]


def collect_gn_import_file_rels(
    target_root: Path,
    file_rels: list[str],
    absolute_prefixes: list[str],
    variable_paths: dict[str, str] | None = None,
) -> list[str]:
    normalized_prefixes = [normalize_rel(prefix) for prefix in absolute_prefixes]
    imported: list[str] = []
    for file_rel in file_rels:
        rel = normalize_rel(file_rel)
        path = target_root / rel
        if not path.is_file():
            continue
        owner_rel = rel.rsplit("/", 1)[0] if "/" in rel else ""
        text = path.read_text(encoding=TEXT_ENCODING, errors="ignore")
        for import_label in re.findall(r'import\("([^"]+)"\)', text):
            label_path = replace_gn_label_variables(import_label.strip(), variable_paths)
            try:
                if label_path.startswith("//"):
                    import_rel = normalize_rel(label_path[2:])
                else:
                    import_rel = resolve_relative_gn_label(owner_rel, label_path)
            except ValueError:
                continue
            if normalized_prefixes and not any(
                import_rel == prefix or import_rel.startswith(f"{prefix}/")
                for prefix in normalized_prefixes
            ):
                continue
            if import_rel not in imported and (target_root / import_rel).is_file():
                imported.append(import_rel)
    return imported


def collect_webview_import_file_rels(target_root: Path, module_dirs: list[str]) -> list[str]:
    build_rels = ["base/web/webview/ohos_nweb/BUILD.gn"]
    for module_dir in module_dirs:
        build_rel = f"{normalize_rel(module_dir)}/BUILD.gn"
        if (target_root / build_rel).is_file():
            build_rels.append(build_rel)
    return collect_gn_import_file_rels(
        target_root,
        build_rels,
        ["base/web/webview"],
        {
            "webview_path": "//base/web/webview",
            "webview_root_path": "//base/web/webview",
        },
    )


def collect_target_module_closure_actions(
    target_root: Path,
    module_dirs: list[str],
    text_role: str,
    fake_role: str,
    phase: str,
    reason: str,
) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = []
    for module_dir in module_dirs:
        root = target_root / module_dir
        if not root.is_dir():
            continue
        for path in sorted(root.rglob("*")):
            if not path.is_file():
                continue
            rel_path = path.relative_to(target_root).as_posix()
            if is_text_closure_file(path):
                actions.append(copy_action(rel_path, text_role, phase, reason))
                continue
            actions.append(
                generated_fake_interface_action(
                    rel_path,
                    fake_role,
                    phase,
                    (
                        "Create a compile-only placeholder for a non-text target payload "
                        "referenced by the target module closure."
                    ),
                    "\n".join(
                        [
                            "FAKE_OPENHARMONY_PORTING_INTERFACE=1",
                            f"dependency={path.name}",
                            "scope=compile_only",
                            "runtime_status=not_functional",
                            f"reference={path}",
                            f"reference_sha256={sha256_file(path)}",
                            "note=replace_with_provenance_checked_vendor_payload_before_runtime_validation",
                        ]
                    )
                    + "\n",
                    f"non-text target payload {rel_path}",
                    str(path),
                    "replace with provenance-checked vendor/third-party payload before runtime validation",
                )
            )
    return actions


def apply_dependent_feature_deferrals(
    subsystem_name: str,
    component_name: str,
    features: list[Any],
    component_deferrals: dict[str, dict[str, Any]],
) -> tuple[list[Any], list[str]]:
    notes: list[str] = []
    if component_key(subsystem_name, component_name) != "arkui:ace_engine":
        return features, notes
    if "web:webview" not in component_deferrals:
        return features, notes

    updated_features: list[Any] = []
    for feature in features:
        name = feature_name(feature)
        if name == "ace_engine_feature_enable_web":
            updated_features.append("ace_engine_feature_enable_web = false")
            notes.append(
                "arkui:ace_engine:ace_engine_feature_enable_web=false_due_to_deferred:web:webview"
            )
        else:
            updated_features.append(feature)
    return updated_features, notes


def filter_unavailable_product_components(
    config: dict[str, Any],
    component_features: dict[str, set[str] | None] | None,
    component_deferrals: dict[str, dict[str, Any]] | None = None,
) -> tuple[dict[str, Any], list[str]]:
    filtered = copy.deepcopy(config)
    removed: list[str] = []
    if component_features is None and not component_deferrals:
        return filtered, removed
    subsystems = filtered.get("subsystems")
    if not isinstance(subsystems, list):
        return filtered, removed
    deferrals = component_deferrals or {}
    for subsystem in subsystems:
        if not isinstance(subsystem, dict):
            continue
        subsystem_name = clean_str(subsystem.get("subsystem"), "")
        components = subsystem.get("components")
        if not isinstance(components, list):
            continue
        kept = []
        for component in components:
            if not isinstance(component, dict):
                kept.append(component)
                continue
            component_name = clean_str(component.get("component"), "")
            key = component_key(subsystem_name, component_name)
            if key in deferrals:
                reason = clean_str(deferrals[key].get("reason"), "external dependency")
                removed.append(f"{key}:deferred_external_prebuilt:{reason}")
                continue
            if component_features is None:
                features = component.get("features")
                if isinstance(features, list):
                    component["features"], feature_notes = apply_dependent_feature_deferrals(
                        subsystem_name,
                        component_name,
                        features,
                        deferrals,
                    )
                    removed.extend(feature_notes)
                kept.append(component)
                continue
            if (
                not component_name
                or component_name in component_features
                or component_name == subsystem_name
            ):
                supported_features = component_features.get(component_name)
                features = component.get("features")
                if supported_features is not None and isinstance(features, list):
                    features, feature_notes = apply_dependent_feature_deferrals(
                        subsystem_name,
                        component_name,
                        features,
                        deferrals,
                    )
                    removed.extend(feature_notes)
                    kept_features = []
                    for feature in features:
                        name = feature_name(feature)
                        if not name or name in supported_features:
                            kept_features.append(feature)
                        else:
                            removed.append(f"{subsystem_name}:{component_name}:{name}")
                    component["features"] = kept_features
                kept.append(component)
            else:
                removed.append(f"{subsystem_name}:{component_name}")
        subsystem["components"] = kept
    return filtered, removed


def is_git_lfs_pointer(path: Path) -> bool:
    if not path.is_file():
        return False
    sample = path.read_bytes()[:256]
    return sample.startswith(b"version https://git-lfs.github.com/spec/v1\n")


def detect_external_prebuilt_component_deferrals(
    workspace: Path,
    target_root: Path,
    target: dict[str, str],
    enabled: bool,
) -> dict[str, dict[str, Any]]:
    if not enabled:
        return {}
    deferrals: dict[str, dict[str, Any]] = {}
    if clean_str(target.get("architecture")) != "riscv64":
        return deferrals

    webview_build = target_root / "base/web/webview/ohos_nweb/BUILD.gn"
    webview_prebuilt_rel = "base/web/webview/ohos_nweb/prebuilts/riscv64/ArkWebCore.hap"
    target_prebuilt = target_root / webview_prebuilt_rel
    workspace_prebuilt = workspace / webview_prebuilt_rel
    target_has_riscv64_branch = False
    if webview_build.is_file():
        webview_text = webview_build.read_text(encoding=TEXT_ENCODING, errors="ignore")
        target_has_riscv64_branch = (
            'target_cpu == "riscv64"' in webview_text
            and webview_prebuilt_rel.split("base/web/webview/ohos_nweb/", 1)[-1] in webview_text
        )
    if target_has_riscv64_branch and target_prebuilt.is_file() and (
        is_git_lfs_pointer(target_prebuilt) or not workspace_prebuilt.is_file()
    ):
        deferrals["web:webview"] = {
            "component": "webview",
            "subsystem": "web",
            "reason": "riscv64 WebView requires ArkWebCore.hap external prebuilt provenance",
            "target_prebuilt_path": str(target_prebuilt),
            "workspace_prebuilt_path": str(workspace_prebuilt),
            "target_prebuilt_sha256": sha256_file(target_prebuilt),
            "target_prebuilt_is_git_lfs_pointer": is_git_lfs_pointer(target_prebuilt),
            "workspace_prebuilt_exists": workspace_prebuilt.is_file(),
            "policy": "defer_component_for_compile_triage_do_not_import_prebuilt",
        }
    return deferrals


def target_has_riscv64_webview_stub_evidence(target_root: Path) -> bool:
    webview_build = target_root / "base/web/webview/ohos_nweb/BUILD.gn"
    webview_prebuilt = target_root / "base/web/webview/ohos_nweb/prebuilts/riscv64/ArkWebCore.hap"
    if not webview_build.is_file() or not webview_prebuilt.is_file():
        return False
    text = webview_build.read_text(encoding=TEXT_ENCODING, errors="ignore")
    return (
        'target_cpu == "riscv64"' in text
        and "prebuilts/riscv64/ArkWebCore.hap" in text
        and is_git_lfs_pointer(webview_prebuilt)
    )


def target_has_riscv64_ndk_evidence(target_root: Path) -> bool:
    target_ndk = target_root / "build/ohos/ndk/ndk.gni"
    if not target_ndk.is_file():
        return False
    text = target_ndk.read_text(encoding=TEXT_ENCODING, errors="ignore")
    return (
        '"//build/toolchain/ohos:ohos_clang_riscv64"' in text
        and '_ndk_shlib_directory = "riscv64-linux-ohos"' in text
    )


def target_has_riscv64_curl_evidence(target_root: Path) -> bool:
    target_curl = target_root / "third_party/curl/BUILD.gn"
    if not target_curl.is_file():
        return False
    text = target_curl.read_text(encoding=TEXT_ENCODING, errors="ignore")
    return '"${current_cpu}" == "x86_64" || "${current_cpu}" == "riscv64"' in text


def target_has_riscv64_rust_prebuilt_evidence(target_root: Path) -> bool:
    target_rust = target_root / "build/rust/BUILD.gn"
    if not target_rust.is_file():
        return False
    text = target_rust.read_text(encoding=TEXT_ENCODING, errors="ignore")
    return (
        'current_cpu == "riscv64"' in text
        and "prebuilts/rustc-riscv" in text
    )


def target_has_riscv64_libcpp_evidence(target_root: Path) -> bool:
    target_libcpp = target_root / "build/common/libcpp/BUILD.gn"
    target_prebuilt = (
        target_root
        / "prebuilts/clang/ohos/linux-x86_64/libcxx-ndk/lib/riscv64-linux-ohos/libc++_shared.so"
    )
    if not target_libcpp.is_file() or not target_prebuilt.is_file():
        return False
    text = target_libcpp.read_text(encoding=TEXT_ENCODING, errors="ignore")
    return (
        'target_cpu == "riscv64"' in text
        and "riscv64-linux-ohos/libc++_shared.so" in text
    )


def target_has_riscv64_ark_llvm_disable_evidence(target_root: Path) -> bool:
    target_ark_config = target_root / "arkcompiler/runtime_core/static_core/ark_config.gni"
    if not target_ark_config.is_file():
        return False
    text = target_ark_config.read_text(encoding=TEXT_ENCODING, errors="ignore")
    return (
        'if (target_cpu == "riscv64")' in text
        and "enable_codegen = false" in text
        and "enable_irtoc = false" in text
        and "is_llvmbackend = false" in text
        and "is_llvm_aot = false" in text
    )


def target_has_riscv64_ark_target_define_evidence(target_root: Path) -> bool:
    target_build = target_root / "arkcompiler/runtime_core/static_core/BUILD.gn"
    if not target_build.is_file():
        return False
    build_text = target_build.read_text(encoding=TEXT_ENCODING, errors="ignore")
    if not (
        'current_cpu == "riscv64"' in build_text
        and "PANDA_TARGET_RISCV64" in build_text
        and "PANDA_TARGET_64" in build_text
    ):
        return False
    cpu_features_candidates = [
        target_root / "arkcompiler/runtime_core/static_core/libarkbase/cpu_features.h",
        target_root / "arkcompiler/runtime_core/static_core/libpandabase/cpu_features.h",
    ]
    for path in cpu_features_candidates:
        if not path.is_file():
            continue
        text = path.read_text(encoding=TEXT_ENCODING, errors="ignore")
        if "PANDA_TARGET_RISCV64" in text and "CACHE_LINE_SIZE = 64" in text:
            return True
    return False


def target_has_compile_standard_whitelist_prefix_evidence(target_root: Path, prefix: str) -> bool:
    whitelist = target_root / "build/compile_standard_whitelist.json"
    if not whitelist.is_file():
        return False
    try:
        data = json.loads(whitelist.read_text(encoding=TEXT_ENCODING, errors="ignore"))
    except Exception:
        return False
    if not isinstance(data, dict):
        return False
    for values in data.values():
        if not isinstance(values, list):
            continue
        if any(isinstance(value, str) and value.startswith(prefix) for value in values):
            return True
    return False


def target_has_webview_app_fwk_update_bundle_migration_evidence(target_root: Path) -> bool:
    bundle = target_root / "base/web/webview/bundle.json"
    if not bundle.is_file():
        return False
    text = bundle.read_text(encoding=TEXT_ENCODING, errors="ignore")
    return (
        "//base/web/webview/sa/app_fwk_update:app_fwk_update_service" in text
        and "//base/web/webview/sa/app_fwk_update/include" in text
    )


def target_has_webview_app_fwk_update_test_migration_evidence(target_root: Path) -> bool:
    build_gn = target_root / "base/web/webview/test/unittest/app_fwk_update_client_test/BUILD.gn"
    if not build_gn.is_file():
        return False
    text = build_gn.read_text(encoding=TEXT_ENCODING, errors="ignore")
    return (
        "${webview_path}/sa/app_fwk_update:app_fwk_update_service" in text
        and "${webview_path}/sa/app_fwk_update/src/app_fwk_update_client.cpp" in text
    )


def target_has_profiler_smartperf_split_evidence(target_root: Path) -> bool:
    profiler_bundle = target_root / "developtools/profiler/bundle.json"
    smartperf_bundle = target_root / "developtools/smartperf_host/bundle.json"
    if not profiler_bundle.is_file() or not smartperf_bundle.is_file():
        return False
    profiler_text = profiler_bundle.read_text(encoding=TEXT_ENCODING, errors="ignore")
    smartperf_text = smartperf_bundle.read_text(encoding=TEXT_ENCODING, errors="ignore")
    return (
        "//developtools/profiler/host/smartperf/" not in profiler_text
        and "//developtools/smartperf_host/smartperf_device" in smartperf_text
        and "smartperf_host_device" in smartperf_text
    )


def file_has_riscv64_rofs_evidence(path: Path) -> bool:
    if not path.is_file():
        return False
    text = path.read_text(encoding=TEXT_ENCODING, errors="ignore")
    return (
        "lume_rofs" in text
        and 'target_cpu == "riscv64"' in text
        and "_rv64.o" in text
        and "assets/${output_obj}" in text
    )


def workspace_needs_riscv64_rofs_mapping(path: Path) -> bool:
    if not path.is_file():
        return False
    text = path.read_text(encoding=TEXT_ENCODING, errors="ignore")
    return (
        "lume_rofs" in text
        and "assets/${output_obj}" in text
        and "_x64.o" in text
        and not ('target_cpu == "riscv64"' in text and "_rv64.o" in text)
    )


def collect_graphic_3d_riscv64_rofs_paths(target_root: Path, workspace: Path) -> list[str]:
    root_rel = "foundation/graphic/graphic_3d"
    target_graphic_root = target_root / root_rel
    if not target_graphic_root.is_dir():
        return []
    paths: list[str] = []
    for target_build in sorted(target_graphic_root.rglob("BUILD.gn")):
        if not file_has_riscv64_rofs_evidence(target_build):
            continue
        rel_path = target_build.relative_to(target_root).as_posix()
        if workspace_needs_riscv64_rofs_mapping(workspace / rel_path):
            paths.append(rel_path)
    return paths


def target_has_riscv64_rofs_evidence(target_root: Path, rel_path: str) -> bool:
    target_build = target_root / rel_path
    return file_has_riscv64_rofs_evidence(target_build)


def target_has_lume_riscv64_asset_compiler_evidence(target_root: Path) -> bool:
    config_path = target_root / "foundation/graphic/graphic_3d/lume/lume_config.gni"
    app_path = target_root / "foundation/graphic/graphic_3d/lume/LumeBinaryCompile/lumeassetcompiler/src/app.cpp"
    elf_path = target_root / "foundation/graphic/graphic_3d/lume/LumeBinaryCompile/lumeassetcompiler/src/elf_common.h"
    if not (config_path.is_file() and app_path.is_file() and elf_path.is_file()):
        return False
    config_text = config_path.read_text(encoding=TEXT_ENCODING, errors="ignore")
    app_text = app_path.read_text(encoding=TEXT_ENCODING, errors="ignore")
    elf_text = elf_path.read_text(encoding=TEXT_ENCODING, errors="ignore")
    return (
        'target_cpu == "riscv64"' in config_text
        and 'cpu_type = "riscv64"' in config_text
        and "{ \"-riscv64\"" in app_text
        and "BUILD_RV64" in app_text
        and "EM_RISCV64" in elf_text
    )


def workspace_lume_asset_compiler_sources_support_riscv64(workspace: Path) -> bool:
    app_path = workspace / "foundation/graphic/graphic_3d/lume/LumeBinaryCompile/lumeassetcompiler/src/app.cpp"
    elf_path = workspace / "foundation/graphic/graphic_3d/lume/LumeBinaryCompile/lumeassetcompiler/src/elf_common.h"
    if not (app_path.is_file() and elf_path.is_file()):
        return False
    app_text = app_path.read_text(encoding=TEXT_ENCODING, errors="ignore")
    elf_text = elf_path.read_text(encoding=TEXT_ENCODING, errors="ignore")
    return "{ \"-riscv64\"" in app_text and "BUILD_RV64" in app_text and "EM_RISCV64" in elf_text


def generated_lume_asset_compiler_path(workspace: Path, product: str) -> Path:
    return (
        workspace
        / "out"
        / product
        / "gen/foundation/graphic/graphic_3d/lume/LumeBinaryCompile/lumeassetcompiler/LumeAssetCompiler"
    )


def generated_lume_asset_compiler_supports_riscv64(workspace: Path, product: str) -> bool:
    binary_path = generated_lume_asset_compiler_path(workspace, product)
    if not binary_path.is_file():
        return False
    try:
        return b"-riscv64" in binary_path.read_bytes()
    except OSError:
        return False


def target_has_riscv64_objcopy_evidence(target_root: Path, rel_path: str = "build/scripts/run_objcopy.py") -> bool:
    target_objcopy = target_root / rel_path
    if not target_objcopy.is_file():
        return False
    text = target_objcopy.read_text(encoding=TEXT_ENCODING, errors="ignore")
    return (
        '"riscv64": "elf64-littleriscv"' in text
        and '"riscv64": "riscv64"' in text
    )


def target_has_libunwind_riscv64_los_linux_drop_evidence(target_root: Path) -> bool:
    build_gn = target_root / "third_party/libunwind/BUILD.gn"
    if not build_gn.is_file():
        return False
    text = build_gn.read_text(encoding=TEXT_ENCODING, errors="ignore")
    return (
        "$libunwind_code_dir/src/riscv/Ginit_remote.c" in text
        and "$libunwind_code_dir/src/riscv/Lis_signal_frame.c" in text
        and "$libunwind_code_dir/src/riscv/Los-linux.c" not in text
    )


def target_has_ffrt_riscv64_fiber_storage_evidence(target_root: Path) -> bool:
    header = target_root / "foundation/resourceschedule/ffrt/interfaces/kits/c/type_def.h"
    if not header.is_file():
        return False
    text = header.read_text(encoding=TEXT_ENCODING, errors="ignore")
    return (
        "ffrt_fiber_storage_size = 8," in text
        and "#elif defined(__riscv)" in text
        and "ffrt_fiber_storage_size = 64," in text
    )


def target_has_riscv64_compiler_mabi_evidence(target_root: Path) -> bool:
    target_compiler = target_root / "build/config/compiler/BUILD.gn"
    if not target_compiler.is_file():
        return False
    text = target_compiler.read_text(encoding=TEXT_ENCODING, errors="ignore")
    return (
        'current_cpu == "riscv64"' in text
        and '"-march=rv64imafdc"' in text
        and '"-mabi=lp64d"' in text
    )


def target_bundle_has_feature(target_root: Path, rel_path: str, feature: str) -> bool:
    target_bundle = target_root / rel_path
    if not target_bundle.is_file():
        return False
    text = target_bundle.read_text(encoding=TEXT_ENCODING, errors="ignore")
    return feature in text


def component_feature_registry_action(
    rel_path: str,
    feature: str,
    target_root: Path,
    reason: str,
) -> dict[str, Any]:
    action = workspace_transform_action(
        rel_path,
        "component_feature_registry_compat",
        "L2_source_feature_registry_stub",
        reason,
    )
    action["add_component_features"] = [feature]
    action["dependency_policy"] = "compile_only_fake_interface"
    action["fake_interface"] = {
        "missing_dependency": f"OpenHarmony component feature declaration {feature}",
        "provenance_path": str(target_root / rel_path),
        "scope": "compile_only_feature_registry",
        "runtime_status": "not_validated",
        "follow_up": "confirm the target implementation path or replace this feature-registry shim with the real source delta",
    }
    return action


def collect_board_kernel_source_rel(target_root: Path, board_root_rel: str) -> str:
    build_gn = target_root / board_root_rel / "kernel" / "BUILD.gn"
    if not build_gn.is_file():
        return ""
    text = build_gn.read_text(encoding=TEXT_ENCODING, errors="ignore")
    match = re.search(r'kernel_source_dir\s*=\s*"//([^"]+)"', text)
    if not match:
        return ""
    try:
        rel = normalize_rel(match.group(1))
    except ValueError:
        return ""
    if rel.startswith("kernel/linux/"):
        return rel
    return ""


def planned_actions(
    seed: dict[str, Any],
    target_root: Path,
    workspace: Path,
    fake_missing_source_components: bool,
) -> tuple[list[dict[str, Any]], list[str]]:
    product = clean_str(seed.get("product"), "unknown")
    vendor = clean_str(seed.get("vendor"), "unknown")
    board = clean_str(seed.get("board"), product)
    soc_vendor = clean_str(seed.get("soc_vendor"), "unknown")
    soc = clean_str(seed.get("soc"), "unknown")

    if "unknown" in {product, vendor, board, soc_vendor, soc}:
        missing = [
            key
            for key, value in {
                "product": product,
                "vendor": vendor,
                "board": board,
                "soc_vendor": soc_vendor,
                "soc": soc,
            }.items()
            if value == "unknown"
        ]
        raise ValueError(f"target profile seed is missing required key(s): {', '.join(missing)}")

    vendor_config_rel = f"vendor/{vendor}/{product}/config.json"
    vendor_config_path = target_root / vendor_config_rel
    if not vendor_config_path.is_file():
        raise FileNotFoundError(f"target-source vendor config is required: {vendor_config_path}")

    vendor_config = read_json(vendor_config_path)
    product_config = build_productdefine(product, seed, vendor_config)
    productdefine_rel = f"productdefine/common/products/{product}.json"

    actions = [
        {
            "path": productdefine_rel,
            "content_source": "generated_from_target_vendor_config",
            "source_path": vendor_config_rel,
            "source_role": "productdefine_config",
            "phase": "L0_target_identity",
            "reason": (
                "Target reference lacks productdefine, so generate the product-visible "
                "file from seed plus target vendor config fields."
            ),
            "dependency_policy": "text_only",
            "generated_json": product_config,
        },
        copy_action(vendor_config_rel, "vendor_product_config", "L1_base_binding", "Import reviewed target vendor product configuration."),
        copy_action(f"vendor/{vendor}/{product}/ohos.build", "vendor_build_manifest", "L1_base_binding", "Import reviewed target vendor build manifest."),
        copy_action(f"vendor/{vendor}/{product}/product.gni", "vendor_product_gni", "L1_base_binding", "Import reviewed target vendor product GNI."),
        copy_action(f"device/board/{vendor}/{board}/config.gni", "board_config_gni", "L1_base_binding", "Import reviewed target board config GNI."),
        copy_action(f"device/board/{vendor}/{board}/device.gni", "board_device_gni", "L1_base_binding", "Import reviewed target board device GNI."),
        copy_action(f"device/board/{vendor}/{board}/BUILD.gn", "board_root_build_gn", "L1_base_binding", "Import the board root GN target required by the board part module list."),
        copy_action(f"device/board/{vendor}/{board}/ohos.build", "board_build_manifest", "L1_base_binding", "Import reviewed target board subsystem manifest."),
        copy_action(f"device/soc/{soc_vendor}/{soc}/soc.gni", "soc_config_gni", "L1_base_binding", "Import reviewed target SoC config GNI."),
    ]

    board_root_rel = f"device/board/{vendor}/{board}"
    board_kernel_source_rel = collect_board_kernel_source_rel(target_root, board_root_rel)
    workspace_kernel_source_is_real = bool(
        board_kernel_source_rel and (workspace / board_kernel_source_rel / "Makefile").is_file()
    )
    if (
        board_kernel_source_rel
        and (target_root / board_kernel_source_rel).is_dir()
        and not workspace_kernel_source_is_real
    ):
        fake_kernel_marker_rel = f"{board_kernel_source_rel}/.openharmony_porting_fake_kernel_source"
        actions.append(
            generated_fake_interface_action(
                fake_kernel_marker_rel,
                "board_kernel_fake_source_marker",
                "L2_external_dependency_stub",
                (
                    "Create a compile-only marker for the missing board BSP kernel source tree so "
                    "the board kernel build script can synthesize placeholder Image/DTB/KO outputs "
                    "without removing product image generation."
                ),
                "\n".join(
                    [
                        "FAKE_OPENHARMONY_PORTING_INTERFACE=1",
                        f"dependency={board_kernel_source_rel}",
                        "scope=compile_only",
                        "runtime_status=not_functional",
                        f"reference={target_root / board_kernel_source_rel}",
                        "note=replace_with_provenance_checked_board_kernel_source_before_runtime_validation",
                    ]
                )
                + "\n",
                f"board BSP kernel source tree {board_kernel_source_rel}",
                str(target_root / board_kernel_source_rel),
                "replace with provenance-checked board BSP kernel source before runtime, boot, or driver validation",
            )
        )
        actions.append(
            target_source_transform_action(
                f"{board_root_rel}/kernel/build_kernel.sh",
                "board_kernel_fake_output_bridge",
                "L2_external_dependency_stub",
                (
                    "Add a compile-only fake-output branch to the target board kernel build script; "
                    "it activates only when the generated fake kernel-source marker is present."
                ),
            )
        )
    board_module_dirs = collect_local_gn_dependency_dirs(
        target_root / board_root_rel / "BUILD.gn",
        board_root_rel,
    )
    actions.extend(
        collect_target_module_closure_actions(
            target_root,
            board_module_dirs,
            "board_module_text_config_closure",
            "board_module_fake_payload",
            "L2_board_module_text_closure",
            "Import reviewed text/config closure for local modules directly listed by the target board root BUILD.gn.",
        )
    )
    board_audio_alsa_rel = f"{board_root_rel}/audio_alsa"
    if (target_root / board_audio_alsa_rel).is_dir():
        actions.extend(
            collect_target_module_closure_actions(
                target_root,
                [board_audio_alsa_rel],
                "board_audio_alsa_text_source_closure",
                "board_audio_alsa_fake_payload",
                "L2_board_module_text_closure",
                (
                    "Import target-evidenced board audio_alsa text/source closure required by "
                    "the audio HDI adapter compile graph."
                ),
            )
        )
    soc_root_rel = f"device/soc/{soc_vendor}/{soc}"
    soc_module_dirs = collect_gn_dependency_dirs(
        target_root / board_root_rel / "BUILD.gn",
        board_root_rel,
        [soc_root_rel],
    )
    soc_hardware_rel = f"{soc_root_rel}/hardware"
    if (target_root / soc_hardware_rel / "BUILD.gn").is_file() and soc_hardware_rel not in soc_module_dirs:
        soc_module_dirs.append(soc_hardware_rel)
    actions.extend(
        collect_target_module_closure_actions(
            target_root,
            soc_module_dirs,
            "soc_module_text_source_closure",
            "soc_module_fake_payload",
            "L2_soc_module_text_closure",
            "Import reviewed text/source closure for SoC modules directly referenced by the target board root BUILD.gn.",
        )
    )

    for rel_path in [
        f"vendor/{vendor}/{product}/default_app_config/BUILD.gn",
        f"vendor/{vendor}/{product}/default_app_config/default_app.json",
    ]:
        if (target_root / rel_path).is_file():
            actions.append(
                copy_action(
                    rel_path,
                    "vendor_default_app_config",
                    "L2_runtime_config_text_closure",
                    "Import reviewed text-only default app config required by the target vendor product build.",
                )
            )

    vendor_ohos_build_path = target_root / f"vendor/{vendor}/{product}/ohos.build"
    vendor_module_dirs = collect_ohos_build_module_dirs(
        vendor_ohos_build_path,
        f"vendor/{vendor}/{product}",
    )
    actions.extend(
        collect_target_module_closure_actions(
            target_root,
            vendor_module_dirs,
            "vendor_product_text_config_closure",
            "vendor_product_fake_payload",
            "L2_vendor_product_text_closure",
            "Import reviewed text/config closure for modules directly listed by the target vendor product ohos.build.",
        )
    )

    bluetooth_root_rel = f"vendor/{vendor}/{product}/bluetooth"
    bluetooth_root = target_root / bluetooth_root_rel
    if (bluetooth_root / "BUILD.gn").is_file():
        for path in sorted(bluetooth_root.rglob("*")):
            if not path.is_file():
                continue
            rel_path = path.relative_to(target_root).as_posix()
            if path.suffix in {".gn", ".c", ".h"}:
                actions.append(
                    copy_action(
                        rel_path,
                        "vendor_bluetooth_text_source",
                        "L2_board_vendor_text_closure",
                        "Import reviewed text-only vendor Bluetooth source/build closure referenced by board ohos.build.",
                    )
                )
        firmware_rel = f"{bluetooth_root_rel}/BCM4362A2.hcd"
        firmware_path = target_root / firmware_rel
        if firmware_path.is_file():
            actions.append(
                generated_fake_interface_action(
                    firmware_rel,
                    "vendor_bluetooth_fake_firmware",
                    "L2_external_dependency_stub",
                    (
                        "Create a compile-only placeholder for the missing BCM4362A2 Bluetooth firmware so "
                        "board Bluetooth module selection remains visible while firmware provenance is reported."
                    ),
                    "\n".join(
                        [
                            "FAKE_OPENHARMONY_PORTING_INTERFACE=1",
                            "dependency=BCM4362A2.hcd",
                            "scope=compile_only",
                            "runtime_status=not_functional",
                            f"reference={firmware_path}",
                            f"reference_sha256={sha256_file(firmware_path)}",
                            "note=replace_with_provenance_checked_bluetooth_firmware_before_runtime_validation",
                        ]
                    )
                    + "\n",
                    "Broadcom BCM4362A2 Bluetooth firmware",
                    str(firmware_path),
                    "replace with provenance-checked Bluetooth firmware before runtime validation",
                )
            )

    inherit_paths: list[str] = []
    for item in product_config.get("inherit") or []:
        if isinstance(item, str) and item.strip().endswith(".json"):
            inherit_paths.append(normalize_rel(item))
    for inherit_rel in dict.fromkeys(inherit_paths):
        if inherit_rel.startswith("productdefine/common/inherit/"):
            actions.append(
                copy_action(
                    inherit_rel,
                    "productdefine_inherit_config",
                    "L0_target_identity",
                    "Import direct product inheritance file referenced by generated productdefine.",
                )
            )

    if clean_str(seed.get("architecture")) == "riscv64" and target_has_riscv64_ndk_evidence(target_root):
        actions.append(
            workspace_transform_action(
                "build/ohos/ndk/ndk.gni",
                "build_riscv64_ndk_compat",
                "L1_build_compatibility",
                (
                    "Add the riscv64 NDK output-directory mapping evidenced by the target source tree; "
                    "OpenHarmony 6.0 otherwise asserts when ohos_ndk_library is evaluated for riscv64."
                ),
            )
        )
    if clean_str(seed.get("architecture")) == "riscv64" and target_has_riscv64_curl_evidence(target_root):
        actions.append(
            workspace_transform_action(
                "third_party/curl/BUILD.gn",
                "third_party_curl_riscv64_compat",
                "L1_build_compatibility",
                (
                    "Add the riscv64 cflags guard evidenced by the target source tree; "
                    "OpenHarmony 6.0 otherwise leaves curl cflags undefined for riscv64."
                ),
            )
        )

    if clean_str(seed.get("architecture")) == "riscv64" and target_has_riscv64_rust_prebuilt_evidence(target_root):
        actions.append(
            workspace_transform_action(
                "build/rust/BUILD.gn",
                "rust_riscv64_prebuilt_build_rule",
                "L2_external_dependency_stub",
                (
                    "Add target-evidenced riscv64 Rust std/test dylib source rules; "
                    "the actual riscv64 Rust dylibs are represented by tracked fake binary placeholders."
                ),
            )
        )
        actions.append(
            workspace_transform_action(
                "build/rust/tests/BUILD.gn",
                "rust_tests_riscv64_prebuilt_build_rule",
                "L2_external_dependency_stub",
                (
                    "Add target-evidenced riscv64 Rust test prebuilt source rules and target test gating; "
                    "the actual riscv64 Rust dylib is represented by the tracked fake binary placeholder."
                ),
            )
        )
        rust_fake_pairs = [
            (
                "libstd.dylib.so",
                "prebuilts/rustc/linux-x86_64/current/lib/rustlib/x86_64-unknown-linux-ohos/lib/libstd.dylib.so",
            ),
            (
                "libtest.dylib.so",
                "prebuilts/rustc/linux-x86_64/current/lib/rustlib/x86_64-unknown-linux-ohos/lib/libtest.dylib.so",
            ),
        ]
        for filename, source_rel in rust_fake_pairs:
            target_rel = (
                "prebuilts/rustc-riscv/linux-x86_64/current/lib/rustlib/"
                f"riscv64-unknown-linux-ohos/lib/{filename}"
            )
            target_prebuilt = target_root / target_rel
            if (workspace / source_rel).is_file() and target_prebuilt.is_file():
                actions.append(
                    workspace_fake_binary_action(
                        target_rel,
                        source_rel,
                        "rust_riscv64_fake_dylib",
                        "L2_external_dependency_stub",
                        (
                            f"Create a compile-only wrong-architecture placeholder for missing riscv64 Rust {filename}; "
                            "this keeps build graph progress while preserving dependency debt."
                        ),
                        f"riscv64 Rust prebuilt {filename}",
                        str(target_prebuilt),
                        "replace with provenance-checked prebuilts/rustc-riscv payload before runtime or packaging validation",
                    )
                )

    if clean_str(seed.get("architecture")) == "riscv64" and target_has_riscv64_libcpp_evidence(target_root):
        actions.append(
            workspace_transform_action(
                "build/common/libcpp/BUILD.gn",
                "libcpp_riscv64_prebuilt_build_rule",
                "L1_build_compatibility",
                (
                    "Add target-evidenced riscv64 libc++ shared-library prebuilt source rules so "
                    "the build/common libcpp install target has a concrete source path."
                ),
            )
        )
        libcpp_rel = "prebuilts/clang/ohos/linux-x86_64/libcxx-ndk/lib/riscv64-linux-ohos/libc++_shared.so"
        fallback_rel = "prebuilts/clang/ohos/linux-x86_64/libcxx-ndk/lib/x86_64-linux-ohos/libc++_shared.so"
        if not (workspace / libcpp_rel).is_file() and (workspace / fallback_rel).is_file():
            actions.append(
                workspace_fake_binary_action(
                    libcpp_rel,
                    fallback_rel,
                    "libcpp_riscv64_fake_shared_library",
                    "L2_external_dependency_stub",
                    (
                        "Create a compile-only wrong-architecture placeholder for missing riscv64 libc++_shared.so; "
                        "this keeps the prebuilt copy rule concrete while preserving dependency debt."
                    ),
                    "riscv64 libc++_shared.so prebuilt",
                    str(target_root / libcpp_rel),
                    "replace with provenance-checked riscv64 clang libcxx-ndk prebuilt before packaging or runtime validation",
                )
            )

    if clean_str(seed.get("architecture")) == "riscv64" and target_has_riscv64_ark_llvm_disable_evidence(target_root):
        actions.append(
            workspace_transform_action(
                "arkcompiler/runtime_core/static_core/ark_config.gni",
                "arkcompiler_riscv64_llvmbackend_disable",
                "L1_build_compatibility",
                (
                    "Apply the target-evidenced riscv64 ArkCompiler compatibility rule that disables "
                    "LLVM backend/irtoc/codegen for riscv64 so libllvmbackend's non-riscv64 assertion "
                    "is not reached."
                ),
            )
        )

    if clean_str(seed.get("architecture")) == "riscv64" and target_has_riscv64_ark_target_define_evidence(target_root):
        actions.append(
            workspace_transform_action(
                "arkcompiler/runtime_core/static_core/BUILD.gn",
                "arkcompiler_riscv64_target_defines",
                "L1_build_compatibility",
                (
                    "Add target-evidenced ArkCompiler PANDA_TARGET_RISCV64/PANDA_TARGET_64 defines "
                    "for riscv64 static_core builds."
                ),
            )
        )
        actions.append(
            workspace_transform_action(
                "arkcompiler/runtime_core/static_core/libpandabase/cpu_features.h",
                "arkcompiler_riscv64_cache_line_size",
                "L1_build_compatibility",
                (
                    "Extend the target-evidenced ArkCompiler cache-line-size condition to riscv64 "
                    "without importing the broader 6.1 libarkbase rename set."
                ),
            )
        )

    soc_display_whitelist_prefix = f"//device/soc/{soc_vendor}/{soc}/hardware/display"
    if target_has_compile_standard_whitelist_prefix_evidence(target_root, soc_display_whitelist_prefix):
        actions.append(
            workspace_transform_action(
                "build/compile_standard_whitelist.json",
                "soc_display_compile_standard_whitelist_entries",
                "L1_build_compatibility",
                (
                    "Merge target-evidenced compile-standard whitelist entries for SoC display "
                    "vendor/HDF targets so part/subsystem check exceptions match the imported "
                    "board display build graph."
                ),
            )
        )

    if clean_str(seed.get("architecture")) == "riscv64":
        for rel_path in collect_graphic_3d_riscv64_rofs_paths(target_root, workspace):
            if target_has_riscv64_rofs_evidence(target_root, rel_path):
                actions.append(
                    workspace_transform_action(
                        rel_path,
                        "graphic_3d_riscv64_rofs_build_rule",
                        "L1_build_compatibility",
                        (
                            "Add target-evidenced riscv64 rofs object mapping so graphic_3d embedded asset "
                            "rules produce a concrete rv64 object path instead of an empty assets directory."
                        ),
                    )
                )
        if target_has_lume_riscv64_asset_compiler_evidence(target_root):
            for rel_path, role, reason in [
                (
                    "foundation/graphic/graphic_3d/lume/lume_config.gni",
                    "lume_rofs_riscv64_cpu_type_compat",
                    "Add target-evidenced riscv64 cpu_type mapping and forward declared LumeAssetCompiler inputs.",
                ),
                (
                    "foundation/graphic/graphic_3d/lume/LumeBinaryCompile/lumeassetcompiler/BUILD.gn",
                    "lume_asset_compiler_declared_inputs",
                    "Declare LumeAssetCompiler CMake and C++ source files as action inputs to avoid stale generated host tools.",
                ),
                (
                    "foundation/graphic/graphic_3d/lume/LumeBinaryCompile/lumeassetcompiler/src/elf_common.h",
                    "lume_asset_compiler_riscv64_elf_machine",
                    "Add target-evidenced RISC-V ELF machine id for Lume generated rofs objects.",
                ),
                (
                    "foundation/graphic/graphic_3d/lume/LumeBinaryCompile/lumeassetcompiler/src/app.cpp",
                    "lume_asset_compiler_riscv64_platform",
                    "Add target-evidenced -riscv64 platform parsing and rv64 ELF output generation.",
                ),
            ]:
                actions.append(
                    workspace_transform_action(
                        rel_path,
                        role,
                        "L1_build_compatibility",
                        reason,
                    )
                )

    if clean_str(seed.get("architecture")) == "riscv64" and target_has_riscv64_objcopy_evidence(target_root):
        actions.append(
            workspace_transform_action(
                "build/scripts/run_objcopy.py",
                "build_scripts_run_objcopy_riscv64_compat",
                "L1_build_compatibility",
                (
                    "Add target-evidenced riscv64 llvm-objcopy output and BFD arch mappings so "
                    "binary-to-object resource generation does not fail with KeyError: 'riscv64'."
                ),
            )
        )

    if clean_str(seed.get("architecture")) == "riscv64" and target_has_libunwind_riscv64_los_linux_drop_evidence(target_root):
        actions.append(
            workspace_transform_action(
                "third_party/libunwind/BUILD.gn",
                "libunwind_riscv64_drop_missing_los_linux",
                "L1_build_compatibility",
                (
                    "Remove target-evidenced stale RISC-V libunwind Los-linux.c source references; "
                    "the shared libunwind-1.8.1 tarball has no src/riscv/Los-linux.c."
                ),
            )
        )

    if clean_str(seed.get("architecture")) == "riscv64" and target_has_ffrt_riscv64_fiber_storage_evidence(target_root):
        actions.append(
            workspace_transform_action(
                "foundation/resourceschedule/ffrt/interfaces/kits/c/type_def.h",
                "ffrt_riscv64_fiber_storage_size",
                "L1_build_compatibility",
                (
                    "Add the target-evidenced __riscv FFRT fiber storage-size branch so FFRT public "
                    "headers compile for RISC-V without importing unrelated 6.1 API enum additions."
                ),
            )
        )

    arkui_objcopy_rel = "foundation/arkui/ace_engine/build/tools/run_objcopy.py"
    if clean_str(seed.get("architecture")) == "riscv64" and target_has_riscv64_objcopy_evidence(target_root, arkui_objcopy_rel):
        actions.append(
            workspace_transform_action(
                arkui_objcopy_rel,
                "arkui_run_objcopy_riscv64_compat",
                "L1_build_compatibility",
                (
                    "Add target-evidenced riscv64 llvm-objcopy output and BFD arch mappings to "
                    "ArkUI's local binary-to-object helper."
                ),
            )
        )

    if clean_str(seed.get("architecture")) == "riscv64" and target_has_riscv64_compiler_mabi_evidence(target_root):
        actions.append(
            workspace_transform_action(
                "build/config/components/musl/BUILD.gn",
                "riscv64_musl_cflags_mabi_compat",
                "L1_build_compatibility",
                (
                    "Make musl riscv64 compile/link cflags carry the same target-evidenced "
                    "-mabi=lp64d ABI as the global compiler riscv64 rule."
                ),
            )
        )
        actions.append(
            workspace_transform_action(
                "build/config/compiler/BUILD.gn",
                "riscv64_compiler_ldflags_mabi_compat",
                "L1_build_compatibility",
                (
                    "Align riscv64 linker ABI flags with the existing target-evidenced cflags "
                    "when lld reports mixed floating-point ABI objects."
                ),
            )
        )

    param_fixer_rel = "base/startup/init/services/etc/param/param_fixer.py"
    target_param_fixer = target_root / param_fixer_rel
    if target_param_fixer.is_file() and (target_param_fixer.stat().st_mode & 0o111):
        actions.append(
            copy_action(
                param_fixer_rel,
                "startup_param_fixer_executable_script",
                "L1_build_compatibility",
                (
                    "Preserve the target-evidenced executable bit for param_fixer.py; "
                    "GN/Ninja invokes it directly through /usr/bin/env during parameter generation."
                ),
            )
        )

    feature_registry_shims = [
        (
            "base/update/updater/bundle.json",
            "updater_feature_updater_gen_executable",
            "Add the updater feature declaration evidenced by the target reference so product feature selection remains unchanged.",
        ),
        (
            "developtools/smartperf_host/bundle.json",
            "smartperf_host_device",
            "Add the SmartPerf device feature declaration evidenced by the target reference so product feature selection remains unchanged.",
        ),
    ]
    for rel_path, feature, reason in feature_registry_shims:
        if target_bundle_has_feature(target_root, rel_path, feature):
            actions.append(component_feature_registry_action(rel_path, feature, target_root, reason))

    if target_has_profiler_smartperf_split_evidence(target_root):
        actions.append(
            workspace_transform_action(
                "developtools/profiler/bundle.json",
                "profiler_smartperf_split_bundle_migration",
                "L2_component_registry_migration",
                (
                    "Apply the target-evidenced SmartPerf split: remove legacy "
                    "developtools/profiler/host/smartperf module and test labels from hiprofiler "
                    "so smartperf_host owns SmartPerf without duplicate fuzz outputs."
                ),
            )
        )

    if clean_str(seed.get("architecture")) == "riscv64" and target_has_riscv64_webview_stub_evidence(target_root):
        prebuilt_rel = "base/web/webview/ohos_nweb/prebuilts/riscv64/ArkWebCore.hap"
        target_prebuilt = target_root / prebuilt_rel
        webview_module_dirs = collect_webview_dependency_dirs(target_root)
        actions.append(
            copy_action(
                "base/web/webview/ohos_nweb/BUILD.gn",
                "webview_riscv64_build_rule",
                "L2_external_dependency_stub",
                (
                    "Import the text-only WebView build rule that declares the target riscv64 "
                    "ArkWebCore HAP path; the actual external HAP remains a tracked fake interface."
                ),
            )
        )
        actions.append(
            generated_fake_interface_action(
                prebuilt_rel,
                "webview_riscv64_fake_arkwebcore_hap",
                "L2_external_dependency_stub",
                (
                    "Create a compile-only placeholder for the missing riscv64 ArkWebCore HAP so "
                    "the product keeps webview enabled while dependency provenance is reported."
                ),
                "\n".join(
                    [
                        "FAKE_OPENHARMONY_PORTING_INTERFACE=1",
                        "dependency=ArkWebCore.hap",
                        "architecture=riscv64",
                        "scope=compile_only",
                        "runtime_status=not_functional",
                        f"reference={target_prebuilt}",
                        f"reference_sha256={sha256_file(target_prebuilt)}",
                        "note=replace_with_provenance_checked_vendor_or_third_party_hap_before_runtime_validation",
                    ]
                )
                + "\n",
                "WebView riscv64 ArkWebCore.hap external prebuilt",
                str(target_prebuilt),
            )
        )
        for rel_path in collect_webview_import_file_rels(target_root, webview_module_dirs):
            if is_text_closure_file(target_root / rel_path):
                actions.append(
                    copy_action(
                        rel_path,
                        "webview_imported_gni_text_closure",
                        "L2_webview_local_module_text_closure",
                        (
                            "Import target WebView local GN/GNI support file required by "
                            "the copied riscv64 WebView build rules."
                        ),
                    )
                )
        if target_has_webview_app_fwk_update_bundle_migration_evidence(target_root):
            actions.append(
                workspace_transform_action(
                    "base/web/webview/bundle.json",
                    "webview_bundle_app_fwk_update_sa_migration",
                    "L2_webview_local_module_text_closure",
                    (
                        "Rewrite the WebView component registry from the old flat sa app_fwk_update "
                        "target to the target-evidenced sa/app_fwk_update target so both services do "
                        "not generate libapp_fwk_update_service.z.so."
                    ),
                )
            )
        if target_has_webview_app_fwk_update_test_migration_evidence(target_root):
            actions.extend(
                collect_target_module_closure_actions(
                    target_root,
                    ["base/web/webview/test/unittest/app_fwk_update_client_test"],
                    "webview_app_fwk_update_test_text_closure",
                    "webview_app_fwk_update_test_fake_payload",
                    "L2_webview_local_module_text_closure",
                    (
                        "Import the target-evidenced WebView app_fwk_update unit-test closure so "
                        "test deps also point at sa/app_fwk_update instead of the old flat sa service."
                    ),
                )
            )
        actions.extend(
            collect_target_module_closure_actions(
                target_root,
                webview_module_dirs,
                "webview_local_module_text_closure",
                "webview_local_module_fake_payload",
                "L2_webview_local_module_text_closure",
                (
                    "Import reviewed text/source closure for local WebView modules directly "
                    "referenced by the target riscv64 ohos_nweb BUILD.gn, including GN labels "
                    "resolved through webview_path."
                ),
            )
        )

    if fake_missing_source_components:
        target_identity = {
            "product": product,
            "board": board,
            "vendor": vendor,
        }
        component_features = collect_workspace_component_features(workspace, target_identity)
        subsystem_paths = read_subsystem_paths(workspace)
        for entry in collect_declared_target_components(product_config, target_root):
            subsystem = entry["subsystem"]
            component = entry["component"]
            if component == subsystem or component in component_features:
                continue
            subsystem_base_path = subsystem_paths.get(subsystem)
            if not subsystem_base_path:
                continue
            actions.append(
                generated_fake_component_bundle_action(
                    vendor,
                    product,
                    subsystem,
                    component,
                    subsystem_base_path,
                )
            )

    deduped_actions: list[dict[str, Any]] = []
    seen_action_paths: set[str] = set()
    for action in actions:
        action_path = clean_str(action.get("path"), "")
        if action_path in seen_action_paths:
            continue
        seen_action_paths.add(action_path)
        deduped_actions.append(action)
    actions = deduped_actions

    notes = [
        "Real binary, firmware, bootloader, prebuilt, and kernel-module payloads are intentionally excluded.",
        "External binary/prebuilt blockers may be represented by compile-only fake interfaces so product features stay visible until dependency analysis is generated.",
        "Missing source component registries may be represented by compile-only fake bundle.json files, with zero sub-components, to keep product selection unchanged during dependency triage.",
        "Board root BUILD.gn is included because board ohos.build references it directly; feature subdirectories remain follow-up batches.",
        "Runtime/HDF config remains a follow-up batch unless build triage shows it is a direct base-binding blocker.",
        "RISC-V NDK build-file compatibility is applied only when target-source evidence contains the riscv64 NDK mapping.",
        "RISC-V third_party/curl build compatibility is applied only when target-source evidence contains the riscv64 cflags guard.",
        "RISC-V build/common libcpp prebuilt source mapping is applied only when target-source evidence contains the riscv64 libc++ rule.",
        "RISC-V ArkCompiler LLVM backend/codegen disablement is applied only when target-source evidence contains the riscv64 ark_config rule.",
        "RISC-V graphic_3d embedded-asset rofs object mappings are applied only when target-source evidence contains matching rv64 object rules.",
        "RISC-V run_objcopy architecture mappings are applied only when target-source evidence contains riscv64 BFD/output mappings.",
        "Target-evidenced executable bits are preserved for directly invoked build scripts such as param_fixer.py and board build_kernel.sh.",
        "SmartPerf split component-registry migration removes legacy hiprofiler-hosted SmartPerf labels only when target evidence shows SmartPerf is owned by smartperf_host.",
        "Vendor product module text/config closures are imported only from direct target ohos.build module labels; non-text payloads become compile-only fake interfaces.",
        "Board module text/config closures are imported only from local labels in the target board root BUILD.gn; kernel modules, bootloader images, and firmware become compile-only fake interfaces.",
        "Board audio_alsa text/source closures are imported when target evidence provides board-specific audio adapter sources required by Ninja.",
        "Missing board BSP kernel source trees may use a tracked fake kernel-source marker plus a build_kernel.sh fake-output bridge so image generation remains visible during dependency triage.",
        "SoC module text/source closures are imported only from target board BUILD.gn labels under the selected SoC root; firmware and proprietary GPU/WiFi/shared-library payloads become compile-only fake interfaces.",
        "WebView local module text/source closures are imported from target ohos_nweb GN labels after resolving webview_path-style variables; binary/prebuilt payloads remain fake-interface debt.",
        "WebView app_fwk_update component-registry labels are migrated to the target sa/app_fwk_update module when target evidence shows the service moved from the old flat sa target.",
        "WebView app_fwk_update test closures are migrated with target evidence when test deps would otherwise keep the old flat sa service in the GN graph.",
    ]
    return actions, notes


def dump_json_bytes(data: dict[str, Any]) -> bytes:
    return (json.dumps(data, ensure_ascii=False, indent=4) + "\n").encode(TEXT_ENCODING)


def normalize_ohos_build_subsystem(
    data: bytes,
    action: dict[str, Any],
    target: dict[str, str],
    enabled: bool,
) -> tuple[bytes, list[str]]:
    if not enabled:
        return data, []
    rel_path = clean_str(action.get("path"), "")
    if not rel_path.endswith("/ohos.build"):
        return data, []
    try:
        build_data = json.loads(data.decode(TEXT_ENCODING))
    except Exception:
        return data, []
    if not isinstance(build_data, dict):
        return data, []

    product = clean_str(target.get("product"), "unknown")
    board = clean_str(target.get("board"), product)
    vendor = clean_str(target.get("vendor"), "unknown")
    parts = build_data.setdefault("parts", {})
    if not isinstance(parts, dict):
        return data, []

    changed = False
    notes: list[str] = []
    vendor_ohos_build = f"vendor/{vendor}/{product}/ohos.build"
    board_ohos_build = f"device/board/{vendor}/{board}/ohos.build"

    if rel_path == vendor_ohos_build:
        expected_subsystem = f"product_{product}"
        if build_data.get("subsystem") != expected_subsystem:
            notes.append(
                f"normalized vendor ohos.build subsystem from {build_data.get('subsystem')} to {expected_subsystem}"
            )
            build_data["subsystem"] = expected_subsystem
            changed = True
    elif rel_path == board_ohos_build:
        expected_subsystem = f"device_{board}"
        if build_data.get("subsystem") != expected_subsystem:
            notes.append(
                f"normalized board ohos.build subsystem from {build_data.get('subsystem')} to {expected_subsystem}"
            )
            build_data["subsystem"] = expected_subsystem
            changed = True
        if expected_subsystem not in parts:
            template = copy.deepcopy(next(iter(parts.values()))) if parts else {}
            if not isinstance(template, dict):
                template = {}
            template.setdefault("module_list", [f"//device/board/{vendor}/{board}:{board}_group"])
            template.setdefault("test_list", [])
            template.setdefault("inner_kits", [])
            parts[expected_subsystem] = template
            notes.append(f"added {expected_subsystem} part alias for OpenHarmony 6.0 device-specific part")
            changed = True
    if changed:
        return dump_json_bytes(build_data), notes
    return data, []


def apply_riscv64_ndk_compat(data: bytes) -> tuple[bytes, list[str]]:
    text = data.decode(TEXT_ENCODING, errors="ignore")
    notes: list[str] = []

    if '"//build/toolchain/ohos:ohos_clang_riscv64",' not in text:
        old_toolchains = (
            '        "//build/toolchain/ohos:ohos_clang_arm64",\n'
            '        "//build/toolchain/ohos:ohos_clang_x86_64",'
        )
        new_toolchains = (
            '        "//build/toolchain/ohos:ohos_clang_arm64",\n'
            '        "//build/toolchain/ohos:ohos_clang_riscv64",\n'
            '        "//build/toolchain/ohos:ohos_clang_x86_64",'
        )
        if old_toolchains in text:
            text = text.replace(old_toolchains, new_toolchains, 1)
            notes.append("added riscv64 to OpenHarmony NDK toolchain fan-out list")
        else:
            notes.append("riscv64 NDK toolchain fan-out insertion point not found")

    if '_ndk_shlib_directory = "riscv64-linux-ohos"' not in text:
        old_mapping = (
            '    } else if (_toolchain == "//build/toolchain/ohos:ohos_clang_arm64") {\n'
            '      _ndk_shlib_directory = "aarch64-linux-ohos"\n'
            '    } else if (_toolchain == "//build/toolchain/ohos:ohos_clang_x86_64") {'
        )
        new_mapping = (
            '    } else if (_toolchain == "//build/toolchain/ohos:ohos_clang_arm64") {\n'
            '      _ndk_shlib_directory = "aarch64-linux-ohos"\n'
            '    } else if (_toolchain == "//build/toolchain/ohos:ohos_clang_riscv64") {\n'
            '      _ndk_shlib_directory = "riscv64-linux-ohos"\n'
            '    } else if (_toolchain == "//build/toolchain/ohos:ohos_clang_x86_64") {'
        )
        if old_mapping in text:
            text = text.replace(old_mapping, new_mapping, 1)
            notes.append("added riscv64-linux-ohos NDK shlib directory mapping")
        else:
            notes.append("riscv64 NDK shlib mapping insertion point not found")
    else:
        notes.append("riscv64 NDK shlib directory mapping already present")

    return text.encode(TEXT_ENCODING), notes


def apply_riscv64_curl_compat(data: bytes) -> tuple[bytes, list[str]]:
    text = data.decode(TEXT_ENCODING, errors="ignore")
    notes: list[str] = []
    old_condition = (
        '    } else if ("${current_cpu}" == "arm64" || "${current_cpu}" == "arm" ||\n'
        '               "${current_cpu}" == "x86_64") {'
    )
    new_condition = (
        '    } else if ("${current_cpu}" == "arm64" || "${current_cpu}" == "arm" ||\n'
        '               "${current_cpu}" == "x86_64" || "${current_cpu}" == "riscv64") {'
    )
    count = text.count(old_condition)
    if count:
        text = text.replace(old_condition, new_condition)
        notes.append(f"added riscv64 to third_party/curl standard cflags guard in {count} location(s)")
    elif new_condition in text:
        notes.append("third_party/curl riscv64 cflags guard already present")
    else:
        notes.append("third_party/curl riscv64 cflags guard insertion point not found")
    return text.encode(TEXT_ENCODING), notes


def apply_riscv64_graphic_3d_rofs_compat(data: bytes) -> tuple[bytes, list[str]]:
    text = data.decode(TEXT_ENCODING, errors="ignore")
    if 'target_cpu == "riscv64"' in text and "_rv64.o" in text:
        return data, ["graphic_3d riscv64 rofs object mapping already present"]

    pattern = re.compile(
        r'(  if \(target_cpu == "(?:x64|x86_64)"\) \{\n'
        r'    output_obj = "\$\{([^}]+)\}_x64\.o"\n'
        r'  \}\n)'
    )

    def add_riscv64_branch(match: re.Match[str]) -> str:
        variable_name = match.group(2)
        return (
            match.group(1)
            + "\n"
            + '  if (target_cpu == "riscv64") {\n'
            + f'    output_obj = "${{{variable_name}}}_rv64.o"\n'
            + "  }\n"
        )

    text, count = pattern.subn(add_riscv64_branch, text)
    if count:
        return (
            text.encode(TEXT_ENCODING),
            [f"added riscv64 graphic_3d rofs object mapping in {count} location(s)"],
        )
    return data, ["graphic_3d riscv64 rofs insertion point not found"]


def apply_lume_rofs_riscv64_cpu_type_compat(data: bytes) -> tuple[bytes, list[str]]:
    text = data.decode(TEXT_ENCODING, errors="ignore")
    notes: list[str] = []

    if 'target_cpu == "riscv64"' in text and 'cpu_type = "riscv64"' in text:
        notes.append("Lume rofs riscv64 cpu_type mapping already present")
    else:
        pattern = re.compile(
            r'(    if \(target_cpu == "(?:x64|x86_64)"(?: \|\| target_cpu == "x64")?\) \{\n'
            r'      cpu_type = "[^"]+"\n'
            r'      output_obj = "\$\{invoker\.base_name\}_x64\.o"\n'
            r'    \}\n)'
        )

        def add_riscv64_branch(match: re.Match[str]) -> str:
            return (
                match.group(1)
                + '    if (target_cpu == "riscv64") {\n'
                + '      cpu_type = "riscv64"\n'
                + '      output_obj = "${invoker.base_name}_rv64.o"\n'
                + "    }\n"
            )

        text, count = pattern.subn(add_riscv64_branch, text, count=1)
        if count:
            notes.append("added Lume rofs riscv64 cpu_type/output mapping")
        else:
            notes.append("Lume rofs riscv64 cpu_type insertion point not found")

    if "if (defined(invoker.inputs))" in text and "inputs = invoker.inputs" in text:
        notes.append("Lume binary compile action already forwards explicit inputs")
    else:
        old = '    args = [ rebase_path(invoker.dest_gen_path, root_build_dir) ]\n'
        new = (
            old
            + "    if (defined(invoker.inputs)) {\n"
            + "      inputs = invoker.inputs\n"
            + "    }\n"
        )
        if old in text:
            text = text.replace(old, new, 1)
            notes.append("added Lume binary compile action input forwarding")
        else:
            notes.append("Lume binary compile action input insertion point not found")
    return text.encode(TEXT_ENCODING), notes


def apply_lume_asset_compiler_declared_inputs(data: bytes) -> tuple[bytes, list[str]]:
    text = data.decode(TEXT_ENCODING, errors="ignore")
    if "src/app.cpp" in text and "src/elf_common.h" in text and "inputs = [" in text:
        return data, ["Lume asset compiler action inputs already declared"]
    old = '  dest_gen_path = "$target_gen_dir"\n'
    new = (
        old
        + "  inputs = [\n"
        + '    "${LUME_BINARY_PATH}/lumeassetcompiler/CMakeLists.txt",\n'
        + '    "${LUME_BINARY_PATH}/lumeassetcompiler/build.sh",\n'
        + '    "${LUME_BINARY_PATH}/lumeassetcompiler/src/app.cpp",\n'
        + '    "${LUME_BINARY_PATH}/lumeassetcompiler/src/app.h",\n'
        + '    "${LUME_BINARY_PATH}/lumeassetcompiler/src/app_main.cpp",\n'
        + '    "${LUME_BINARY_PATH}/lumeassetcompiler/src/coff.h",\n'
        + '    "${LUME_BINARY_PATH}/lumeassetcompiler/src/dir.cpp",\n'
        + '    "${LUME_BINARY_PATH}/lumeassetcompiler/src/dir.h",\n'
        + '    "${LUME_BINARY_PATH}/lumeassetcompiler/src/elf32.h",\n'
        + '    "${LUME_BINARY_PATH}/lumeassetcompiler/src/elf64.h",\n'
        + '    "${LUME_BINARY_PATH}/lumeassetcompiler/src/elf_common.h",\n'
        + '    "${LUME_BINARY_PATH}/lumeassetcompiler/src/maco.h",\n'
        + '    "${LUME_BINARY_PATH}/lumeassetcompiler/src/platform.cpp",\n'
        + '    "${LUME_BINARY_PATH}/lumeassetcompiler/src/platform.h",\n'
        + '    "${LUME_BINARY_PATH}/lumeassetcompiler/src/toarray.h",\n'
        + "  ]\n"
    )
    if old in text:
        text = text.replace(old, new, 1)
        return text.encode(TEXT_ENCODING), ["declared Lume asset compiler CMake/source inputs"]
    return data, ["Lume asset compiler action input insertion point not found"]


def apply_lume_asset_compiler_riscv64_elf_machine(data: bytes) -> tuple[bytes, list[str]]:
    text = data.decode(TEXT_ENCODING, errors="ignore")
    if "EM_RISCV64" in text:
        return data, ["Lume asset compiler RISC-V ELF machine id already present"]
    anchor = "#define EM_AARCH64 183 /* ARM 64 bit */\n"
    if anchor in text:
        text = text.replace(anchor, anchor + "#define EM_RISCV64 243 /* RISCV 64 bit */\n", 1)
        return text.encode(TEXT_ENCODING), ["added Lume asset compiler EM_RISCV64 id"]
    return data, ["Lume asset compiler EM_RISCV64 insertion point not found"]


def apply_lume_asset_compiler_riscv64_platform(data: bytes) -> tuple[bytes, list[str]]:
    text = data.decode(TEXT_ENCODING, errors="ignore")
    notes: list[str] = []

    if "BUILD_RV64" not in text:
        old = "    BUILD_V8 = (1 << 3),\n"
        new = old + "    BUILD_RV64 = (1 << 7),\n"
        if old in text:
            text = text.replace(old, new, 1)
            notes.append("added Lume asset compiler BUILD_RV64 architecture bit")
        else:
            notes.append("Lume asset compiler BUILD_RV64 insertion point not found")
    else:
        notes.append("Lume asset compiler BUILD_RV64 already present")

    if "{ \"-riscv64\"" not in text:
        old = '    { "-arm64-v8a", PLATFORM_AD | BUILD_V8 | PlatformSet() },\n'
        new = old + '    { "-riscv64", PLATFORM_AD | BUILD_RV64 | PlatformSet() },\n'
        if old in text:
            text = text.replace(old, new, 1)
            notes.append("added Lume asset compiler -riscv64 platform parser entry")
        else:
            notes.append("Lume asset compiler -riscv64 platform insertion point not found")
    else:
        notes.append("Lume asset compiler -riscv64 platform parser entry already present")

    old_default = "uint32_t arcAndPlat = (BUILD_X86 | BUILD_X64 | BUILD_V7 | BUILD_V8) |"
    new_default = "uint32_t arcAndPlat = (BUILD_X86 | BUILD_X64 | BUILD_V7 | BUILD_V8 | BUILD_RV64) |"
    if old_default in text:
        text = text.replace(old_default, new_default, 1)
        notes.append("included BUILD_RV64 in Lume asset compiler default arch set")
    elif new_default in text:
        notes.append("Lume asset compiler default arch set already includes BUILD_RV64")
    else:
        notes.append("Lume asset compiler default arch set insertion point not found")

    if 'std::string rv64Name = "rofs_rv64.o";' not in text:
        old = '    std::string o64Name = "rofs_64.o";\n'
        new = old + '    std::string rv64Name = "rofs_rv64.o";\n'
        if old in text:
            text = text.replace(old, new, 1)
            notes.append("added Lume asset compiler rv64 output name variable")
        else:
            notes.append("Lume asset compiler rv64 output variable insertion point not found")
    else:
        notes.append("Lume asset compiler rv64 output name variable already present")

    old_assignment = "secName = obj32Name = obj64Name = o32Name = o64Name = x32Name = x64Name = macName = argv[baseArg + FILE_NAME];"
    new_assignment = "secName = obj32Name = obj64Name = o32Name = o64Name = rv64Name = x32Name = x64Name = macName = argv[baseArg + FILE_NAME];"
    if old_assignment in text:
        text = text.replace(old_assignment, new_assignment, 1)
        notes.append("included rv64Name in Lume asset compiler custom output name assignment")
    elif new_assignment in text:
        notes.append("Lume asset compiler custom output name assignment already includes rv64Name")
    else:
        notes.append("Lume asset compiler custom output name assignment insertion point not found")

    if 'rv64Name += "_rv64.o";' not in text:
        old = '        o64Name += "_64.o";\n'
        new = old + '        rv64Name += "_rv64.o";\n'
        if old in text:
            text = text.replace(old, new, 1)
            notes.append("added Lume asset compiler rv64 custom output suffix")
        else:
            notes.append("Lume asset compiler rv64 custom output suffix insertion point not found")
    else:
        notes.append("Lume asset compiler rv64 custom output suffix already present")

    rv64_write = (
        "        if (arcAndPlat & BUILD_RV64) {\n"
        "            if (!WriteElf<Elf64Bit>(EM_RISCV64, rv64Name, secName, sizeOfData, data.get())) {\n"
        "                return -1;\n"
        "            }\n"
        "        }\n"
    )
    if rv64_write not in text:
        old = (
            "        if (arcAndPlat & BUILD_V8) {\n"
            "            if (!WriteElf<Elf64Bit>(EM_AARCH64, o64Name, secName, sizeOfData, data.get())) {\n"
            "                return -1;\n"
            "            }\n"
            "        }\n"
        )
        if old in text:
            text = text.replace(old, old + rv64_write, 1)
            notes.append("added Lume asset compiler rv64 ELF object writer")
        else:
            notes.append("Lume asset compiler rv64 ELF writer insertion point not found")
    else:
        notes.append("Lume asset compiler rv64 ELF object writer already present")

    return text.encode(TEXT_ENCODING), notes


def apply_riscv64_objcopy_compat(data: bytes) -> tuple[bytes, list[str]]:
    text = data.decode(TEXT_ENCODING, errors="ignore")
    notes: list[str] = []

    if '"riscv64": "elf64-littleriscv"' not in text:
        old_output = '    "arm64": "elf64-littleaarch64",\n'
        new_output = old_output + '    "riscv64": "elf64-littleriscv",\n'
        if old_output in text:
            text = text.replace(old_output, new_output, 1)
            notes.append("added riscv64 llvm-objcopy output target mapping")
        else:
            notes.append("riscv64 objcopy output target insertion point not found")
    else:
        notes.append("riscv64 llvm-objcopy output target mapping already present")

    if '"riscv64": "riscv64"' not in text:
        old_bfd = '    "arm64": "aarch64",\n'
        new_bfd = old_bfd + '    "riscv64": "riscv64",\n'
        if old_bfd in text:
            text = text.replace(old_bfd, new_bfd, 1)
            notes.append("added riscv64 llvm-objcopy BFD architecture mapping")
        else:
            notes.append("riscv64 objcopy BFD architecture insertion point not found")
    else:
        notes.append("riscv64 llvm-objcopy BFD architecture mapping already present")

    return text.encode(TEXT_ENCODING), notes


def apply_libunwind_riscv64_los_linux_drop_compat(data: bytes) -> tuple[bytes, list[str]]:
    text = data.decode(TEXT_ENCODING, errors="ignore")
    line = '  "$libunwind_code_dir/src/riscv/Los-linux.c",\n'
    count = text.count(line)
    if not count:
        return data, ["libunwind riscv64 Los-linux.c source references already absent"]
    text = text.replace(line, "")
    return (
        text.encode(TEXT_ENCODING),
        [f"removed {count} stale libunwind riscv64 Los-linux.c source reference(s)"],
    )


def apply_ffrt_riscv64_fiber_storage_compat(data: bytes) -> tuple[bytes, list[str]]:
    text = data.decode(TEXT_ENCODING, errors="ignore")
    if "#elif defined(__riscv)" in text and "ffrt_fiber_storage_size = 64," in text:
        return data, ["FFRT riscv fiber storage-size branch already present"]
    old = "#elif defined(__x86_64__)\n    ffrt_fiber_storage_size = 8,\n"
    new = old + "#elif defined(__riscv)\n    ffrt_fiber_storage_size = 64,\n"
    if old in text:
        text = text.replace(old, new, 1)
        return text.encode(TEXT_ENCODING), ["added FFRT riscv fiber storage-size branch"]
    return data, ["FFRT riscv fiber storage-size insertion point not found"]


def apply_riscv64_compiler_ldflags_mabi_compat(data: bytes) -> tuple[bytes, list[str]]:
    text = data.decode(TEXT_ENCODING, errors="ignore")
    notes: list[str] = []
    if '"-mabi=lp64d"' in text and 'ldflags += [\n        "-march=rv64imafdc",\n        "-mabi=lp64d",' in text:
        return data, ["riscv64 linker mabi flag already present next to -march=rv64imafdc"]

    old = '      ldflags += [ "-march=rv64imafdc" ]\n'
    new = (
        "      ldflags += [\n"
        '        "-march=rv64imafdc",\n'
        '        "-mabi=lp64d",\n'
        "      ]\n"
    )
    if old in text:
        text = text.replace(old, new, 1)
        notes.append("added riscv64 -mabi=lp64d linker flag beside -march=rv64imafdc")
    else:
        notes.append("riscv64 linker mabi insertion point not found")
    return text.encode(TEXT_ENCODING), notes


def apply_riscv64_musl_cflags_mabi_compat(data: bytes) -> tuple[bytes, list[str]]:
    text = data.decode(TEXT_ENCODING, errors="ignore")
    notes: list[str] = []
    if 'musl_arch == "riscv64"' in text and 'cflags_basic += [ "-mabi=lp64d" ]' in text:
        return data, ["musl riscv64 cflags_basic already carries -mabi=lp64d"]

    anchor = (
        '  cflags_basic = [\n'
        '    "--target=${musl_target_triple}",\n'
        '    "-Wall",\n'
        '    "-Wl,-z,relro,-z,now,-z,noexecstack",\n'
        "  ]\n"
    )
    insertion = (
        anchor
        + "\n"
        + '  if (musl_arch == "riscv64") {\n'
        + '    cflags_basic += [ "-mabi=lp64d" ]\n'
        + "  }\n"
    )
    if anchor in text:
        text = text.replace(anchor, insertion, 1)
        notes.append("added musl riscv64 -mabi=lp64d to cflags_basic")
    else:
        notes.append("musl cflags_basic insertion point not found")
    return text.encode(TEXT_ENCODING), notes


def apply_riscv64_libcpp_compat(data: bytes) -> tuple[bytes, list[str]]:
    text = data.decode(TEXT_ENCODING, errors="ignore")
    notes: list[str] = []

    prebuilt_branch = (
        '  } else if (use_hwasan == false && target_cpu == "riscv64") {\n'
        '    source = "${clang_stl_path}/riscv64-linux-ohos/libc++_shared.so"\n'
    )
    if prebuilt_branch not in text:
        old = (
            '  } else if (use_hwasan == false && target_cpu == "arm64") {\n'
            '    source = "${clang_stl_path}/aarch64-linux-ohos/libc++_shared.so"\n'
            '  } else if (target_cpu == "x86_64") {'
        )
        new = (
            '  } else if (use_hwasan == false && target_cpu == "arm64") {\n'
            '    source = "${clang_stl_path}/aarch64-linux-ohos/libc++_shared.so"\n'
            f"{prebuilt_branch}"
            '  } else if (target_cpu == "x86_64") {'
        )
        if old in text:
            text = text.replace(old, new, 1)
            notes.append("added riscv64 libc++_shared.so source branch")
        else:
            notes.append("riscv64 libc++_shared.so source insertion point not found")
    else:
        notes.append("riscv64 libc++_shared.so source branch already present")

    copy_branch = (
        '  } else if (target_cpu == "riscv64") {\n'
        '    sources = [ "${clang_stl_path}/riscv64-linux-ohos/libc++_shared.so" ]\n'
    )
    if copy_branch not in text:
        old = (
            '  } else if (target_cpu == "arm64") {\n'
            '    sources = [ "${clang_stl_path}/aarch64-linux-ohos/libc++_shared.so" ]\n'
            '  } else if (target_cpu == "x86_64") {'
        )
        new = (
            '  } else if (target_cpu == "arm64") {\n'
            '    sources = [ "${clang_stl_path}/aarch64-linux-ohos/libc++_shared.so" ]\n'
            f"{copy_branch}"
            '  } else if (target_cpu == "x86_64") {'
        )
        if old in text:
            text = text.replace(old, new, 1)
            notes.append("added riscv64 libc++_shared.so unstripped-copy source branch")
        else:
            notes.append("riscv64 libc++_shared.so unstripped-copy insertion point not found")
    else:
        notes.append("riscv64 libc++_shared.so unstripped-copy source branch already present")

    return text.encode(TEXT_ENCODING), notes


def apply_riscv64_ark_llvmbackend_disable_compat(data: bytes) -> tuple[bytes, list[str]]:
    text = data.decode(TEXT_ENCODING, errors="ignore")
    if 'if (target_cpu == "riscv64")' in text and "is_llvmbackend = false" in text:
        return data, ["ArkCompiler riscv64 LLVM backend/codegen disablement already present"]

    riscv64_block = (
        'if (target_cpu == "riscv64") {\n'
        '  enable_irtoc = false\n'
        '  enable_codegen = false\n'
        '  is_llvmbackend = false\n'
        '  is_llvm_interpreter = false\n'
        '  is_llvm_fastpath = false\n'
        '  is_llvm_aot = false\n'
        '}\n\n'
    )
    insertion_marker = (
        'if (!is_llvmbackend) {\n'
        '  assert(!is_llvm_interpreter,'
    )
    if insertion_marker in text:
        text = text.replace(insertion_marker, riscv64_block + insertion_marker, 1)
        return (
            text.encode(TEXT_ENCODING),
            ["added target-evidenced ArkCompiler riscv64 LLVM backend/codegen disablement"],
        )
    return data, ["ArkCompiler riscv64 LLVM backend/codegen insertion point not found"]


def apply_riscv64_ark_target_defines_compat(data: bytes) -> tuple[bytes, list[str]]:
    text = data.decode(TEXT_ENCODING, errors="ignore")
    if 'current_cpu == "riscv64"' in text and "PANDA_TARGET_RISCV64" in text:
        return data, ["ArkCompiler riscv64 target defines already present"]

    old = (
        '  } else if (current_cpu == "x86") {\n'
        '    defines += [\n'
        '      "PANDA_TARGET_32",\n'
        '      "PANDA_TARGET_X86",\n'
        '    ]\n'
    )
    new = (
        '  } else if (current_cpu == "riscv64") {\n'
        '    defines += [\n'
        '      "PANDA_TARGET_RISCV64",\n'
        '      "PANDA_TARGET_64",\n'
        '    ]\n'
        f"{old}"
    )
    if old in text:
        text = text.replace(old, new, 1)
        return (
            text.encode(TEXT_ENCODING),
            ["added target-evidenced ArkCompiler riscv64 target defines"],
        )
    return data, ["ArkCompiler riscv64 target defines insertion point not found"]


def apply_riscv64_ark_cache_line_compat(data: bytes) -> tuple[bytes, list[str]]:
    text = data.decode(TEXT_ENCODING, errors="ignore")
    if "PANDA_TARGET_RISCV64" in text and "CACHE_LINE_SIZE = 64" in text:
        return data, ["ArkCompiler riscv64 cache-line-size condition already present"]

    old = "#if defined(PANDA_TARGET_AMD64) || defined(PANDA_TARGET_ARM64) || defined(PANDA_TARGET_ARM32)"
    new = old + " || defined(PANDA_TARGET_RISCV64)"
    if old in text:
        text = text.replace(old, new, 1)
        return (
            text.encode(TEXT_ENCODING),
            ["added target-evidenced ArkCompiler riscv64 cache-line-size condition"],
        )
    return data, ["ArkCompiler riscv64 cache-line-size insertion point not found"]


def apply_target_compile_standard_whitelist_prefix_entries(
    data: bytes,
    target_root: Path,
    prefixes: list[str],
) -> tuple[bytes, list[str]]:
    try:
        current = json.loads(data.decode(TEXT_ENCODING))
    except Exception:
        return data, ["compile-standard whitelist transform skipped: current JSON is invalid"]
    target_path = target_root / "build/compile_standard_whitelist.json"
    if not target_path.is_file():
        return data, ["compile-standard whitelist transform skipped: target whitelist not found"]
    try:
        target = json.loads(target_path.read_text(encoding=TEXT_ENCODING, errors="ignore"))
    except Exception:
        return data, ["compile-standard whitelist transform skipped: target JSON is invalid"]
    if not isinstance(current, dict) or not isinstance(target, dict):
        return data, ["compile-standard whitelist transform skipped: JSON root is not an object"]

    notes: list[str] = []
    for key, target_values in target.items():
        if not isinstance(target_values, list):
            continue
        selected = [
            value
            for value in target_values
            if isinstance(value, str) and any(value.startswith(prefix) for prefix in prefixes)
        ]
        if not selected:
            continue
        current_values = current.setdefault(key, [])
        if not isinstance(current_values, list):
            notes.append(f"skipped whitelist key {key}: current value is not a list")
            continue
        existing = {value for value in current_values if isinstance(value, str)}
        added = 0
        for value in selected:
            if value not in existing:
                current_values.append(value)
                existing.add(value)
                added += 1
        if added:
            notes.append(f"added {added} target-evidenced SoC display whitelist entries to {key}")
        else:
            notes.append(f"SoC display whitelist entries already present in {key}")

    if not notes:
        notes.append("no target-evidenced SoC display whitelist entries matched requested prefixes")
    return (json.dumps(current, ensure_ascii=False, indent=4) + "\n").encode(TEXT_ENCODING), notes


def apply_webview_bundle_app_fwk_update_migration(data: bytes) -> tuple[bytes, list[str]]:
    text = data.decode(TEXT_ENCODING, errors="ignore")
    replacements = {
        "//base/web/webview/sa:app_fwk_update_service": (
            "//base/web/webview/sa/app_fwk_update:app_fwk_update_service"
        ),
        "//base/web/webview/sa/include": "//base/web/webview/sa/app_fwk_update/include",
    }
    notes: list[str] = []
    for old, new in replacements.items():
        count = text.count(old)
        if count:
            text = text.replace(old, new)
            notes.append(f"rewrote {count} WebView bundle reference(s) from {old} to {new}")
        elif new in text:
            notes.append(f"WebView bundle reference already migrated to {new}")
        else:
            notes.append(f"WebView bundle migration source label not found: {old}")
    return text.encode(TEXT_ENCODING), notes


def item_mentions_profiler_smartperf_host(item: Any) -> bool:
    if isinstance(item, str):
        return "//developtools/profiler/host/smartperf/" in item
    if isinstance(item, dict):
        return any(item_mentions_profiler_smartperf_host(value) for value in item.values())
    if isinstance(item, list):
        return any(item_mentions_profiler_smartperf_host(value) for value in item)
    return False


def apply_profiler_smartperf_split_migration(data: bytes) -> tuple[bytes, list[str]]:
    notes: list[str] = []
    try:
        bundle = json.loads(data.decode(TEXT_ENCODING))
    except Exception:
        return data, ["profiler SmartPerf split migration skipped: bundle.json is not valid JSON"]
    component = bundle.get("component") if isinstance(bundle, dict) else None
    build = component.get("build") if isinstance(component, dict) else None
    if not isinstance(build, dict):
        return data, ["profiler SmartPerf split migration skipped: component.build missing"]

    for key in ("sub_component", "test"):
        values = build.get(key)
        if not isinstance(values, list):
            continue
        kept = [item for item in values if not item_mentions_profiler_smartperf_host(item)]
        removed = len(values) - len(kept)
        if removed:
            build[key] = kept
            notes.append(f"removed {removed} legacy profiler SmartPerf {key} label(s)")

    inner_kits = build.get("inner_kits")
    if isinstance(inner_kits, list):
        kept_inner_kits = [
            item for item in inner_kits if not item_mentions_profiler_smartperf_host(item)
        ]
        removed = len(inner_kits) - len(kept_inner_kits)
        if removed:
            build["inner_kits"] = kept_inner_kits
            notes.append(f"removed {removed} legacy profiler SmartPerf inner_kits entry/entries")

    if not notes:
        notes.append("legacy profiler SmartPerf labels already absent")
    return (json.dumps(bundle, ensure_ascii=False, indent=2) + "\n").encode(TEXT_ENCODING), notes


def apply_board_kernel_fake_output_bridge(data: bytes) -> tuple[bytes, list[str]]:
    text = data.decode(TEXT_ENCODING, errors="ignore")
    if "OPENHARMONY_PORTING_FAKE_KERNEL_MARKER" in text:
        return data, ["board kernel fake-output bridge already present"]

    marker_export = (
        'export PRODUCT_PATH=vendor/${DEVICE_BOARD}/${DEVICE_NAME}\n'
        'export OPENHARMONY_PORTING_FAKE_KERNEL_MARKER="${KERNEL_SOURCE_DIR}/.openharmony_porting_fake_kernel_source"\n'
    )
    if 'export PRODUCT_PATH=vendor/${DEVICE_BOARD}/${DEVICE_NAME}\n' not in text:
        return data, ["board kernel fake-output bridge insertion point not found: PRODUCT_PATH export"]
    text = text.replace('export PRODUCT_PATH=vendor/${DEVICE_BOARD}/${DEVICE_NAME}\n', marker_export, 1)

    fake_function = r'''
function make_fake_kernel_outputs(){
    echo "openharmony_porting: synthesizing compile-only fake kernel outputs for ${KERNEL_SOURCE_DIR}"
    rm -rf "${KERNEL_BUILD_ROOT}"
    mkdir -p "${KERNEL_BUILD_ROOT}/arch/riscv/boot/dts/thead"
    mkdir -p "${KERNEL_BUILD_ROOT}/drivers/media/common/videobuf2"
    mkdir -p "${KERNEL_BUILD_ROOT}/drivers/media/usb/uvc"
    mkdir -p "${KERNEL_BUILD_ROOT}/drivers/gpu-viv"
    printf 'FAKE_OPENHARMONY_PORTING_INTERFACE=1\nmissing_dependency=%s\nscope=compile_only\nruntime_status=not_functional\n' "${KERNEL_SOURCE_DIR}" > "${KERNEL_BUILD_ROOT}/arch/riscv/boot/Image"
    printf 'FAKE_OPENHARMONY_PORTING_INTERFACE=1\nmissing_dependency=%s\nscope=compile_only\nruntime_status=not_functional\n' "${KERNEL_SOURCE_DIR}/${KERNEL_DTB}" > "${KERNEL_BUILD_ROOT}/arch/riscv/boot/dts/thead/${KERNEL_DTB}"
    printf 'FAKE_OPENHARMONY_PORTING_INTERFACE=1\nmissing_dependency=videobuf2-vmalloc.ko\nscope=compile_only\nruntime_status=not_functional\n' > "${KERNEL_BUILD_ROOT}/drivers/media/common/videobuf2/videobuf2-vmalloc.ko"
    printf 'FAKE_OPENHARMONY_PORTING_INTERFACE=1\nmissing_dependency=uvcvideo.ko\nscope=compile_only\nruntime_status=not_functional\n' > "${KERNEL_BUILD_ROOT}/drivers/media/usb/uvc/uvcvideo.ko"
    printf 'FAKE_OPENHARMONY_PORTING_INTERFACE=1\nmissing_dependency=galcore.ko\nscope=compile_only\nruntime_status=not_functional\n' > "${KERNEL_BUILD_ROOT}/drivers/gpu-viv/galcore.ko"
    mkdir -p "${OHOS_IMAGES_DIR}"
    cp "${KERNEL_BUILD_ROOT}/arch/riscv/boot/Image" "${OHOS_IMAGES_DIR}/Image"
    cp "${KERNEL_BUILD_ROOT}/arch/riscv/boot/dts/thead/${KERNEL_DTB}" "${OHOS_IMAGES_DIR}/${KERNEL_DTB}"
    cp_ko
    make_boot
}

'''
    if "function copy_kernel(){" not in text:
        return data, ["board kernel fake-output bridge insertion point not found: copy_kernel function"]
    text = text.replace("function copy_kernel(){\n", fake_function + "function copy_kernel(){\n", 1)

    fake_dispatch = (
        'if [ -f "${OPENHARMONY_PORTING_FAKE_KERNEL_MARKER}" ]; then\n'
        '    make_fake_kernel_outputs\n'
        '    popd\n'
        '    exit 0\n'
        'fi\n\n'
    )
    if 'if [ ! -f "${OHOS_IMAGES_DIR}/Image" ]; then' not in text:
        return data, ["board kernel fake-output bridge insertion point not found: Image guard"]
    text = text.replace(
        'if [ ! -f "${OHOS_IMAGES_DIR}/Image" ]; then',
        fake_dispatch + 'if [ ! -f "${OHOS_IMAGES_DIR}/Image" ]; then',
        1,
    )
    return text.encode(TEXT_ENCODING), ["added compile-only fake-output branch to board kernel build script"]


def apply_component_feature_compat(data: bytes, features_to_add: list[str]) -> tuple[bytes, list[str]]:
    notes: list[str] = []
    try:
        bundle = json.loads(data.decode(TEXT_ENCODING))
    except Exception:
        return data, ["component feature transform skipped: bundle.json is not valid JSON"]
    if not isinstance(bundle, dict):
        return data, ["component feature transform skipped: bundle root is not an object"]
    component = bundle.get("component")
    if not isinstance(component, dict):
        return data, ["component feature transform skipped: missing component object"]
    features = component.setdefault("features", [])
    if not isinstance(features, list):
        return data, ["component feature transform skipped: component.features is not a list"]
    changed = False
    for feature in features_to_add:
        if feature not in features:
            features.append(feature)
            notes.append(f"added component feature declaration {feature}")
            changed = True
    if not changed:
        notes.append("component feature declarations already present")
    return (json.dumps(bundle, ensure_ascii=False, indent=4) + "\n").encode(TEXT_ENCODING), notes


def materialize_action(
    action: dict[str, Any],
    workspace: Path,
    target_root: Path,
    target: dict[str, str],
    normalize_subsystems: bool,
    component_features: dict[str, set[str] | None] | None,
    component_deferrals: dict[str, dict[str, Any]] | None,
) -> tuple[bytes | None, str, str, list[str]]:
    rel_path = clean_str(action.get("path"), "")
    if action.get("content_source") == "generated_fake_interface":
        content = clean_str(action.get("generated_text"), "")
        return content.encode(TEXT_ENCODING), "generated_fake_interface", "available", [
            "generated compile-only fake interface; runtime implementation is intentionally absent"
        ]
    if action.get("content_source") == "workspace_fake_binary_from_existing":
        source_path = workspace / clean_str(action.get("source_path"), "")
        if not source_path.is_file():
            return None, str(source_path), "missing_workspace_source", []
        return source_path.read_bytes(), str(source_path), "available", [
            "copied existing workspace binary as compile-only wrong-architecture placeholder"
        ]
    if action.get("content_source") == "generated_from_target_vendor_config":
        config, removed = filter_unavailable_product_components(
            action["generated_json"],
            component_features,
            component_deferrals,
        )
        notes = []
        if removed:
            notes.append("filtered unavailable components/features from generated productdefine: " + ", ".join(removed))
        return productdefine_bytes(config), "generated", "available", notes
    if action.get("content_source") == "target_source_transform":
        source_path = target_root / clean_str(action.get("source_path"), "")
        if not source_path.is_file():
            return None, str(source_path), "missing_source", []
        data = source_path.read_bytes()
        transforms: list[str] = []
        if action.get("source_role") == "board_kernel_fake_output_bridge":
            data, transforms = apply_board_kernel_fake_output_bridge(data)
        return data, str(source_path), "available", transforms
    if action.get("content_source") == "workspace_transform":
        source_path = workspace / rel_path
        if not source_path.is_file():
            return None, str(source_path), "missing_workspace_source", []
        data = source_path.read_bytes()
        transforms: list[str] = []
        if rel_path == "build/ohos/ndk/ndk.gni" and target.get("architecture") == "riscv64":
            data, transforms = apply_riscv64_ndk_compat(data)
        elif rel_path == "third_party/curl/BUILD.gn" and target.get("architecture") == "riscv64":
            data, transforms = apply_riscv64_curl_compat(data)
        elif rel_path == "build/common/libcpp/BUILD.gn" and target.get("architecture") == "riscv64":
            data, transforms = apply_riscv64_libcpp_compat(data)
        elif (
            rel_path == "arkcompiler/runtime_core/static_core/ark_config.gni"
            and target.get("architecture") == "riscv64"
        ):
            data, transforms = apply_riscv64_ark_llvmbackend_disable_compat(data)
        elif (
            rel_path == "arkcompiler/runtime_core/static_core/BUILD.gn"
            and action.get("source_role") == "arkcompiler_riscv64_target_defines"
            and target.get("architecture") == "riscv64"
        ):
            data, transforms = apply_riscv64_ark_target_defines_compat(data)
        elif (
            rel_path == "arkcompiler/runtime_core/static_core/libpandabase/cpu_features.h"
            and action.get("source_role") == "arkcompiler_riscv64_cache_line_size"
            and target.get("architecture") == "riscv64"
        ):
            data, transforms = apply_riscv64_ark_cache_line_compat(data)
        elif (
            rel_path == "build/compile_standard_whitelist.json"
            and action.get("source_role") == "soc_display_compile_standard_whitelist_entries"
        ):
            prefix = f"//device/soc/{clean_str(target.get('soc_vendor'))}/{clean_str(target.get('soc'))}/hardware/display"
            data, transforms = apply_target_compile_standard_whitelist_prefix_entries(data, target_root, [prefix])
        elif (
            rel_path == "base/web/webview/bundle.json"
            and action.get("source_role") == "webview_bundle_app_fwk_update_sa_migration"
        ):
            data, transforms = apply_webview_bundle_app_fwk_update_migration(data)
        elif (
            rel_path == "developtools/profiler/bundle.json"
            and action.get("source_role") == "profiler_smartperf_split_bundle_migration"
        ):
            data, transforms = apply_profiler_smartperf_split_migration(data)
        elif (
            action.get("source_role") == "graphic_3d_riscv64_rofs_build_rule"
            and target.get("architecture") == "riscv64"
        ):
            data, transforms = apply_riscv64_graphic_3d_rofs_compat(data)
        elif (
            rel_path == "foundation/graphic/graphic_3d/lume/lume_config.gni"
            and action.get("source_role") == "lume_rofs_riscv64_cpu_type_compat"
            and target.get("architecture") == "riscv64"
        ):
            data, transforms = apply_lume_rofs_riscv64_cpu_type_compat(data)
        elif (
            rel_path == "foundation/graphic/graphic_3d/lume/LumeBinaryCompile/lumeassetcompiler/BUILD.gn"
            and action.get("source_role") == "lume_asset_compiler_declared_inputs"
            and target.get("architecture") == "riscv64"
        ):
            data, transforms = apply_lume_asset_compiler_declared_inputs(data)
        elif (
            rel_path == "foundation/graphic/graphic_3d/lume/LumeBinaryCompile/lumeassetcompiler/src/elf_common.h"
            and action.get("source_role") == "lume_asset_compiler_riscv64_elf_machine"
            and target.get("architecture") == "riscv64"
        ):
            data, transforms = apply_lume_asset_compiler_riscv64_elf_machine(data)
        elif (
            rel_path == "foundation/graphic/graphic_3d/lume/LumeBinaryCompile/lumeassetcompiler/src/app.cpp"
            and action.get("source_role") == "lume_asset_compiler_riscv64_platform"
            and target.get("architecture") == "riscv64"
        ):
            data, transforms = apply_lume_asset_compiler_riscv64_platform(data)
        elif (
            rel_path == "build/scripts/run_objcopy.py"
            and target.get("architecture") == "riscv64"
        ):
            data, transforms = apply_riscv64_objcopy_compat(data)
        elif (
            rel_path == "third_party/libunwind/BUILD.gn"
            and action.get("source_role") == "libunwind_riscv64_drop_missing_los_linux"
            and target.get("architecture") == "riscv64"
        ):
            data, transforms = apply_libunwind_riscv64_los_linux_drop_compat(data)
        elif (
            rel_path == "foundation/resourceschedule/ffrt/interfaces/kits/c/type_def.h"
            and action.get("source_role") == "ffrt_riscv64_fiber_storage_size"
            and target.get("architecture") == "riscv64"
        ):
            data, transforms = apply_ffrt_riscv64_fiber_storage_compat(data)
        elif (
            rel_path == "foundation/arkui/ace_engine/build/tools/run_objcopy.py"
            and action.get("source_role") == "arkui_run_objcopy_riscv64_compat"
            and target.get("architecture") == "riscv64"
        ):
            data, transforms = apply_riscv64_objcopy_compat(data)
        elif (
            rel_path == "build/config/compiler/BUILD.gn"
            and action.get("source_role") == "riscv64_compiler_ldflags_mabi_compat"
            and target.get("architecture") == "riscv64"
        ):
            data, transforms = apply_riscv64_compiler_ldflags_mabi_compat(data)
        elif (
            rel_path == "build/config/components/musl/BUILD.gn"
            and action.get("source_role") == "riscv64_musl_cflags_mabi_compat"
            and target.get("architecture") == "riscv64"
        ):
            data, transforms = apply_riscv64_musl_cflags_mabi_compat(data)
        elif rel_path in {"build/rust/BUILD.gn", "build/rust/tests/BUILD.gn"} and target.get("architecture") == "riscv64":
            source_path = target_root / rel_path
            if source_path.is_file():
                data = source_path.read_bytes()
                transforms = [f"replaced {rel_path} with target-evidenced riscv64 Rust prebuilt source rules"]
            else:
                transforms = [f"target {rel_path} evidence missing; no transform applied"]
        elif action.get("add_component_features"):
            data, transforms = apply_component_feature_compat(
                data,
                [clean_str(feature, "") for feature in action.get("add_component_features") or [] if clean_str(feature, "")],
            )
        return data, str(source_path), "available", transforms
    source_path = target_root / clean_str(action.get("source_path"), "")
    if not source_path.is_file():
        return None, "target_source_root", "missing_source", []
    data = source_path.read_bytes()
    transforms: list[str] = []
    vendor_config_rel = f"vendor/{target['vendor']}/{target['product']}/config.json"
    if rel_path == vendor_config_rel:
        try:
            config = json.loads(data.decode(TEXT_ENCODING))
        except Exception:
            config = None
        if isinstance(config, dict):
            config, removed = filter_unavailable_product_components(config, component_features, component_deferrals)
            if removed:
                transforms.append("filtered unavailable components/features from vendor config: " + ", ".join(removed))
                data = (json.dumps(config, ensure_ascii=False, indent=2) + "\n").encode(TEXT_ENCODING)
    if rel_path.startswith("productdefine/common/inherit/") and rel_path.endswith(".json"):
        try:
            config = json.loads(data.decode(TEXT_ENCODING))
        except Exception:
            config = None
        if isinstance(config, dict):
            config, removed = filter_unavailable_product_components(config, component_features, component_deferrals)
            if removed:
                transforms.append("filtered unavailable components/features from product inheritance: " + ", ".join(removed))
                data = (json.dumps(config, ensure_ascii=False, indent=2) + "\n").encode(TEXT_ENCODING)
    data, subsystem_transforms = normalize_ohos_build_subsystem(data, action, target, normalize_subsystems)
    transforms.extend(subsystem_transforms)
    return data, str(source_path), "available", transforms


def render_markdown(manifest: dict[str, Any]) -> str:
    summary = manifest["summary"]
    lines = [
        "# Porting Base Patch Manifest",
        "",
        f"- Generated: `{manifest['generated_at']}`",
        f"- Workspace: `{manifest['workspace']}`",
        f"- Target source root: `{manifest['target_source_root']}`",
        f"- Apply requested: `{manifest['apply_requested']}`",
        f"- Attempt build: `{manifest['attempt_build']}`",
        f"- Planned actions: {summary['planned_actions']}",
        f"- Applied actions: {summary['applied_actions']}",
        f"- Skipped same-content actions: {summary['skipped_same_content_actions']}",
        f"- Blocking issues: {summary['blocking_issue_count']}",
        f"- Fake interfaces: {summary.get('fake_interface_count', 0)}",
        f"- Prebuild cleanups: {summary.get('prebuild_cleanup_count', 0)}",
        "",
        "## Actions",
        "",
    ]
    for action in manifest["actions"]:
        lines.extend(
            [
                f"### {action['path']}",
                "",
                f"- Phase: `{action['phase']}`",
                f"- Role: `{action['source_role']}`",
                f"- Source: `{action['content_source']}` / `{action.get('source_path', 'unknown')}`",
                f"- Workspace status: `{action['workspace_status']}`",
                f"- Apply status: `{action['apply_status']}`",
                f"- Staged path: `{action.get('staged_path', 'unknown')}`",
                f"- Compatibility transforms: `{'; '.join(action.get('compatibility_transforms') or []) or 'none'}`",
                "",
            ]
        )
    if manifest.get("build_result"):
        build = manifest["build_result"]
        lines.extend(
            [
                "## Build Attempt",
                "",
                f"- Command: `{build['command']}`",
                f"- Return code: `{build['return_code']}`",
                f"- Timed out: `{build['timed_out']}`",
                f"- Log: `{build['log_path']}`",
                f"- Host env fix: `{(build.get('host_env_fix') or {}).get('reason', 'none')}`",
                "",
            ]
        )
        cleanups = build.get("prebuild_cleanups") or []
        if cleanups:
            lines.extend(["### Prebuild Cleanups", ""])
            for cleanup in cleanups:
                lines.append(f"- `{cleanup.get('status', 'unknown')}` `{cleanup.get('path', 'unknown')}`: {cleanup.get('reason', 'no reason recorded')}")
            lines.append("")
        diagnostics = build.get("diagnostics") or []
        if diagnostics:
            lines.extend(["### Build Diagnostics", ""])
            for diag in diagnostics:
                lines.extend(
                    [
                        f"- `{diag['id']}` ({diag['classification']}): {diag['summary']}",
                        f"  - Suggested next action: {diag['suggested_next_action']}",
                    ]
                )
            lines.append("")
    if manifest["blocking_issues"]:
        lines.extend(["## Blocking Issues", ""])
        for issue in manifest["blocking_issues"]:
            lines.append(f"- `{issue['path']}`: {issue['reason']}")
        lines.append("")
    fake_interfaces = manifest.get("fake_interfaces") or []
    if fake_interfaces:
        lines.extend(["## Fake Interfaces", ""])
        for item in fake_interfaces:
            lines.extend(
                [
                    f"- `{item.get('path', 'unknown')}`: {item.get('missing_dependency', 'unknown dependency')}",
                    f"  - Scope: `{item.get('scope', 'unknown')}`",
                    f"  - Runtime status: `{item.get('runtime_status', 'unknown')}`",
                    f"  - Provenance path: `{item.get('provenance_path', 'unknown')}`",
                    f"  - Follow-up: {item.get('follow_up', 'replace with real dependency')}",
                ]
            )
        lines.append("")
    deferrals = manifest.get("external_prebuilt_deferrals") or []
    if deferrals:
        lines.extend(["## External Prebuilt Deferrals", ""])
        for item in deferrals:
            lines.extend(
                [
                    f"- `{item.get('subsystem', 'unknown')}:{item.get('component', 'unknown')}`: {item.get('reason', 'external dependency')}",
                    f"  - Target prebuilt: `{item.get('target_prebuilt_path', 'unknown')}`",
                    f"  - Workspace prebuilt exists: `{item.get('workspace_prebuilt_exists', 'unknown')}`",
                    f"  - Target is Git LFS pointer: `{item.get('target_prebuilt_is_git_lfs_pointer', 'unknown')}`",
                ]
            )
        lines.append("")
    lines.extend(["## Notes", ""])
    for note in manifest.get("notes", []):
        lines.append(f"- {note}")
    return "\n".join(lines).rstrip() + "\n"


ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


def read_text_sample(path: Path, limit_bytes: int = 240_000) -> str:
    if not path.is_file():
        return ""
    data = path.read_bytes()
    if len(data) > limit_bytes:
        data = data[-limit_bytes:]
    return data.decode(TEXT_ENCODING, errors="ignore")


def strip_ansi(text: str) -> str:
    return ANSI_RE.sub("", text)


def matching_lines(text: str, needles: list[str], limit: int = 8) -> list[str]:
    matches = []
    lowered_needles = [needle.lower() for needle in needles]
    for line in strip_ansi(text).splitlines():
        lowered = line.lower()
        if any(needle in lowered for needle in lowered_needles):
            matches.append(line.strip())
            if len(matches) >= limit:
                break
    return matches


def normalize_ninja_source_path(path: str, workspace: Path) -> str:
    rel = path.strip().strip("'\"").replace("\\", "/")
    workspace_prefix = str(workspace).replace("\\", "/").rstrip("/") + "/"
    if rel.startswith(workspace_prefix):
        rel = rel[len(workspace_prefix) :]
    while rel.startswith("../"):
        rel = rel[3:]
    if rel.startswith("./"):
        rel = rel[2:]
    try:
        return normalize_rel(rel)
    except ValueError:
        return rel


GN_IDENTIFIER_KEYWORDS = {
    "if",
    "else",
    "foreach",
    "defined",
    "true",
    "false",
}


def clean_prefixed_gn_line(line: str) -> str:
    text = re.sub(r"^\s*\[[^\]]+\]\s*\[GN\]\s*", "", line)
    return re.sub(r"^\s*\[[^\]]+\]\s*", "", text).strip()


def collect_undefined_identifier_matches(text: str) -> list[tuple[str, str]]:
    matches: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    lines = strip_ansi(text).splitlines()
    for index, line in enumerate(lines):
        path_match = re.search(r"ERROR at //([^:\n]+):\d+:\d+: Undefined identifier", line)
        if not path_match:
            continue
        gn_path = path_match.group(1)
        identifier = ""
        for context_line in lines[index + 1 : index + 8]:
            clean_line = clean_prefixed_gn_line(context_line)
            if (
                not clean_line
                or clean_line.startswith("^")
                or clean_line.startswith("See ")
                or clean_line.startswith("ERROR at ")
            ):
                continue
            for token in re.findall(r"\b[A-Za-z_][A-Za-z0-9_]*\b", clean_line):
                if token not in GN_IDENTIFIER_KEYWORDS:
                    identifier = token
                    break
            if identifier:
                break
        if not identifier:
            continue
        key = (gn_path, identifier)
        if key in seen:
            continue
        seen.add(key)
        matches.append(key)
    return matches


def collect_gn_assertion_matches(text: str) -> list[tuple[str, list[str]]]:
    matches: list[tuple[str, list[str]]] = []
    seen: set[str] = set()
    lines = strip_ansi(text).splitlines()
    for index, line in enumerate(lines):
        path_match = re.search(r"ERROR at //([^:\n]+):\d+:\d+: Assertion failed", line)
        if not path_match:
            continue
        gn_path = path_match.group(1)
        if gn_path in seen:
            continue
        context: list[str] = []
        for context_line in lines[index + 1 : index + 8]:
            clean_line = clean_prefixed_gn_line(context_line)
            if not clean_line or clean_line.startswith("^") or clean_line.startswith("See "):
                continue
            context.append(clean_line)
            if len(context) >= 3:
                break
        seen.add(gn_path)
        matches.append((gn_path, context))
    return matches


def collect_duplicate_output_blocks(text: str) -> list[list[str]]:
    blocks: list[list[str]] = []
    lines = strip_ansi(text).splitlines()
    for index, line in enumerate(lines):
        if "Duplicate output file" not in line:
            continue
        block: list[str] = []
        for context_line in lines[index : index + 24]:
            clean_line = clean_prefixed_gn_line(context_line)
            if clean_line:
                block.append(clean_line)
        if block and block not in blocks:
            blocks.append(block)
    return blocks


def build_diagnostic(
    diag_id: str,
    classification: str,
    summary: str,
    suggested_next_action: str,
    evidence_paths: list[str],
    evidence_lines: list[str],
    severity: str = "blocking",
) -> dict[str, Any]:
    return {
        "id": diag_id,
        "severity": severity,
        "classification": classification,
        "summary": summary,
        "suggested_next_action": suggested_next_action,
        "evidence_paths": evidence_paths,
        "evidence_lines": evidence_lines,
    }


def parse_build_diagnostics(
    build_result: dict[str, Any],
    workspace: Path,
    target_root: Path,
    product: str,
    target: dict[str, str],
) -> list[dict[str, Any]]:
    log_path = Path(clean_str(build_result.get("log_path"), ""))
    candidate_logs = [
        log_path,
        workspace / "out" / product / "error.log",
        workspace / "out" / product / "build.log",
        workspace / "out" / "sdk" / "error.log",
    ]
    texts: list[tuple[Path, str]] = []
    started_at_epoch = float(build_result.get("started_at_epoch") or 0)
    for path in candidate_logs:
        if path != log_path and started_at_epoch:
            try:
                if path.stat().st_mtime < started_at_epoch - 2:
                    continue
            except FileNotFoundError:
                continue
        text = read_text_sample(path)
        if text:
            texts.append((path, text))
    all_text = "\n".join(text for _, text in texts)
    plain_text = strip_ansi(all_text)
    diagnostics: list[dict[str, Any]] = []

    if "'cstdlib' file not found" in plain_text:
        evidence_paths = [str(path) for path, text in texts if "'cstdlib' file not found" in strip_ansi(text)]
        diagnostics.append(
            build_diagnostic(
                "host_sdk_cxx_stdlib_header_missing",
                "host_or_prebuilt_toolchain",
                "The SDK/host clang_x64 stage cannot find the C++ standard header <cstdlib>.",
                "Repair or provision the host/prebuilt C++ standard library before treating this as a target-source porting failure.",
                evidence_paths,
                matching_lines(all_text, ["cstdlib", "ResourceLimits.cpp"], 6),
            )
        )

    if (
        clean_str(target.get("architecture")) == "riscv64"
        and ("/usr/include/c++/" in plain_text or "/usr/include/x86_64-linux-gnu/c++/" in plain_text)
        and ("riscv64-linux-ohos" in plain_text or "libcxx-ohos/include/c++/v1" in plain_text)
        and (
            "__locale_t" in plain_text
            or "_ISupper" in plain_text
            or "bits/std_abs.h" in plain_text
            or "integral_constant' is ambiguous" in plain_text
        )
    ):
        evidence_paths = [
            str(path)
            for path, text in texts
            if "/usr/include/c++/" in strip_ansi(text) or "/usr/include/x86_64-linux-gnu/c++/" in strip_ansi(text)
        ]
        diagnostics.append(
            build_diagnostic(
                "host_cxx_include_path_pollutes_target_riscv64",
                "host_or_prebuilt_toolchain_env_scope",
                "Host GCC C++ headers are being mixed into riscv64 target C++ compilation alongside musl/libcxx-ohos headers.",
                "Do not export host CPLUS_INCLUDE_PATH globally for the product build; keep any host C++ include repair scoped to host-tool probes or host-only actions, and export only validated link paths such as LIBRARY_PATH.",
                evidence_paths or [str(log_path)],
                matching_lines(
                    all_text,
                    [
                        "/usr/include/c++/",
                        "/usr/include/x86_64-linux-gnu/c++/",
                        "riscv64-linux-ohos",
                        "libcxx-ohos/include/c++/v1",
                        "__locale_t",
                        "_ISupper",
                        "bits/std_abs.h",
                    ],
                    14,
                ),
            )
        )

    if (
        'assert(defined(_ndk_shlib_directory))' in plain_text
        and clean_str(target.get("architecture")) == "riscv64"
    ):
        evidence_paths = [str(path) for path, text in texts if "assert(defined(_ndk_shlib_directory))" in strip_ansi(text)]
        diagnostics.append(
            build_diagnostic(
                "riscv64_ndk_shlib_directory_mapping",
                "source_build_compatibility",
                "GN evaluates an ohos_ndk_library for riscv64 but the current build file lacks the riscv64 NDK shlib directory mapping.",
                "Apply the evidence-backed build/ohos/ndk/ndk.gni riscv64 compatibility patch and rerun the product build.",
                evidence_paths,
                matching_lines(all_text, ["_ndk_shlib_directory", "ohos_ndk_library", "unsupported cpu riscv64"], 8),
            )
        )

    if (
        "ERROR at //third_party/curl/BUILD.gn" in plain_text
        and "Undefined identifier" in plain_text
        and "cflags +=" in plain_text
        and clean_str(target.get("architecture")) == "riscv64"
    ):
        evidence_paths = [str(path) for path, text in texts if "ERROR at //third_party/curl/BUILD.gn" in strip_ansi(text)]
        diagnostics.append(
            build_diagnostic(
                "riscv64_curl_cflags_guard_missing",
                "source_build_compatibility",
                "GN reaches third_party/curl for riscv64 but the standard cflags branch does not include riscv64, leaving cflags undefined.",
                "Apply the evidence-backed third_party/curl/BUILD.gn riscv64 cflags guard patch and rerun the product build.",
                evidence_paths,
                matching_lines(all_text, ["third_party/curl/BUILD.gn", "Undefined identifier", "cflags +="], 8),
            )
        )

    undefined_identifier_matches = collect_undefined_identifier_matches(plain_text)
    for gn_path, identifier in undefined_identifier_matches[:8]:
        if gn_path == "third_party/curl/BUILD.gn":
            continue
        if (
            gn_path == "base/web/webview/ohos_nweb/BUILD.gn"
            and identifier == "defines"
            and clean_str(target.get("architecture")) == "riscv64"
        ):
            prebuilt_rel = "base/web/webview/ohos_nweb/prebuilts/riscv64/ArkWebCore.hap"
            target_prebuilt = target_root / prebuilt_rel
            prebuilt_note = "target reference prebuilt not found"
            if target_prebuilt.is_file():
                target_text = read_text_sample(target_prebuilt, 2048)
                if target_text.startswith("version https://git-lfs.github.com/spec/v1"):
                    prebuilt_note = f"target reference uses Git LFS pointer for {prebuilt_rel}"
                else:
                    prebuilt_note = f"target reference contains {prebuilt_rel}"
            diagnostics.append(
                build_diagnostic(
                    "riscv64_webview_prebuilt_dependency",
                    "external_prebuilt_dependency",
                    "WebView lacks a riscv64 initialization branch in the current workspace; the reference branch points at a riscv64 ArkWebCore HAP prebuilt.",
                    "Keep webview visible in product config; import the evidenced text build rule and use a marked compile-only fake ArkWebCore HAP until the real vendor/third-party dependency is provenance-checked.",
                    [str(log_path), str(target_prebuilt)],
                    matching_lines(all_text, ["base/web/webview/ohos_nweb/BUILD.gn", "Undefined identifier", "defines +="], 8)
                    + [prebuilt_note],
                )
            )
        else:
            diagnostics.append(
                build_diagnostic(
                    "gn_undefined_identifier",
                    "source_build_compatibility",
                    f"GN reports undefined identifier {identifier} in {gn_path}.",
                    "Compare the current workspace file with the reference target source and decide whether this is a safe text compatibility patch or requires a tracked fake interface for a missing dependency.",
                    [str(log_path)],
                    matching_lines(all_text, [gn_path, "Undefined identifier", identifier], 8),
                )
            )

    for gn_path, context in collect_gn_assertion_matches(plain_text)[:8]:
        context_text = " ".join(context)
        if (
            gn_path == "arkcompiler/runtime_core/static_core/libllvmbackend/BUILD.gn"
            and "target_cpu" in context_text
            and clean_str(target.get("architecture")) == "riscv64"
        ):
            diagnostics.append(
                build_diagnostic(
                    "riscv64_arkcompiler_llvmbackend_disable_missing",
                    "source_build_compatibility",
                    "ArkCompiler libllvmbackend asserts the target CPU set before riscv64 can pass GN generation.",
                    "Apply the target-evidenced ark_config.gni riscv64 rule that disables LLVM backend/irtoc/codegen for riscv64 and rerun the product build.",
                    [str(log_path), str(target_root / "arkcompiler/runtime_core/static_core/ark_config.gni")],
                    matching_lines(all_text, ["libllvmbackend/BUILD.gn", "Assertion failed", "target_cpu"], 8),
                )
            )
        else:
            diagnostics.append(
                build_diagnostic(
                    "gn_assertion_failed",
                    "source_build_compatibility",
                    f"GN assertion failed in {gn_path}.",
                    "Compare the assertion and surrounding build arguments with the reference target source before applying a scoped compatibility patch.",
                    [str(log_path)],
                    matching_lines(all_text, [gn_path, "Assertion failed"], 8),
                )
            )

    if (
        clean_str(target.get("architecture")) == "riscv64"
        and "Undefined cacheline size" in plain_text
        and "arkcompiler/runtime_core/static_core/libpandabase/cpu_features.h" in plain_text
    ):
        diagnostics.append(
            build_diagnostic(
                "riscv64_arkcompiler_cache_line_size_missing",
                "source_build_compatibility",
                "ArkCompiler static_core is compiling for riscv64 without a defined PANDA_TARGET_RISCV64 cache-line-size path.",
                "Apply the target-evidenced static_core riscv64 target defines and cpu_features cache-line-size condition, then rerun the compile flow.",
                [
                    str(log_path),
                    str(target_root / "arkcompiler/runtime_core/static_core/BUILD.gn"),
                    str(target_root / "arkcompiler/runtime_core/static_core/libarkbase/cpu_features.h"),
                ],
                matching_lines(
                    all_text,
                    [
                        "Undefined cacheline size",
                        "libpandabase/cpu_features.h",
                        "PANDA_TARGET_RISCV64",
                        "static_assert(CACHE_LINE_SIZE",
                    ],
                    12,
                ),
            )
        )

    for block in collect_duplicate_output_blocks(plain_text)[:8]:
        block_text = "\n".join(block)
        if (
            "web/webview/libapp_fwk_update_service.z.so" in block_text
            and "//base/web/webview/sa:app_fwk_update_service" in block_text
            and "//base/web/webview/sa/app_fwk_update:app_fwk_update_service" in block_text
        ):
            diagnostics.append(
                build_diagnostic(
                    "webview_app_fwk_update_duplicate_output",
                    "source_build_compatibility",
                    "WebView builds both old flat sa app_fwk_update_service and the target sa/app_fwk_update service, producing the same shared library.",
                    "Migrate base/web/webview/bundle.json and WebView app_fwk_update test labels to the target-evidenced sa/app_fwk_update module and rerun GN generation.",
                    [str(log_path), str(target_root / "base/web/webview/bundle.json")],
                    matching_lines(
                        all_text,
                        [
                            "Duplicate output file",
                            "libapp_fwk_update_service.z.so",
                            "//base/web/webview/sa:app_fwk_update_service",
                            "//base/web/webview/sa/app_fwk_update:app_fwk_update_service",
                        ],
                        12,
                    ),
                )
            )
        elif (
            "tests/fuzztest/hiprofiler/hiprofiler/SpDaemonFuzzTest" in block_text
            and "//developtools/profiler/host/smartperf/client/client_command/test/fuzztest/spdaemon_fuzzer:SpDaemonFuzzTest" in block_text
            and "//developtools/smartperf_host/smartperf_device/device_command/test/fuzztest/spdaemon_fuzzer:SpDaemonFuzzTest" in block_text
        ):
            diagnostics.append(
                build_diagnostic(
                    "smartperf_spdaemon_fuzzer_duplicate_output",
                    "source_build_compatibility",
                    "Both legacy hiprofiler-hosted SmartPerf and smartperf_host build the SpDaemonFuzzTest target.",
                    "Apply the target-evidenced SmartPerf split by removing legacy developtools/profiler/host/smartperf labels from hiprofiler's bundle registry.",
                    [str(log_path), str(target_root / "developtools/profiler/bundle.json")],
                    matching_lines(
                        all_text,
                        [
                            "Duplicate output file",
                            "SpDaemonFuzzTest",
                            "//developtools/profiler/host/smartperf/client/client_command/test/fuzztest/spdaemon_fuzzer",
                            "//developtools/smartperf_host/smartperf_device/device_command/test/fuzztest/spdaemon_fuzzer",
                        ],
                        12,
                    ),
                )
            )
        else:
            diagnostics.append(
                build_diagnostic(
                    "gn_duplicate_output_file",
                    "source_build_compatibility",
                    "GN reports duplicate output files.",
                    "Inspect the colliding targets and migrate or rename the stale target according to target-source evidence.",
                    [str(log_path)],
                    matching_lines(all_text, ["Duplicate output file", "Collisions:"], 12),
                )
            )

    missing_build_gn = sorted(set(re.findall(r"Unable to load \"([^\"]*BUILD\.gn)\"", plain_text)))
    for rel in missing_build_gn[:8]:
        diagnostics.append(
            build_diagnostic(
                "missing_build_gn",
                "source_import_follow_up",
                f"GN could not load {rel}.",
                "Import the corresponding reviewed text-only BUILD.gn closure if it belongs to the target board/vendor/SoC source set.",
                [str(log_path)],
                [rel],
            )
        )

    ninja_missing_sources = sorted(
        set(
            (
                normalize_ninja_source_path(source_path, workspace),
                needed_by.strip(),
                source_path.strip(),
            )
            for source_path, needed_by in re.findall(
                r"ninja: error: '([^']+)', needed by '([^']+)', missing and no known rule to make it",
                plain_text,
            )
        )
    )
    for missing_rel, needed_by, raw_source_path in ninja_missing_sources[:12]:
        evidence_lines = matching_lines(all_text, ["ninja: error", raw_source_path, needed_by], 8)
        evidence_lines.extend(
            [
                f"normalized_missing_source={missing_rel}",
                f"needed_by={needed_by}",
            ]
        )
        if "/audio_alsa/" in f"/{missing_rel}/":
            diagnostics.append(
                build_diagnostic(
                    "board_audio_alsa_source_missing",
                    "source_import_follow_up",
                    f"Ninja needs board audio_alsa source {missing_rel}, but it is not present in the current workspace.",
                    "Import the target-evidenced board audio_alsa text/source closure and rerun the compile flow; keep non-text audio payloads as tracked fake interfaces if encountered.",
                    [str(log_path), str(target_root / missing_rel)],
                    evidence_lines,
                )
            )
        elif missing_rel.startswith("kernel/linux/"):
            diagnostics.append(
                build_diagnostic(
                    "board_kernel_bsp_source_missing",
                    "external_bsp_dependency",
                    f"Ninja needs board BSP kernel source path {missing_rel}, but it is not present in the current workspace.",
                    "Keep product image generation visible; add a tracked compile-only fake kernel source marker plus a board build_kernel.sh fake-output bridge, then report the real BSP kernel source as dependency debt.",
                    [str(log_path), str(target_root / missing_rel)],
                    evidence_lines,
                )
            )
        else:
            diagnostics.append(
                build_diagnostic(
                    "ninja_missing_source_file",
                    "source_import_follow_up",
                    f"Ninja needs source file {missing_rel}, but no rule can generate it.",
                    "Import the reviewed target-source text closure that owns the missing file, or record it as unresolved source evidence if the reference tree lacks it.",
                    [str(log_path), str(target_root / missing_rel)],
                    evidence_lines,
                )
            )

    permission_denied_scripts: list[str] = []
    for line in plain_text.splitlines():
        if "/usr/bin/env:" not in line or not ("权限不够" in line or "Permission denied" in line):
            continue
        match = re.search(r"/usr/bin/env:\s*[“\"']([^”\"']+)[”\"']", line)
        if match:
            permission_denied_scripts.append(match.group(1))
        else:
            permission_denied_scripts.append(line.strip())
    for script_path in sorted(set(permission_denied_scripts))[:8]:
        normalized_script = normalize_ninja_source_path(script_path, workspace)
        diagnostics.append(
            build_diagnostic(
                "direct_invoked_script_not_executable",
                "source_file_mode_compatibility",
                f"Ninja invokes {normalized_script} directly through /usr/bin/env, but the file is not executable.",
                "Preserve the target-evidenced executable bit when staging/applying directly invoked build scripts, then rerun the compile flow.",
                [str(log_path), str(target_root / normalized_script)],
                matching_lines(all_text, [script_path, "权限不够", "Permission denied"], 10)
                + [f"normalized_script={normalized_script}"],
            )
        )

    part_subsystem_mismatches = sorted(
        set(
            re.findall(
                r"subsystem name or part name is incorrect, target is ([^,]+), subsystem name is ([^,]+), part name is ([^\s,\n]+)",
                plain_text,
            )
        )
    )
    soc_display_prefix = f"//device/soc/{clean_str(target.get('soc_vendor'))}/{clean_str(target.get('soc'))}/hardware/display"
    soc_display_mismatches = [
        (target_path, subsystem_name, part_name)
        for target_path, subsystem_name, part_name in part_subsystem_mismatches
        if target_path.startswith(soc_display_prefix)
    ]
    if soc_display_mismatches:
        diagnostics.append(
            build_diagnostic(
                "soc_display_compile_standard_whitelist_missing",
                "source_build_compatibility",
                f"SoC display targets under {soc_display_prefix} need target-evidenced compile-standard whitelist entries for part/subsystem checks.",
                "Merge only the matching target-source build/compile_standard_whitelist.json entries for this SoC display prefix, then rerun the compile flow.",
                [str(log_path), str(target_root / "build/compile_standard_whitelist.json")],
                matching_lines(
                    all_text,
                    [
                        "subsystem name or part name is incorrect",
                        soc_display_prefix,
                        "compile_standard_whitelist.json",
                    ],
                    14,
                )
                + [
                    f"target={target_path}, subsystem={subsystem_name}, part={part_name}"
                    for target_path, subsystem_name, part_name in soc_display_mismatches[:8]
                ],
            )
        )
    for target_path, subsystem_name, part_name in part_subsystem_mismatches[:8]:
        if target_path.startswith(soc_display_prefix):
            continue
        diagnostics.append(
            build_diagnostic(
                "compile_standard_part_subsystem_mismatch",
                "source_build_compatibility",
                f"Compile-standard check rejects {target_path} for subsystem {subsystem_name} and part {part_name}.",
                "Compare the target path against target-source compile_standard_whitelist evidence or correct the component ownership metadata without dropping product features.",
                [str(log_path), str(target_root / "build/compile_standard_whitelist.json")],
                matching_lines(all_text, ["subsystem name or part name is incorrect", target_path], 10),
            )
        )

    bad_subsystem_bundle_paths = sorted(set(re.findall(r"subsystem name config incorrect in '([^']+bundle\.json)'", plain_text)))
    for bundle_path in bad_subsystem_bundle_paths[:8]:
        diagnostics.append(
            build_diagnostic(
                "bundle_subsystem_path_mismatch",
                "source_build_compatibility",
                f"Bundle metadata path does not match subsystem_config: {bundle_path}.",
                "Place generated or imported bundle.json files under the subsystem root from build/subsystem_config.json, such as third_party for thirdparty or drivers for hdf.",
                [str(log_path)],
                matching_lines(all_text, ["subsystem name config incorrect", bundle_path], 8),
            )
        )

    unsupported_features = sorted(
        set(
            re.findall(
                r"The product use a feature that is not supported by this part, part_name='([^']+)', feature='([^']+)'",
                plain_text,
            )
        )
    )
    unsupported_features.extend(
        sorted(
            set(
                (part_name, feature)
                for vals, part_name in re.findall(
                    r"The product use a feature vals='\[([^\]]+)\]', but that is not defined in this part bundle\.json file, part_name='([^']+)'",
                    plain_text,
                )
                for feature in re.findall(r"'([^']+)'", vals)
            )
        )
    )
    unsupported_features = sorted(set(unsupported_features))
    for part_name, feature in unsupported_features[:8]:
        diagnostics.append(
            build_diagnostic(
                "unsupported_product_feature",
                "source_feature_registry_skew",
                f"Product selects feature {feature} for part {part_name}, but the current component registry does not declare it.",
                "Preserve the product feature; import the target component feature declaration or add a tracked compile-only feature-registry shim before validating runtime behavior.",
                [str(log_path)],
                matching_lines(all_text, ["not supported by this part", part_name, feature], 8),
            )
        )

    if "unable to find library -lstdc++" in plain_text:
        diagnostics.append(
            build_diagnostic(
                "host_static_libstdcxx_missing",
                "host_or_prebuilt_toolchain",
                "The host clang_x64 link stage cannot find libstdc++ for -static-libstdc++.",
                "Provide a host GCC library path containing libstdc++.a/libstdc++.so, or let the executor set a validated LIBRARY_PATH for the build subprocess.",
                [str(log_path)],
                matching_lines(all_text, ["unable to find library -lstdc++", "merge_abc", "-static-libstdc++"], 8),
            )
        )

    undefined_prebuilt_sources = sorted(
        set(re.findall(r"source must be defined for ([A-Za-z0-9_.+-]+)", plain_text))
    )
    for target_name in undefined_prebuilt_sources[:8]:
        diagnostics.append(
            build_diagnostic(
                "prebuilt_source_undefined",
                "external_prebuilt_dependency",
                f"GN prebuilt target {target_name} has no source for the current architecture.",
                "Add an evidenced architecture branch for the prebuilt rule; if the real binary is unavailable, use a tracked compile-only placeholder and report the missing dependency.",
                [str(log_path)],
                matching_lines(all_text, ["source must be defined", target_name], 8),
            )
        )

    file_path_slash_errors = sorted(
        set(re.findall(r"ERROR at //([^:\n]+):\d+:\d+: File path ends in a slash\.", plain_text))
    )
    for gn_path in file_path_slash_errors[:8]:
        if (
            clean_str(target.get("architecture")) == "riscv64"
            and gn_path == "build/templates/cxx/prebuilt.gni"
            and "build/common/libcpp/BUILD.gn" in plain_text
            and "libc++_shared.so" in plain_text
        ):
            diagnostics.append(
                build_diagnostic(
                    "libcpp_riscv64_prebuilt_source_missing",
                    "source_build_compatibility",
                    "build/common/libcpp leaves the libc++_shared.so prebuilt source empty for riscv64, so the generic prebuilt template sees an output directory as a file.",
                    "Apply the target-evidenced build/common/libcpp riscv64 prebuilt source rule; if the riscv64 libc++ payload is absent, use a tracked compile-only placeholder and report dependency debt.",
                    [str(log_path), str(target_root / "build/common/libcpp/BUILD.gn")],
                    matching_lines(all_text, ["File path ends in a slash", "build/common/libcpp/BUILD.gn", "libc++_shared.so", "libcpp_install"], 8),
                )
            )
        elif (
            clean_str(target.get("architecture")) == "riscv64"
            and gn_path.startswith("foundation/graphic/graphic_3d/")
            and "assets/${output_obj}" in plain_text
        ):
            diagnostics.append(
                build_diagnostic(
                    "graphic_3d_riscv64_rofs_output_obj_missing",
                    "source_build_compatibility",
                    f"graphic_3d rofs rule in {gn_path} leaves output_obj empty for riscv64, so GN sees the generated assets directory as a file path.",
                    "Apply the target-evidenced riscv64 graphic_3d rofs object mapping for matching BUILD.gn files and rerun the product build.",
                    [str(log_path), str(target_root / gn_path)],
                    matching_lines(all_text, ["File path ends in a slash", "assets/${output_obj}", "rofs", gn_path], 8),
                )
            )
        else:
            diagnostics.append(
                build_diagnostic(
                    "gn_file_path_ends_in_slash",
                    "source_build_compatibility",
                    f"GN reports a file path ending in a slash in {gn_path}.",
                    "Inspect the variable used in the path; it is likely empty for the current target architecture.",
                    [str(log_path)],
                    matching_lines(all_text, ["File path ends in a slash", gn_path], 8),
                )
            )

    if (
        clean_str(target.get("architecture")) == "riscv64"
        and "CompilerAsset.sh" in plain_text
        and "Invalid argument!" in plain_text
        and "rofs_rv64.o" in plain_text
    ):
        diagnostic_id = "graphic_3d_lume_rofs_riscv64_asset_compiler_missing"
        message = (
            "Lume rofs generation emits rofs_rv64.o but its shared template/compiler do not fully map "
            "riscv64 to the -riscv64 asset compiler path."
        )
        recommendation = (
            "Apply the target-evidenced Lume lume_config.gni riscv64 cpu_type mapping plus minimal "
            "LumeAssetCompiler -riscv64/EM_RISCV64 support, declare the host compiler source inputs, "
            "and rerun the product build."
        )
        if (
            workspace_lume_asset_compiler_sources_support_riscv64(workspace)
            and generated_lume_asset_compiler_path(workspace, product).is_file()
            and not generated_lume_asset_compiler_supports_riscv64(workspace, product)
        ):
            diagnostic_id = "graphic_3d_lume_rofs_riscv64_asset_compiler_stale"
            message = (
                "Lume sources contain riscv64 asset compiler support, but the generated host "
                "LumeAssetCompiler binary is stale and still lacks -riscv64 parsing."
            )
            recommendation = (
                "Remove the stale out/<product>/gen LumeAssetCompiler directory or declare source inputs "
                "for the lume_binary_complile action so Ninja rebuilds the host tool, then rerun the build."
            )
        diagnostics.append(
            build_diagnostic(
                diagnostic_id,
                "source_build_compatibility",
                message,
                recommendation,
                [
                    str(log_path),
                    str(target_root / "foundation/graphic/graphic_3d/lume/lume_config.gni"),
                    str(target_root / "foundation/graphic/graphic_3d/lume/LumeBinaryCompile/lumeassetcompiler/src/app.cpp"),
                    str(target_root / "foundation/graphic/graphic_3d/lume/LumeBinaryCompile/lumeassetcompiler/src/elf_common.h"),
                ],
                matching_lines(
                    all_text,
                    ["CompilerAsset.sh", "Invalid argument!", "rofs_rv64.o", "LumeAssetCompiler"],
                    12,
                ),
            )
        )

    if (
        clean_str(target.get("architecture")) == "riscv64"
        and "Assignment had no effect" in plain_text
        and "foundation/graphic/graphic_3d/lume/LumeBinaryCompile/lumeassetcompiler/BUILD.gn" in plain_text
        and "inputs = [" in plain_text
    ):
        diagnostics.append(
            build_diagnostic(
                "graphic_3d_lume_binary_compile_inputs_not_forwarded",
                "source_build_compatibility",
                "LumeAssetCompiler BUILD.gn declares action inputs, but the shared lume_binary_complile template does not forward invoker.inputs.",
                "Patch foundation/graphic/graphic_3d/lume/lume_config.gni so lume_binary_complile assigns inputs = invoker.inputs when defined, then rerun GN/build.",
                [
                    str(log_path),
                    str(target_root / "foundation/graphic/graphic_3d/lume/lume_config.gni"),
                    str(target_root / "foundation/graphic/graphic_3d/lume/LumeBinaryCompile/lumeassetcompiler/BUILD.gn"),
                ],
                matching_lines(
                    all_text,
                    ["Assignment had no effect", "lumeassetcompiler/BUILD.gn", "inputs = ["],
                    12,
                ),
            )
        )

    if (
        clean_str(target.get("architecture")) == "riscv64"
        and "third_party/libunwind" in plain_text
        and "src/riscv/Los-linux.c" in plain_text
        and "no such file or directory" in plain_text
    ):
        diagnostics.append(
            build_diagnostic(
                "third_party_libunwind_riscv64_missing_los_linux_source",
                "source_build_compatibility",
                "libunwind's RISC-V source list references src/riscv/Los-linux.c, but the libunwind-1.8.1 source archive does not contain that file.",
                "Apply the target-evidenced third_party/libunwind/BUILD.gn compatibility patch that removes src/riscv/Los-linux.c from the RISC-V source lists, then rerun the build.",
                [
                    str(log_path),
                    str(target_root / "third_party/libunwind/BUILD.gn"),
                    str(target_root / "third_party/libunwind/libunwind-1.8.1.tar.gz"),
                ],
                matching_lines(
                    all_text,
                    ["third_party/libunwind", "src/riscv/Los-linux.c", "no such file or directory"],
                    12,
                ),
            )
        )

    if (
        clean_str(target.get("architecture")) == "riscv64"
        and "foundation/resourceschedule/ffrt/interfaces/kits/c/type_def.h" in plain_text
        and '"unsupported architecture"' in plain_text
        and "ffrt_fiber_storage_size" in plain_text
    ):
        diagnostics.append(
            build_diagnostic(
                "ffrt_type_def_riscv64_fiber_storage_missing",
                "source_build_compatibility",
                "FFRT public type_def.h lacks a __riscv branch for ffrt_fiber_storage_size, so RISC-V users hit the unsupported architecture guard.",
                "Apply the target-evidenced minimal FFRT type_def.h patch that sets ffrt_fiber_storage_size = 64 for __riscv, then rerun the build.",
                [
                    str(log_path),
                    str(target_root / "foundation/resourceschedule/ffrt/interfaces/kits/c/type_def.h"),
                ],
                matching_lines(
                    all_text,
                    ["type_def.h", "unsupported architecture", "ffrt_fiber_storage_size"],
                    12,
                ),
            )
        )

    if (
        clean_str(target.get("architecture")) == "riscv64"
        and "run_objcopy.py" in plain_text
        and "KeyError: 'riscv64'" in plain_text
    ):
        objcopy_rel = "build/scripts/run_objcopy.py"
        diag_id = "riscv64_run_objcopy_arch_mapping_missing"
        if "foundation/arkui/ace_engine/build/tools/run_objcopy.py" in plain_text:
            objcopy_rel = "foundation/arkui/ace_engine/build/tools/run_objcopy.py"
            diag_id = "riscv64_arkui_run_objcopy_arch_mapping_missing"
        diagnostics.append(
            build_diagnostic(
                diag_id,
                "source_build_compatibility",
                f"{objcopy_rel} lacks riscv64 llvm-objcopy mappings for binary-to-object resource generation.",
                f"Apply the target-evidenced riscv64 OUTPUT_TARGET and BUILD_ID_LINK_OUTPUT mappings in {objcopy_rel} and rerun the compile flow.",
                [str(log_path), str(target_root / objcopy_rel)],
                matching_lines(all_text, ["run_objcopy.py", "KeyError: 'riscv64'", "--arch riscv64"], 10),
            )
        )

    if (
        clean_str(target.get("architecture")) == "riscv64"
        and "cannot link object files with different floating-point ABI" in plain_text
        and "riscv64-linux-ohos/libc.so" in plain_text
    ):
        diagnostics.append(
            build_diagnostic(
                "riscv64_musl_float_abi_link_mismatch",
                "source_build_compatibility",
                "musl libc.so link mixes riscv64 object files with different floating-point ABI settings.",
                "Align musl riscv64 compile/link cflags and global ldflags with the target-evidenced -march=rv64imafdc/-mabi=lp64d ABI.",
                [
                    str(log_path),
                    str(target_root / "build/config/compiler/BUILD.gn"),
                    str(workspace / "build/config/components/musl/BUILD.gn"),
                ],
                matching_lines(
                    all_text,
                    [
                        "cannot link object files with different floating-point ABI",
                        "riscv64-linux-ohos/libc.so",
                        "-march=rv64imafdc",
                        "-mabi=lp64d",
                    ],
                    12,
                ),
            )
        )

    component_failures = sorted(set(re.findall(r"find component ([^ ]+) failed", plain_text)))
    for component in component_failures[:8]:
        diagnostics.append(
            build_diagnostic(
                "unavailable_product_component",
                "product_config_version_skew",
                f"Product configuration references unavailable component {component}.",
                "Keep the product declaration; add or import the real component registry/source, or generate a tracked zero-subcomponent fake bundle registry for compile triage.",
                [str(log_path)],
                matching_lines(all_text, [f"find component {component} failed"], 4),
            )
        )

    ohos_component_missing = sorted(set(re.findall(r"OHOS component : \(([^)]+)\) not found", plain_text)))
    for component in ohos_component_missing[:8]:
        if component == "webview":
            diagnostics.append(
                build_diagnostic(
                    "webview_component_visibility_lost",
                    "product_config_dependency_skew",
                    "A module references webview, but the webview component is not present in the loaded product parts.",
                    "Restore the webview component in product configuration and satisfy missing external/prebuilt dependencies with tracked compile-only fake interfaces before dependency analysis.",
                    [str(log_path)],
                    matching_lines(all_text, ["OHOS component : (webview) not found", "webview:cj_webview_ffi", "cj_frontend"], 8),
                )
            )
        else:
            diagnostics.append(
                build_diagnostic(
                    "ohos_component_not_found",
                    "product_config_dependency_skew",
                    f"GN references OHOS component {component}, but it is not present in the loaded product parts.",
                    "Prefer keeping the feature/component visible; import the missing text closure or add a tracked fake interface for external dependencies, then report unresolved dependency debt.",
                    [str(log_path)],
                    matching_lines(all_text, [f"OHOS component : ({component}) not found", component], 8),
                )
            )

    if "unsupported cpu riscv64" in plain_text and not any(
        diag["id"] in {
            "riscv64_ndk_shlib_directory_mapping",
            "riscv64_arkcompiler_cache_line_size_missing",
            "graphic_3d_lume_binary_compile_inputs_not_forwarded",
        }
        for diag in diagnostics
    ):
        diagnostics.append(
            build_diagnostic(
                "unsupported_cpu_riscv64_message",
                "upstream_component_arch_gap",
                "The build log contains an unsupported cpu riscv64 message.",
                "Inspect the nearby GN target after earlier blockers are removed; it may require a component-level riscv64 guard or upstream compatibility patch.",
                [str(log_path)],
                matching_lines(all_text, ["unsupported cpu riscv64"], 4),
                severity="warning",
            )
        )

    return diagnostics


def test_host_clang_cstdlib(clangxx: Path, env: dict[str, str] | None = None) -> bool:
    if not clangxx.is_file():
        return True
    try:
        proc = subprocess.run(
            [str(clangxx), "-E", "-x", "c++", "-"],
            input=b"#include <cstdlib>\n",
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            env=env,
            timeout=15,
            check=False,
        )
    except Exception:
        return True
    return proc.returncode == 0


def test_host_clang_static_libstdcxx(clangxx: Path, env: dict[str, str] | None = None) -> bool:
    if not clangxx.is_file():
        return True
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(prefix="ohos_clang_link_", delete=False) as tmp:
            tmp_path = tmp.name
        proc = subprocess.run(
            [str(clangxx), "-x", "c++", "-", "-static-libstdc++", "-o", tmp_path],
            input=b"int main() { return 0; }\n",
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            env=env,
            timeout=20,
            check=False,
        )
        return proc.returncode == 0
    except Exception:
        return True
    finally:
        if tmp_path:
            try:
                Path(tmp_path).unlink()
            except FileNotFoundError:
                pass


def version_sort_key(path: Path) -> tuple[int, ...]:
    numbers = [int(part) for part in re.findall(r"\d+", path.name)]
    return tuple(numbers) if numbers else (0,)


def detect_host_cxx_env_fix(workspace: Path) -> dict[str, Any]:
    clangxx = workspace / "prebuilts/clang/ohos/linux-x86_64/llvm/bin/clang++"
    if test_host_clang_cstdlib(clangxx) and test_host_clang_static_libstdcxx(clangxx):
        return {"applied": False, "reason": "host clang can include <cstdlib> and link -static-libstdc++ without extra environment"}

    include_root = Path("/usr/include/c++")
    arch_root = Path("/usr/include/x86_64-linux-gnu/c++")
    candidates = sorted(
        [path for path in include_root.iterdir() if path.is_dir()] if include_root.is_dir() else [],
        key=version_sort_key,
        reverse=True,
    )
    base_env = os.environ.copy()
    existing = base_env.get("CPLUS_INCLUDE_PATH", "")
    for include_dir in candidates:
        paths = [str(include_dir)]
        arch_dir = arch_root / include_dir.name
        if arch_dir.is_dir():
            paths.append(str(arch_dir))
        if existing:
            paths.append(existing)
        candidate_env = base_env.copy()
        candidate_env["CPLUS_INCLUDE_PATH"] = ":".join(paths)
        lib_dir = Path("/usr/lib/gcc/x86_64-linux-gnu") / include_dir.name
        existing_lib = base_env.get("LIBRARY_PATH", "")
        lib_paths = []
        if (lib_dir / "libstdc++.a").is_file() or (lib_dir / "libstdc++.so").is_file():
            lib_paths.append(str(lib_dir))
        if existing_lib:
            lib_paths.append(existing_lib)
        if lib_paths:
            candidate_env["LIBRARY_PATH"] = ":".join(lib_paths)
        if test_host_clang_cstdlib(clangxx, candidate_env) and test_host_clang_static_libstdcxx(clangxx, candidate_env):
            exported_env = {}
            if "LIBRARY_PATH" in candidate_env:
                exported_env["LIBRARY_PATH"] = candidate_env["LIBRARY_PATH"]
            return {
                "applied": bool(exported_env),
                "env": exported_env,
                "probe_only_env": {"CPLUS_INCLUDE_PATH": candidate_env["CPLUS_INCLUDE_PATH"]},
                "omitted_global_env": ["CPLUS_INCLUDE_PATH"],
                "reason": (
                    "prebuilt host clang selected an incomplete GCC installation; "
                    "validated host C++ include/library probes but omitted global CPLUS_INCLUDE_PATH "
                    f"to avoid target C++ header pollution; exported env {exported_env}"
                ),
                "validation": "#include <cstdlib> and -static-libstdc++ link probes passed with probe-only CPLUS_INCLUDE_PATH",
            }
    return {
        "applied": False,
        "reason": "host clang still cannot include <cstdlib> with detected /usr/include/c++ candidates",
    }


def run_build(
    workspace: Path,
    out_dir: Path,
    product: str,
    timeout_sec: int,
    host_env_fix: dict[str, Any] | None = None,
) -> dict[str, Any]:
    log_path = out_dir / f"build_{product}.log"
    command = ["./build.sh", "--product-name", product, "--ccache=false"]
    timed_out = False
    return_code = 0
    started_at_epoch = time.time()
    env = os.environ.copy()
    if host_env_fix and host_env_fix.get("applied") and isinstance(host_env_fix.get("env"), dict):
        env.update({str(key): str(value) for key, value in host_env_fix["env"].items()})
    with log_path.open("wb") as log:
        log.write((f"# Command: {' '.join(command)}\n# CWD: {workspace}\n# Started: {now()}\n\n").encode(TEXT_ENCODING))
        if host_env_fix and host_env_fix.get("applied"):
            log.write((f"# Host env fix: {host_env_fix.get('reason')}\n\n").encode(TEXT_ENCODING))
        try:
            proc = subprocess.run(
                command,
                cwd=workspace,
                stdout=log,
                stderr=subprocess.STDOUT,
                timeout=timeout_sec,
                env=env,
                check=False,
            )
            return_code = proc.returncode
        except subprocess.TimeoutExpired:
            timed_out = True
            return_code = 124
            log.write((f"\n# Timed out after {timeout_sec} seconds at {now()}\n").encode(TEXT_ENCODING))
    return {
        "command": " ".join(command),
        "return_code": return_code,
        "timed_out": timed_out,
        "timeout_sec": timeout_sec,
        "log_path": str(log_path),
        "started_at_epoch": started_at_epoch,
        "host_env_fix": host_env_fix or {"applied": False, "reason": "not evaluated"},
    }


def prepare_generated_artifacts_for_build(workspace: Path, product: str, target: dict[str, Any]) -> list[dict[str, Any]]:
    cleanups: list[dict[str, Any]] = []
    if clean_str(target.get("architecture")) != "riscv64":
        return cleanups
    if not workspace_lume_asset_compiler_sources_support_riscv64(workspace):
        return cleanups

    binary_path = generated_lume_asset_compiler_path(workspace, product)
    if not binary_path.is_file() or generated_lume_asset_compiler_supports_riscv64(workspace, product):
        return cleanups

    generated_dir = binary_path.parent
    workspace_resolved = workspace.resolve()
    generated_resolved = generated_dir.resolve()
    allowed_prefix = (
        workspace_resolved
        / "out"
        / product
        / "gen/foundation/graphic/graphic_3d/lume/LumeBinaryCompile/lumeassetcompiler"
    ).resolve()
    if generated_resolved != allowed_prefix or workspace_resolved not in generated_resolved.parents:
        cleanups.append(
            {
                "path": str(generated_dir),
                "status": "skipped_path_safety_check_failed",
                "reason": "refused to remove generated LumeAssetCompiler path outside the expected out/<product>/gen subtree",
            }
        )
        return cleanups

    shutil.rmtree(generated_dir)
    cleanups.append(
        {
            "path": str(generated_dir),
            "status": "removed",
            "reason": "stale generated LumeAssetCompiler lacked -riscv64 while patched sources require riscv64 support",
        }
    )
    return cleanups


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", required=True, help="OpenHarmony workspace to patch.")
    parser.add_argument("--target-source-root", required=True, help="Read-only target/reference OpenHarmony source root.")
    parser.add_argument("--target-profile", required=True, help="Target profile seed YAML.")
    parser.add_argument("--out", required=True, help="Output directory for manifests, staged files, backups, and build logs.")
    parser.add_argument("--apply", action="store_true", help="Write staged files into the workspace.")
    parser.add_argument("--overwrite", action="store_true", help="Allow replacing existing differing workspace files after backup.")
    parser.add_argument("--attempt-build", action="store_true", help="Run ./build.sh --product-name <seed product> --ccache=false after a successful apply.")
    parser.add_argument("--build-timeout-sec", type=int, default=DEFAULT_BUILD_TIMEOUT_SEC, help="Build timeout in seconds.")
    parser.add_argument(
        "--no-ohos6-subsystem-normalization",
        action="store_true",
        help="Disable compatibility normalization of product/device ohos.build subsystem names.",
    )
    parser.add_argument(
        "--filter-unavailable-components",
        action="store_true",
        help="Opt in to filtering target config components/features not visible in the current workspace. Default preserves product feature declarations.",
    )
    parser.add_argument(
        "--no-component-visibility-filter",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--defer-external-prebuilt-components",
        action="store_true",
        help="Opt in to removing external-prebuilt-backed components from compile-triage product config. Default keeps product features visible and uses fake interfaces where implemented.",
    )
    parser.add_argument(
        "--no-external-prebuilt-deferral",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--no-fake-missing-source-components",
        action="store_true",
        help="Disable generation of compile-only fake bundle.json registries for product components missing from the current source tree.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    workspace = Path(args.workspace).resolve()
    target_root = Path(args.target_source_root).resolve()
    target_profile = Path(args.target_profile).resolve()
    out_dir = Path(args.out).resolve()
    staged_root = out_dir / "staged_files"
    backup_root = out_dir / "backups"
    out_dir.mkdir(parents=True, exist_ok=True)

    if args.attempt_build and not args.apply:
        raise SystemExit("--attempt-build requires --apply")
    if not workspace.is_dir():
        raise SystemExit(f"workspace not found: {workspace}")
    if not target_root.is_dir():
        raise SystemExit(f"target source root not found: {target_root}")
    if not target_profile.is_file():
        raise SystemExit(f"target profile seed not found: {target_profile}")
    if not (workspace / "build.sh").is_file():
        raise SystemExit(f"workspace does not look like an OpenHarmony root: {workspace}")

    seed = read_yaml(target_profile)
    target = {
        "product": clean_str(seed.get("product")),
        "board": clean_str(seed.get("board")),
        "soc": clean_str(seed.get("soc")),
        "soc_vendor": clean_str(seed.get("soc_vendor")),
        "vendor": clean_str(seed.get("vendor")),
        "architecture": clean_str(seed.get("architecture")),
        "openharmony_version": clean_str(seed.get("openharmony_version")),
    }

    actions, notes = planned_actions(
        seed,
        target_root,
        workspace,
        not args.no_fake_missing_source_components,
    )
    component_visibility_filter_enabled = bool(args.filter_unavailable_components) and not args.no_component_visibility_filter
    component_features: dict[str, set[str] | None] | None = None
    if component_visibility_filter_enabled:
        component_features = collect_workspace_component_features(workspace, target)
    external_prebuilt_deferral_enabled = bool(args.defer_external_prebuilt_components) and not args.no_external_prebuilt_deferral
    component_deferrals = detect_external_prebuilt_component_deferrals(
        workspace,
        target_root,
        target,
        external_prebuilt_deferral_enabled,
    )
    if component_deferrals:
        notes.append(
            "External prebuilt-backed components deferred for compile triage: "
            + ", ".join(sorted(component_deferrals))
        )
    results: list[dict[str, Any]] = []
    blocking_issues: list[dict[str, Any]] = []

    for action in actions:
        rel_path = clean_str(action["path"])
        workspace_path = workspace / rel_path
        staged_path = staged_root / rel_path
        if staged_path.name == "bundle.json":
            staged_path = staged_root / "_non_scanned_bundle_json" / (rel_path + ".staged")
        data, source_label, source_status, transforms = materialize_action(
            action,
            workspace,
            target_root,
            target,
            not args.no_ohos6_subsystem_normalization,
            component_features,
            component_deferrals,
        )

        result = {key: value for key, value in action.items() if key not in {"generated_json", "generated_text"}}
        result.update(
            {
                "workspace_path": str(workspace_path),
                "staged_path": str(staged_path),
                "source_label": source_label,
                "source_status": source_status,
                "workspace_status": "missing",
                "source_sha256": "unknown",
                "workspace_sha256": "unknown",
                "workspace_mode": "unknown",
                "desired_mode": "unknown",
                "apply_status": "not_requested",
                "backup_path": "none",
                "compatibility_transforms": transforms,
            }
        )

        if data is None:
            result["apply_status"] = "blocked_missing_source"
            blocking_issues.append({"path": rel_path, "reason": "target source file is missing"})
            results.append(result)
            continue

        result["source_sha256"] = sha256_bytes(data)
        desired_mode = executable_source_mode(source_label, bool(action.get("force_executable")))
        if desired_mode is not None:
            result["desired_mode"] = oct(desired_mode)
        write_bytes(staged_path, data)
        apply_mode(staged_path, desired_mode)

        if workspace_path.exists():
            if workspace_path.is_file():
                result["workspace_status"] = "present"
                result["workspace_sha256"] = sha256_file(workspace_path)
                result["workspace_mode"] = oct(workspace_path.stat().st_mode & 0o777)
            else:
                result["workspace_status"] = "present_non_file"
                result["apply_status"] = "blocked_non_file_target"
                blocking_issues.append({"path": rel_path, "reason": "workspace target exists and is not a file"})
                results.append(result)
                continue

        if not args.apply:
            results.append(result)
            continue

        mode_needs_update = (
            desired_mode is not None
            and result["workspace_status"] == "present"
            and (workspace_path.stat().st_mode & 0o777) != desired_mode
        )
        if (
            result["workspace_status"] == "present"
            and result["workspace_sha256"] == result["source_sha256"]
            and not mode_needs_update
        ):
            result["apply_status"] = "skipped_same_content"
            results.append(result)
            continue
        if (
            result["workspace_status"] == "present"
            and result["workspace_sha256"] == result["source_sha256"]
            and mode_needs_update
        ):
            apply_mode(workspace_path, desired_mode)
            result["apply_status"] = "applied_mode_updated"
            result["workspace_mode_after"] = oct(workspace_path.stat().st_mode & 0o777)
            result["workspace_sha256_after"] = sha256_file(workspace_path)
            results.append(result)
            continue

        if result["workspace_status"] == "present" and not args.overwrite:
            result["apply_status"] = "blocked_existing_file_differs"
            blocking_issues.append({"path": rel_path, "reason": "workspace file exists and differs; rerun with --overwrite after review"})
            results.append(result)
            continue

        if result["workspace_status"] == "present":
            backup_path = backup_root / rel_path
            mkdir_parent(backup_path)
            shutil.copy2(workspace_path, backup_path)
            result["backup_path"] = str(backup_path)

        write_bytes(workspace_path, data)
        apply_mode(workspace_path, desired_mode)
        result["apply_status"] = "applied_created" if result["workspace_status"] == "missing" else "applied_overwritten_with_backup"
        result["workspace_sha256_after"] = sha256_file(workspace_path)
        result["workspace_mode_after"] = oct(workspace_path.stat().st_mode & 0o777)
        results.append(result)

    if args.apply:
        unapplied_blockers = [item for item in results if str(item["apply_status"]).startswith("blocked")]
        for item in unapplied_blockers:
            if not any(issue["path"] == item["path"] for issue in blocking_issues):
                blocking_issues.append({"path": item["path"], "reason": item["apply_status"]})

    build_result: dict[str, Any] | None = None
    prebuild_cleanups: list[dict[str, Any]] = []
    if args.attempt_build and not blocking_issues:
        prebuild_cleanups = prepare_generated_artifacts_for_build(workspace, target["product"], target)
        host_env_fix = detect_host_cxx_env_fix(workspace)
        build_result = run_build(workspace, out_dir, target["product"], args.build_timeout_sec, host_env_fix)
        build_result["prebuild_cleanups"] = prebuild_cleanups
        build_result["diagnostics"] = parse_build_diagnostics(build_result, workspace, target_root, target["product"], target)

    fake_interfaces = [
        {
            "path": item["path"],
            "source_sha256": item.get("source_sha256", "unknown"),
            **item.get("fake_interface", {}),
        }
        for item in results
        if isinstance(item.get("fake_interface"), dict)
    ]
    summary = {
        "planned_actions": len(results),
        "available_source_actions": sum(1 for item in results if item["source_status"] == "available"),
        "applied_actions": sum(1 for item in results if str(item["apply_status"]).startswith("applied")),
        "skipped_same_content_actions": sum(1 for item in results if item["apply_status"] == "skipped_same_content"),
        "blocking_issue_count": len(blocking_issues),
        "build_diagnostic_count": len(build_result.get("diagnostics", [])) if build_result else 0,
        "fake_interface_count": len(fake_interfaces),
        "prebuild_cleanup_count": len(prebuild_cleanups),
    }
    manifest = {
        "schema_version": 1,
        "artifact_type": "porting_base_patch_execution",
        "generated_at": now(),
        "workspace": str(workspace),
        "target_source_root": str(target_root),
        "target_profile": str(target_profile),
        "target": target,
        "apply_requested": bool(args.apply),
        "overwrite_requested": bool(args.overwrite),
        "attempt_build": bool(args.attempt_build),
        "write_policy": "apply_only_when_flagged",
        "dependency_policy": "exclude_real_binary_firmware_bootloader_prebuilt_kernel_module_payloads_generate_marked_compile_only_fakes_when_needed",
        "compatibility_policy": {
            "ohos6_subsystem_normalization": not args.no_ohos6_subsystem_normalization,
            "component_visibility_filter": component_visibility_filter_enabled,
            "external_prebuilt_component_deferral": external_prebuilt_deferral_enabled,
            "compile_only_fake_interfaces": True,
            "fake_missing_source_components": not args.no_fake_missing_source_components,
            "reason": "OpenHarmony 6.0 preloader injects product_<product> and device_<board> subsystem paths.",
        },
        "available_component_count": len(component_features) if component_features is not None else 0,
        "external_prebuilt_deferrals": list(component_deferrals.values()),
        "fake_interfaces": fake_interfaces,
        "prebuild_cleanups": prebuild_cleanups,
        "actions": results,
        "blocking_issues": blocking_issues,
        "notes": notes,
        "summary": summary,
        "build_result": build_result,
    }

    manifest_yaml = out_dir / "base_patch_manifest.yaml"
    manifest_md = out_dir / "base_patch_manifest.md"
    manifest_yaml.write_text(yaml.safe_dump(manifest, allow_unicode=True, sort_keys=False), encoding=TEXT_ENCODING)
    manifest_md.write_text(render_markdown(manifest), encoding=TEXT_ENCODING)

    if blocking_issues:
        return 2 if args.apply else 0
    if build_result and build_result["return_code"] != 0:
        return int(build_result["return_code"]) if int(build_result["return_code"]) > 0 else 1
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        raise SystemExit(130)
