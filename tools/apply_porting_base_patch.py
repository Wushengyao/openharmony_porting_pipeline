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
from typing import Any

import yaml


TEXT_ENCODING = "utf-8"
DEFAULT_BUILD_TIMEOUT_SEC = 3600


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


def filter_unavailable_product_components(
    config: dict[str, Any],
    component_features: dict[str, set[str] | None] | None,
) -> tuple[dict[str, Any], list[str]]:
    filtered = copy.deepcopy(config)
    removed: list[str] = []
    if component_features is None:
        return filtered, removed
    subsystems = filtered.get("subsystems")
    if not isinstance(subsystems, list):
        return filtered, removed
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
            if (
                not component_name
                or component_name in component_features
                or component_name == subsystem_name
            ):
                supported_features = component_features.get(component_name)
                features = component.get("features")
                if supported_features is not None and isinstance(features, list):
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


def planned_actions(seed: dict[str, Any], target_root: Path) -> tuple[list[dict[str, Any]], list[str]]:
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

    notes = [
        "Binary, firmware, bootloader, prebuilt, and kernel-module payloads are intentionally excluded.",
        "Board root BUILD.gn is included because board ohos.build references it directly; feature subdirectories remain follow-up batches.",
        "Runtime/HDF config remains a follow-up batch unless build triage shows it is a direct base-binding blocker.",
        "RISC-V NDK build-file compatibility is applied only when target-source evidence contains the riscv64 NDK mapping.",
        "RISC-V third_party/curl build compatibility is applied only when target-source evidence contains the riscv64 cflags guard.",
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
        deferred_prefixes = [f"//vendor/{vendor}/{product}/bluetooth"]
        removed_labels: list[str] = []
        for part_data in parts.values():
            if not isinstance(part_data, dict):
                continue
            module_list = part_data.get("module_list")
            if not isinstance(module_list, list):
                continue
            kept_modules = []
            for label in module_list:
                text = clean_str(label, "")
                if any(text.startswith(prefix) for prefix in deferred_prefixes):
                    removed_labels.append(text)
                else:
                    kept_modules.append(label)
            if len(kept_modules) != len(module_list):
                part_data["module_list"] = kept_modules
                changed = True
        if removed_labels:
            notes.append("deferred binary/firmware-linked board modules: " + ", ".join(dict.fromkeys(removed_labels)))

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


def materialize_action(
    action: dict[str, Any],
    workspace: Path,
    target_root: Path,
    target: dict[str, str],
    normalize_subsystems: bool,
    component_features: dict[str, set[str] | None] | None,
) -> tuple[bytes | None, str, str, list[str]]:
    rel_path = clean_str(action.get("path"), "")
    if action.get("content_source") == "generated_from_target_vendor_config":
        config, removed = filter_unavailable_product_components(action["generated_json"], component_features)
        notes = []
        if removed:
            notes.append("filtered unavailable components/features from generated productdefine: " + ", ".join(removed))
        return productdefine_bytes(config), "generated", "available", notes
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
            config, removed = filter_unavailable_product_components(config, component_features)
            if removed:
                transforms.append("filtered unavailable components/features from vendor config: " + ", ".join(removed))
                data = (json.dumps(config, ensure_ascii=False, indent=2) + "\n").encode(TEXT_ENCODING)
    if rel_path.startswith("productdefine/common/inherit/") and rel_path.endswith(".json"):
        try:
            config = json.loads(data.decode(TEXT_ENCODING))
        except Exception:
            config = None
        if isinstance(config, dict):
            config, removed = filter_unavailable_product_components(config, component_features)
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
                "",
            ]
        )
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
    for path in candidate_logs:
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

    undefined_identifier_matches = sorted(
        set(
            re.findall(
                r"ERROR at //([^:\n]+):\d+:\d+: Undefined identifier\.\s+([A-Za-z_][A-Za-z0-9_]*) \+=",
                plain_text,
            )
        )
    )
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
                    "Do not import the HAP through the base source patch. Provide/provenance-check the prebuilt separately, or explicitly defer the webview component for compile-only triage.",
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
                    "Compare the current workspace file with the reference target source and decide whether this is a safe text compatibility patch or a dependency-backed feature to defer.",
                    [str(log_path)],
                    matching_lines(all_text, [gn_path, "Undefined identifier", f"{identifier} +="], 8),
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

    component_failures = sorted(set(re.findall(r"find component ([^ ]+) failed", plain_text)))
    for component in component_failures[:8]:
        diagnostics.append(
            build_diagnostic(
                "unavailable_product_component",
                "product_config_version_skew",
                f"Product configuration references unavailable component {component}.",
                "Filter or replace the component using current workspace bundle metadata before rerunning preloader/build.",
                [str(log_path)],
                matching_lines(all_text, [f"find component {component} failed"], 4),
            )
        )

    if "unsupported cpu riscv64" in plain_text and not any(diag["id"] == "riscv64_ndk_shlib_directory_mapping" for diag in diagnostics):
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


def run_build(workspace: Path, out_dir: Path, product: str, timeout_sec: int) -> dict[str, Any]:
    log_path = out_dir / f"build_{product}.log"
    command = ["./build.sh", "--product-name", product, "--ccache=false"]
    timed_out = False
    return_code = 0
    with log_path.open("wb") as log:
        log.write((f"# Command: {' '.join(command)}\n# CWD: {workspace}\n# Started: {now()}\n\n").encode(TEXT_ENCODING))
        try:
            proc = subprocess.run(
                command,
                cwd=workspace,
                stdout=log,
                stderr=subprocess.STDOUT,
                timeout=timeout_sec,
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
    }


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
        "--no-component-visibility-filter",
        action="store_true",
        help="Disable filtering of target config components not visible in the current workspace.",
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

    actions, notes = planned_actions(seed, target_root)
    component_features: dict[str, set[str] | None] | None = collect_workspace_component_features(workspace, target)
    if args.no_component_visibility_filter:
        component_features = None
    results: list[dict[str, Any]] = []
    blocking_issues: list[dict[str, Any]] = []

    for action in actions:
        rel_path = clean_str(action["path"])
        workspace_path = workspace / rel_path
        staged_path = staged_root / rel_path
        data, source_label, source_status, transforms = materialize_action(
            action,
            workspace,
            target_root,
            target,
            not args.no_ohos6_subsystem_normalization,
            component_features,
        )

        result = {key: value for key, value in action.items() if key != "generated_json"}
        result.update(
            {
                "workspace_path": str(workspace_path),
                "staged_path": str(staged_path),
                "source_label": source_label,
                "source_status": source_status,
                "workspace_status": "missing",
                "source_sha256": "unknown",
                "workspace_sha256": "unknown",
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
        write_bytes(staged_path, data)

        if workspace_path.exists():
            if workspace_path.is_file():
                result["workspace_status"] = "present"
                result["workspace_sha256"] = sha256_file(workspace_path)
            else:
                result["workspace_status"] = "present_non_file"
                result["apply_status"] = "blocked_non_file_target"
                blocking_issues.append({"path": rel_path, "reason": "workspace target exists and is not a file"})
                results.append(result)
                continue

        if not args.apply:
            results.append(result)
            continue

        if result["workspace_status"] == "present" and result["workspace_sha256"] == result["source_sha256"]:
            result["apply_status"] = "skipped_same_content"
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
        result["apply_status"] = "applied_created" if result["workspace_status"] == "missing" else "applied_overwritten_with_backup"
        result["workspace_sha256_after"] = sha256_file(workspace_path)
        results.append(result)

    if args.apply:
        unapplied_blockers = [item for item in results if str(item["apply_status"]).startswith("blocked")]
        for item in unapplied_blockers:
            if not any(issue["path"] == item["path"] for issue in blocking_issues):
                blocking_issues.append({"path": item["path"], "reason": item["apply_status"]})

    build_result: dict[str, Any] | None = None
    if args.attempt_build and not blocking_issues:
        build_result = run_build(workspace, out_dir, target["product"], args.build_timeout_sec)
        build_result["diagnostics"] = parse_build_diagnostics(build_result, workspace, target_root, target["product"], target)

    summary = {
        "planned_actions": len(results),
        "available_source_actions": sum(1 for item in results if item["source_status"] == "available"),
        "applied_actions": sum(1 for item in results if str(item["apply_status"]).startswith("applied")),
        "skipped_same_content_actions": sum(1 for item in results if item["apply_status"] == "skipped_same_content"),
        "blocking_issue_count": len(blocking_issues),
        "build_diagnostic_count": len(build_result.get("diagnostics", [])) if build_result else 0,
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
        "dependency_policy": "exclude_binary_firmware_bootloader_prebuilt_kernel_module_payloads",
        "compatibility_policy": {
            "ohos6_subsystem_normalization": not args.no_ohos6_subsystem_normalization,
            "component_visibility_filter": not args.no_component_visibility_filter,
            "reason": "OpenHarmony 6.0 preloader injects product_<product> and device_<board> subsystem paths.",
        },
        "available_component_count": len(component_features) if component_features is not None else 0,
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
