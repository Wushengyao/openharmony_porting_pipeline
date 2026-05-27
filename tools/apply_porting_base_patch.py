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
    ".py",
    ".sh",
    ".txt",
    ".xml",
}
TEXT_CLOSURE_FILENAMES = {
    "BUILD.gn",
    "Kconfig",
    "Makefile",
}
TEE_RISCV64_BARRIER_SOURCE_RELS = [
    "base/tee/tee_client/services/teecd/src/secfile_load_agent.c",
    "base/tee/tee_client/services/teecd/src/fs_work_agent.c",
    "base/tee/tee_client/services/teecd/src/misc_work_agent.c",
]
PROFILER_NATIVE_DAEMON_RISCV64_SOURCE_RELS = [
    (
        "developtools/profiler/device/plugins/native_daemon/include/register.h",
        "profiler_native_daemon_riscv64_register_header",
        "Import target-evidenced RISC-V register enum, buildArchType, arch-name, and register-count support.",
    ),
    (
        "developtools/profiler/device/plugins/native_daemon/src/register.cpp",
        "profiler_native_daemon_riscv64_register_cpp",
        "Import target-evidenced RISC-V libunwind-to-perf register mapping paired with register.h.",
    ),
    (
        "developtools/profiler/device/plugins/native_daemon/src/call_stack.cpp",
        "profiler_native_daemon_riscv64_call_stack",
        "Import target-evidenced DfxRegsRiscv64 unwind register selection for native daemon call stacks.",
    ),
]
HIPERF_RISCV64_SOURCE_RELS = [
    (
        "developtools/hiperf/include/register.h",
        "hiperf_riscv64_register_header",
        "Import target-evidenced RISC-V perf register enum and BUILD_ARCH_TYPE support.",
    ),
    (
        "developtools/hiperf/src/register.cpp",
        "hiperf_riscv64_register_cpp",
        "Import target-evidenced RISC-V register mask, name, uname, ABI, and libunwind mapping support.",
    ),
    (
        "developtools/hiperf/src/callstack.cpp",
        "hiperf_riscv64_callstack",
        "Import target-evidenced DfxRegsRiscv64 call-stack register selection.",
    ),
    (
        "developtools/hiperf/src/hiperf_libreport.cpp",
        "hiperf_riscv64_libreport",
        "Import target-evidenced RISC-V machine-name support for hiperf reports.",
    ),
    (
        "developtools/hiperf/include/nonlinux/linux/perf_event_host.h",
        "hiperf_host_perf_event_text_header",
        "Import the target-evidenced host perf_event fallback header referenced by the updated hiperf register header.",
    ),
]
ARKUI_NAPI_RISCV64_CJ_SUPPORT_REL = "foundation/arkui/napi/native_engine/impl/ark/cj_support.cpp"
GRAPHIC_2D_VSYNC_LOG_REL = "foundation/graphic/graphic_2d/rosen/modules/composer/vsync/include/vsync_log.h"
LUME_STATIC_PLUGIN_DECL_REL = "foundation/graphic/graphic_3d/lume/LumeEngine/src/static_plugin_decl.h"
ARK_ETS_RUNTIME_BUILD_REL = "arkcompiler/ets_runtime/BUILD.gn"
ARK_ETS_RUNTIME_RISCV64_TRAMPOLINE_REL = "arkcompiler/ets_runtime/ecmascript/trampoline/riscv64/raw_asm_stub.S"
ARK_RUNTIME_ASM_SUPPORT_CPP_REL = "arkcompiler/runtime_core/static_core/runtime/arch/asm_support.cpp"
ARK_ETS_SUBPROJECT_SOURCES_REL = "arkcompiler/runtime_core/static_core/plugins/ets/subproject_sources.gn"
ARK_ETS_PROXY_ENTRYPOINTS_CPP_REL = "arkcompiler/runtime_core/static_core/plugins/ets/runtime/entrypoints/ets_proxy_entrypoints.cpp"
ARK_ETS_RISCV64_BRIDGE_SOURCE_RELS = [
    "arkcompiler/runtime_core/static_core/plugins/ets/runtime/interop_js/arch/riscv64/call_bridge_riscv64.S",
    "arkcompiler/runtime_core/static_core/plugins/ets/runtime/napi/arch/riscv64/ets_napi_entry_point_riscv64.S",
    "arkcompiler/runtime_core/static_core/plugins/ets/runtime/napi/arch/riscv64/ets_async_entry_point_riscv64.S",
    ARK_ETS_PROXY_ENTRYPOINTS_CPP_REL,
    "arkcompiler/runtime_core/static_core/plugins/ets/runtime/entrypoints/arch/riscv64/ets_proxy_entry_point_riscv64.S",
    "arkcompiler/runtime_core/static_core/runtime/bridge/arch/riscv64/proxy_entrypoint_riscv64.S",
]
SKIA_RASTER_PIPELINE_OPTS_REL = "third_party/skia/m133/src/opts/SkRasterPipeline_opts.h"
RUN_OBJCOPY_REL = "build/scripts/run_objcopy.py"
CXX_STDLIB_HEADER_NAMES = {
    "algorithm",
    "array",
    "atomic",
    "bitset",
    "cinttypes",
    "condition_variable",
    "cstddef",
    "cstdint",
    "cstdlib",
    "ctime",
    "functional",
    "list",
    "map",
    "memory",
    "mutex",
    "optional",
    "string",
    "type_traits",
    "unordered_map",
    "utility",
    "vector",
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


def ark_ets_proxy_entrypoints_compile_only_stub(target_root: Path) -> str:
    return "\n".join(
        [
            "/* Auto-generated compile-only OpenHarmony porting source stub.",
            f" * Reference dependency: {target_root / ARK_ETS_PROXY_ENTRYPOINTS_CPP_REL}",
            " * The real ETS proxy invoke runtime depends on the newer ETS reflection API.",
            " * Runtime implementation is intentionally absent.",
            " */",
            "#include <cstdint>",
            "",
            "namespace ark::ets::entrypoints {",
            "",
            "extern \"C\" void EtsProxyEntryPoint();",
            "",
            "const void *GetEtsProxyEntryPoint()",
            "{",
            "    return reinterpret_cast<const void *>(EtsProxyEntryPoint);",
            "}",
            "",
            "extern \"C\" int64_t EtsProxyMethodInvoke(void *method, uint8_t *args, uint8_t *inStackArgs)",
            "{",
            "    (void)method;",
            "    (void)args;",
            "    (void)inStackArgs;",
            "    return 0;",
            "}",
            "",
            "}  // namespace ark::ets::entrypoints",
        ]
    ) + "\n"


def workspace_lacks_ark_ets_reflect_proxy_runtime(workspace: Path) -> bool:
    reflect_method = workspace / "arkcompiler/runtime_core/static_core/plugins/ets/runtime/types/ets_reflect_method.h"
    platform_types = workspace / "arkcompiler/runtime_core/static_core/plugins/ets/runtime/ets_platform_types.h"
    if not reflect_method.is_file() or not platform_types.is_file():
        return True
    text = platform_types.read_text(encoding=TEXT_ENCODING, errors="ignore")
    return "coreReflectProxyInvoke" not in text or "coreReflectInstanceMethod" not in text


def generated_fake_shared_library_action(
    rel_path: str,
    role: str,
    phase: str,
    reason: str,
    missing_dependency: str,
    provenance_path: str,
    follow_up: str = "replace with provenance-checked vendor/third-party shared library before runtime validation",
) -> dict[str, Any]:
    return {
        "path": normalize_rel(rel_path),
        "source_path": normalize_rel(rel_path),
        "content_source": "generated_fake_shared_library",
        "source_role": role,
        "phase": phase,
        "reason": reason,
        "dependency_policy": "compile_only_fake_shared_library",
        "fake_interface": {
            "missing_dependency": missing_dependency,
            "provenance_path": provenance_path,
            "scope": "compile_only_linkable_shared_library",
            "runtime_status": "not_functional",
            "symbol_policy": "reference_dynsym_stub_when_available",
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


def collect_gn_quoted_file_rels(
    target_root: Path,
    file_rels: list[str],
    absolute_prefixes: list[str],
    variable_paths: dict[str, str] | None = None,
) -> list[str]:
    normalized_prefixes = [normalize_rel(prefix) for prefix in absolute_prefixes]
    collected: list[str] = []
    for file_rel in file_rels:
        owner_rel = normalize_rel(file_rel).rsplit("/", 1)[0] if "/" in normalize_rel(file_rel) else ""
        path = target_root / normalize_rel(file_rel)
        if not path.is_file():
            continue
        text = path.read_text(encoding=TEXT_ENCODING, errors="ignore")
        for quoted in re.findall(r'"([^"]+)"', text):
            label_path = replace_gn_label_variables(quoted.strip(), variable_paths)
            if ":" in label_path:
                continue
            try:
                if label_path.startswith("//"):
                    rel_path = normalize_rel(label_path[2:])
                else:
                    rel_path = resolve_relative_gn_label(owner_rel, label_path)
            except ValueError:
                continue
            if normalized_prefixes and not any(
                rel_path == prefix or rel_path.startswith(f"{prefix}/")
                for prefix in normalized_prefixes
            ):
                continue
            if rel_path not in collected and (target_root / rel_path).is_file():
                collected.append(rel_path)
    return collected


def collect_webview_glue_prepare_input_file_rels(target_root: Path) -> list[str]:
    interface_build_rel = "base/web/webview/ohos_interface/BUILD.gn"
    collected = [interface_build_rel] if (target_root / interface_build_rel).is_file() else []
    for rel_path in collect_gn_quoted_file_rels(
        target_root,
        [interface_build_rel],
        [
            "base/web/webview/copy_files.py",
            "base/web/webview/web_aafwk.gni",
        ],
        {
            "webview_path": "//base/web/webview",
            "webview_root_path": "//base/web/webview",
        },
    ):
        if rel_path not in collected:
            collected.append(rel_path)
    return collected


def webview_glue_prepare_input_dirs() -> list[str]:
    return [
        "base/web/webview/ohos_interface/include/ohos_nweb",
        "base/web/webview/ohos_interface/ohos_glue/base",
        "base/web/webview/ohos_interface/ohos_glue/scripts",
        "base/web/webview/ohos_interface/ohos_glue/ohos_nweb/include",
        "base/web/webview/ohos_interface/ohos_glue/ohos_nweb/bridge/webview",
        "base/web/webview/ohos_interface/ohos_glue/ohos_nweb/cpptoc/webview",
        "base/web/webview/ohos_interface/ohos_glue/ohos_nweb/ctocpp/webview",
    ]


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
            if path.name.endswith(".so") or ".so." in path.name:
                actions.append(
                    generated_fake_shared_library_action(
                        rel_path,
                        fake_role,
                        phase,
                        (
                            "Create a target-architecture compile-only shared-library stub for "
                            "a non-text target payload referenced by the target module closure."
                        ),
                        f"shared-library target payload {rel_path}",
                        str(path),
                    )
                )
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


def llvm_readelf_path(workspace: Path) -> Path:
    return workspace / "prebuilts/clang/ohos/linux-x86_64/llvm/bin/llvm-readelf"


def ohos_clang_path(workspace: Path) -> Path:
    return workspace / "prebuilts/clang/ohos/linux-x86_64/llvm/bin/clang"


def normalize_elf_symbol_name(name: str) -> str:
    name = name.strip()
    if "@" in name:
        name = name.split("@", 1)[0]
    return name


def is_c_identifier(name: str) -> bool:
    return bool(re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", name))


def collect_defined_dynsym_symbols(workspace: Path, shared_library: Path) -> list[dict[str, Any]]:
    readelf = llvm_readelf_path(workspace)
    if not readelf.is_file() or not shared_library.is_file():
        return []
    try:
        proc = subprocess.run(
            [str(readelf), "--dyn-syms", "--wide", str(shared_library)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            errors="ignore",
            timeout=30,
            check=False,
        )
    except Exception:
        return []
    if proc.returncode != 0:
        return []
    symbols: list[dict[str, Any]] = []
    seen: set[str] = set()
    for line in proc.stdout.splitlines():
        parts = line.split()
        if len(parts) < 8 or not parts[0].rstrip(":").isdigit():
            continue
        symbol_type = parts[3]
        bind = parts[4]
        ndx = parts[6]
        raw_name = " ".join(parts[7:])
        name = normalize_elf_symbol_name(raw_name)
        if (
            not name
            or name in seen
            or ndx == "UND"
            or bind not in {"GLOBAL", "WEAK"}
            or symbol_type not in {"FUNC", "OBJECT", "NOTYPE"}
            or not is_c_identifier(name)
        ):
            continue
        try:
            size = int(parts[2])
        except ValueError:
            size = 0
        seen.add(name)
        symbols.append({"name": name, "type": symbol_type, "size": size})
    return symbols


def fake_shared_library_c_source(symbols: list[dict[str, Any]], source_path: Path) -> str:
    lines = [
        "/* Auto-generated compile-only OpenHarmony porting shared-library stub.",
        f" * Reference dependency: {source_path}",
        " * Runtime implementation is intentionally absent.",
        " */",
        "__attribute__((visibility(\"default\"))) long __openharmony_porting_fake_shared_library_marker(void) { return 0; }",
    ]
    for index, symbol in enumerate(symbols):
        name = clean_str(symbol.get("name"), "")
        if not is_c_identifier(name):
            continue
        symbol_type = clean_str(symbol.get("type"), "NOTYPE")
        try:
            size = int(symbol.get("size") or 0)
        except (TypeError, ValueError):
            size = 0
        if symbol_type == "OBJECT":
            object_size = min(max(size, 8), 4096)
            lines.append(
                f"__attribute__((visibility(\"default\"))) unsigned char {name}[{object_size}] = {{0}};"
            )
            continue
        lines.append(f"__attribute__((visibility(\"default\"))) long {name}(void) {{ return 0; }}")
        if index >= 2000:
            break
    return "\n".join(lines) + "\n"


def fake_shared_library_riscv64_asm_source(symbols: list[dict[str, Any]], source_path: Path) -> str:
    lines = [
        "# Auto-generated compile-only OpenHarmony porting shared-library stub.",
        f"# Reference dependency: {source_path}",
        "# Runtime implementation is intentionally absent.",
        ".text",
        ".globl __openharmony_porting_fake_shared_library_marker",
        ".type __openharmony_porting_fake_shared_library_marker,@function",
        "__openharmony_porting_fake_shared_library_marker:",
        "    li a0, 0",
        "    ret",
        ".size __openharmony_porting_fake_shared_library_marker, .-__openharmony_porting_fake_shared_library_marker",
    ]
    for symbol in symbols:
        name = clean_str(symbol.get("name"), "")
        if not is_c_identifier(name):
            continue
        symbol_type = clean_str(symbol.get("type"), "NOTYPE")
        try:
            size = int(symbol.get("size") or 0)
        except (TypeError, ValueError):
            size = 0
        if symbol_type == "OBJECT":
            object_size = min(max(size, 8), 4096)
            lines.extend(
                [
                    ".data",
                    f".globl {name}",
                    f".type {name},@object",
                    f".size {name}, {object_size}",
                    f"{name}:",
                    f"    .zero {object_size}",
                ]
            )
            continue
        lines.extend(
            [
                ".text",
                f".globl {name}",
                f".type {name},@function",
                f"{name}:",
                "    li a0, 0",
                "    ret",
                f".size {name}, .-{name}",
            ]
        )
    return "\n".join(lines) + "\n"


def fake_shared_library_source(
    symbols: list[dict[str, Any]],
    source_path: Path,
    target: dict[str, str],
) -> tuple[str, str]:
    if clean_str(target.get("architecture"), "") == "riscv64":
        return fake_shared_library_riscv64_asm_source(symbols, source_path), "assembler"
    return fake_shared_library_c_source(symbols, source_path), "c"


def target_clang_flags(target: dict[str, str]) -> list[str]:
    arch = clean_str(target.get("architecture"), "")
    if arch == "riscv64":
        return ["--target=riscv64-linux-ohos", "-march=rv64imafdc", "-mabi=lp64d"]
    if arch in {"arm64", "aarch64"}:
        return ["--target=aarch64-linux-ohos"]
    if arch in {"arm", "arm32"}:
        return ["--target=arm-linux-ohos"]
    if arch in {"x86_64", "amd64"}:
        return ["--target=x86_64-linux-ohos"]
    return []


def generate_fake_shared_library_bytes(
    workspace: Path,
    target: dict[str, str],
    rel_path: str,
    source_path: Path,
) -> tuple[bytes | None, list[str]]:
    clang = ohos_clang_path(workspace)
    if not clang.is_file():
        return None, [f"fake shared-library generation failed: missing clang at {clang}"]
    symbols = collect_defined_dynsym_symbols(workspace, source_path)
    source, source_lang = fake_shared_library_source(symbols, source_path, target)
    with tempfile.TemporaryDirectory(prefix="ohos_fake_shared_lib_") as tmpdir:
        tmp = Path(tmpdir)
        src = tmp / ("fake_shared_library.S" if source_lang == "assembler" else "fake_shared_library.c")
        out = tmp / Path(rel_path).name
        src.write_text(source, encoding=TEXT_ENCODING)
        cmd = [
            str(clang),
            *target_clang_flags(target),
            "-x",
            source_lang,
            "-fno-builtin",
            "-shared",
            "-fPIC",
            "-nostdlib",
            "-fuse-ld=lld",
            "-Wl,--build-id=none",
            f"-Wl,-soname,{Path(rel_path).name}",
            str(src),
            "-o",
            str(out),
        ]
        try:
            proc = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                errors="ignore",
                timeout=60,
                check=False,
            )
        except Exception as exc:
            return None, [f"fake shared-library generation failed: {exc}"]
        if proc.returncode != 0 or not out.is_file():
            detail = (proc.stderr or proc.stdout or "unknown compiler failure").strip().splitlines()
            return None, ["fake shared-library generation failed"] + detail[:6]
        return out.read_bytes(), [
            "generated target-architecture compile-only shared-library stub",
            f"stubbed exported symbols from reference dynsym: {len(symbols)}",
        ]


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


def target_has_riscv64_rust_toolchain_evidence(target_root: Path) -> bool:
    target_toolchain = target_root / "build/rust/rustc_toolchain.gni"
    target_ohos_toolchain = target_root / "build/toolchain/ohos/BUILD.gn"
    if not target_toolchain.is_file() or not target_ohos_toolchain.is_file():
        return False
    toolchain_text = target_toolchain.read_text(encoding=TEXT_ENCODING, errors="ignore")
    ohos_toolchain_text = target_ohos_toolchain.read_text(encoding=TEXT_ENCODING, errors="ignore")
    return (
        "enable_rust_riscv" in toolchain_text
        and "prebuilts/rustc-riscv" in toolchain_text
        and 'rust_abi_target = "riscv64-unknown-linux-ohos"' in ohos_toolchain_text
    )


def target_has_rust_template_source_forwarding_evidence(target_root: Path) -> bool:
    target_template = target_root / "build/templates/rust/rust_template.gni"
    if not target_template.is_file():
        return False
    text = target_template.read_text(encoding=TEXT_ENCODING, errors="ignore")
    return (
        'target(invoker.target_type, "${target_name}")' in text
        and "rustflags = _rustflags" in text
        and '"sources",' not in text
        and 'target_cpu != "riscv64"' not in text
    )


def target_has_riscv64_buildconfig_arch_evidence(target_root: Path) -> bool:
    target_buildconfig = target_root / "build/config/BUILDCONFIG.gn"
    if not target_buildconfig.is_file():
        return False
    text = target_buildconfig.read_text(encoding=TEXT_ENCODING, errors="ignore")
    return 'if (current_cpu == "riscv64")' in text and 'arch = "riscv64"' in text


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


def target_has_arkcompiler_runtime_riscv64_support_evidence(target_root: Path) -> bool:
    arch_header = target_root / "arkcompiler/runtime_core/static_core/libarkbase/utils/arch.h"
    object_accessor = target_root / "arkcompiler/runtime_core/static_core/runtime/include/object_accessor.h"
    signal_handler = target_root / "arkcompiler/runtime_core/static_core/runtime/signal_handler.h"
    fiber_context = target_root / "arkcompiler/runtime_core/static_core/runtime/fibers/fiber_context.h"
    fiber_layout = target_root / "arkcompiler/runtime_core/static_core/runtime/fibers/arch/riscv64/context_layout.h"
    runtime_build = target_root / "arkcompiler/runtime_core/static_core/runtime/BUILD.gn"
    required = [arch_header, object_accessor, signal_handler, fiber_context, fiber_layout, runtime_build]
    if not all(path.is_file() for path in required):
        return False
    return (
        "Arch::RISCV64" in arch_header.read_text(encoding=TEXT_ENCODING, errors="ignore")
        and "PANDA_TARGET_RISCV64" in signal_handler.read_text(encoding=TEXT_ENCODING, errors="ignore")
        and "fibers/arch/riscv64/get.S" in runtime_build.read_text(encoding=TEXT_ENCODING, errors="ignore")
        and "runtime/fibers/arch/riscv64/context_layout.h"
        in fiber_context.read_text(encoding=TEXT_ENCODING, errors="ignore")
    )


def target_has_arkcompiler_cross_values_riscv64_evidence(target_root: Path) -> bool:
    cross_values_build = target_root / "arkcompiler/runtime_core/static_core/cross_values/BUILD.gn"
    if not cross_values_build.is_file():
        return False
    text = cross_values_build.read_text(encoding=TEXT_ENCODING, errors="ignore")
    return 'current_cpu == "riscv64"' in text and 'arch = "RISCV64"' in text


def target_has_arkcompiler_string_index_riscv64_evidence(target_root: Path) -> bool:
    string_index = target_root / "arkcompiler/runtime_core/static_core/runtime/entrypoints/string_index_of.h"
    if not string_index.is_file():
        return False
    text = string_index.read_text(encoding=TEXT_ENCODING, errors="ignore")
    return "!defined(PANDA_TARGET_RISCV64)" in text and "Unknown target architecture" in text


def target_has_arkcompiler_ets_to_string_cache_riscv64_evidence(target_root: Path) -> bool:
    cache = (
        target_root
        / "arkcompiler/runtime_core/static_core/plugins/ets/runtime/intrinsics/helpers/ets_to_string_cache.cpp"
    )
    if not cache.is_file():
        return False
    text = cache.read_text(encoding=TEXT_ENCODING, errors="ignore")
    return (
        "#if !defined(ARK_HYBRID) && defined(PANDA_32_BIT_MANAGED_POINTER) && defined(PANDA_TARGET_64)"
        in text
        and "std::atomic<Data>::is_always_lock_free" in text
    )


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


def target_has_compile_app_root_ohpm_evidence(target_root: Path) -> bool:
    compile_app = target_root / "build/scripts/compile_app.py"
    if not compile_app.is_file():
        return False
    text = compile_app.read_text(encoding=TEXT_ENCODING, errors="ignore")
    return (
        ("root_dir = get_root_dir()" in text or "root_dir = os.path.abspath(get_root_dir())" in text)
        and 'os.path.join(root_dir, "prebuilts/tool/command-line-tools/ohpm/bin/ohpm")' in text
        and "ohpm_install_cmd = [ohpm_path, 'install']" in text
    )


def target_has_request_rust_cxxbridge_evidence(target_root: Path) -> bool:
    rels = [
        "base/request/request/common/ffrt_rs/src/wrapper.rs",
        "base/request/request/common/database/src/wrapper.rs",
        "base/request/request/common/netstack_rs/src/wrapper.rs",
    ]
    matched = 0
    for rel in rels:
        path = target_root / rel
        if not path.is_file():
            continue
        text = path.read_text(encoding=TEXT_ENCODING, errors="ignore")
        if "#[cxx::bridge" in text and 'extern "Rust"' in text:
            matched += 1
    return matched >= 2


def host_clang_x64_stdlib_fix_actions(workspace: Path) -> list[dict[str, Any]]:
    host_fix = detect_host_cxx_env_fix(workspace)
    include_paths = [clean_str(path, "") for path in host_fix.get("include_paths") or [] if clean_str(path, "")]
    if not include_paths:
        return []
    if not (workspace / "build/toolchain/linux/BUILD.gn").is_file():
        return []
    library_paths = [
        clean_str(path, "") for path in host_fix.get("library_paths") or [] if clean_str(path, "")
    ]
    linux_action = workspace_transform_action(
        "build/toolchain/linux/BUILD.gn",
        "host_clang_x64_cxx_stdlib_paths",
        "L1_host_toolchain_compatibility",
        (
            "Scope detected host GCC C++ standard-library include/library paths to the "
            "linux clang_x64 host toolchain only; this repairs host ArkCompiler tools "
            "without exporting CPLUS_INCLUDE_PATH into riscv64 target compilation."
        ),
    )
    linux_action["host_cxx_include_paths"] = include_paths
    linux_action["host_cxx_library_paths"] = library_paths
    linux_action["host_cxx_probe_validation"] = clean_str(host_fix.get("validation"), "")
    linux_action["dependency_policy"] = "host_toolchain_config"

    forward_action = workspace_transform_action(
        "build/toolchain/gcc_toolchain.gni",
        "clang_toolchain_extra_flags_forwarding",
        "L1_host_toolchain_compatibility",
        (
            "Forward extra_cxxflags/extra_ldflags through the clang_toolchain wrapper so "
            "the host-only clang_x64 stdlib repair variables are consumed instead of "
            "triggering GN 'Assignment had no effect'."
        ),
    )
    forward_action["dependency_policy"] = "host_toolchain_config"
    return [linux_action, forward_action]


def target_compile_standard_whitelist_prefixes(target: dict[str, Any]) -> list[str]:
    vendor = clean_str(target.get("vendor"), "")
    product = clean_str(target.get("product"), "")
    board = clean_str(target.get("board"), "")
    soc_vendor = clean_str(target.get("soc_vendor"), "")
    soc = clean_str(target.get("soc"), "")
    roots = [
        f"//vendor/{vendor}/{product}" if vendor and product else "",
        f"//device/board/{vendor}/{board}" if vendor and board else "",
        f"//device/soc/{soc_vendor}/{soc}" if soc_vendor and soc else "",
    ]
    prefixes: list[str] = []
    for root in roots:
        if not root:
            continue
        prefixes.extend([f"{root}/", f"{root}:"])
    return prefixes


def target_compile_standard_whitelist_contains_label(target_root: Path, label: str) -> bool:
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
        if isinstance(values, list) and label in values:
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


def target_has_profiler_native_daemon_riscv64_evidence(target_root: Path) -> bool:
    header = target_root / "developtools/profiler/device/plugins/native_daemon/include/register.h"
    register_cpp = target_root / "developtools/profiler/device/plugins/native_daemon/src/register.cpp"
    call_stack_cpp = target_root / "developtools/profiler/device/plugins/native_daemon/src/call_stack.cpp"
    if not header.is_file() or not register_cpp.is_file() or not call_stack_cpp.is_file():
        return False
    header_text = header.read_text(encoding=TEXT_ENCODING, errors="ignore")
    register_text = register_cpp.read_text(encoding=TEXT_ENCODING, errors="ignore")
    call_stack_text = call_stack_cpp.read_text(encoding=TEXT_ENCODING, errors="ignore")
    return (
        "target_cpu_riscv64" in header_text
        and "ArchType::ARCH_RISCV64" in header_text
        and "PERF_REG_RISCV64_PC" in header_text
        and "UNW_RISCV_PC" in register_text
        and "PERF_REG_RISCV64_PC" in register_text
        and "target_cpu_riscv64" in call_stack_text
        and "DfxRegsRiscv64" in call_stack_text
    )


def target_has_hiperf_riscv64_evidence(target_root: Path) -> bool:
    header = target_root / "developtools/hiperf/include/register.h"
    register_cpp = target_root / "developtools/hiperf/src/register.cpp"
    callstack_cpp = target_root / "developtools/hiperf/src/callstack.cpp"
    libreport_cpp = target_root / "developtools/hiperf/src/hiperf_libreport.cpp"
    host_perf_header = target_root / "developtools/hiperf/include/nonlinux/linux/perf_event_host.h"
    if not all(path.is_file() for path in [header, register_cpp, callstack_cpp, libreport_cpp, host_perf_header]):
        return False
    header_text = header.read_text(encoding=TEXT_ENCODING, errors="ignore")
    register_text = register_cpp.read_text(encoding=TEXT_ENCODING, errors="ignore")
    callstack_text = callstack_cpp.read_text(encoding=TEXT_ENCODING, errors="ignore")
    libreport_text = libreport_cpp.read_text(encoding=TEXT_ENCODING, errors="ignore")
    host_perf_text = host_perf_header.read_text(encoding=TEXT_ENCODING, errors="ignore")
    return (
        "target_cpu_riscv64" in header_text
        and "ArchType::ARCH_RISCV64" in header_text
        and "PERF_REG_RISCV64_PC" in header_text
        and "PERF_REG_RISCV64_MAX" in header_text
        and "UNW_RISCV_PC" in register_text
        and "PERF_REG_RISCV64_PC" in register_text
        and 'machine == "riscv64"' in register_text
        and "target_cpu_riscv64" in callstack_text
        and "DfxRegsRiscv64" in callstack_text
        and 'machineName = "riscv64"' in libreport_text
        and "PERF_TYPE_HARDWARE" in host_perf_text
    )


def target_has_arkui_napi_riscv64_evidence(target_root: Path) -> bool:
    build_gn = target_root / "foundation/arkui/napi/BUILD.gn"
    cj_support = target_root / ARKUI_NAPI_RISCV64_CJ_SUPPORT_REL
    if not build_gn.is_file() or not cj_support.is_file():
        return False
    build_text = build_gn.read_text(encoding=TEXT_ENCODING, errors="ignore")
    cj_text = cj_support.read_text(encoding=TEXT_ENCODING, errors="ignore")
    return (
        'current_cpu == "riscv64"' in build_text
        and "NAPI_TARGET_RISCV64" in build_text
        and "_RISCV64_" in build_text
        and "NAPI_TARGET_RISCV64" in cj_text
        and 'LIBS_NAME "riscv_64"' in cj_text
        and "ElfOff" in cj_text
        and "ElfEhdr" in cj_text
    )


def target_has_graphic_2d_vsync_riscv64_log_evidence(target_root: Path) -> bool:
    vsync_log = target_root / GRAPHIC_2D_VSYNC_LOG_REL
    if not vsync_log.is_file():
        return False
    text = vsync_log.read_text(encoding=TEXT_ENCODING, errors="ignore")
    return (
        "(defined(__riscv) && __riscv_xlen == 64)" in text
        and '#define VPUBI64  "%{public}ld"' in text
        and '#define VPUBU64  "%{public}lu"' in text
    )


def target_has_lume_static_plugin_riscv64_section_evidence(target_root: Path) -> bool:
    static_plugin_decl = target_root / LUME_STATIC_PLUGIN_DECL_REL
    if not static_plugin_decl.is_file():
        return False
    text = static_plugin_decl.read_text(encoding=TEXT_ENCODING, errors="ignore")
    return (
        "#elif __riscv" in text
        and '#define SECTION(NAME) #NAME",\\"wa\\"\\n .align 3\\n"' in text
        and "SECTION(spl.1)" in text
        and "DEFINE_STATIC_PLUGIN" in text
    )


def target_has_ark_ets_runtime_explicit_thin_lto_evidence(target_root: Path) -> bool:
    build_gn = target_root / ARK_ETS_RUNTIME_BUILD_REL
    if not build_gn.is_file():
        return False
    text = build_gn.read_text(encoding=TEXT_ENCODING, errors="ignore")
    return (
        'if (!is_mac && target_os != "ios" && !use_libfuzzer && !enable_lto_O0)' in text
        and 'cflags_cc += [ "-flto=thin" ]' in text
        and 'ldflags += [ "-flto=thin" ]' in text
        and "PANDA_ENABLE_LTO" in text
    )


def target_has_ark_jsruntime_riscv64_trampoline_evidence(target_root: Path) -> bool:
    build_gn = target_root / ARK_ETS_RUNTIME_BUILD_REL
    trampoline = target_root / ARK_ETS_RUNTIME_RISCV64_TRAMPOLINE_REL
    if not build_gn.is_file() or not trampoline.is_file():
        return False
    build_text = build_gn.read_text(encoding=TEXT_ENCODING, errors="ignore")
    trampoline_text = trampoline.read_text(encoding=TEXT_ENCODING, errors="ignore")
    return (
        'current_cpu == "riscv64"' in build_text
        and "ecmascript/trampoline/riscv64/raw_asm_stub.S" in build_text
        and "LazyDeoptEntryName" in trampoline_text
        and ".global LazyDeoptEntryName" in trampoline_text
    )


def target_has_ark_runtime_riscv64_osr_guard_evidence(target_root: Path) -> bool:
    asm_support = target_root / ARK_RUNTIME_ASM_SUPPORT_CPP_REL
    runtime_build = target_root / "arkcompiler/runtime_core/static_core/runtime/BUILD.gn"
    if not asm_support.is_file() or not runtime_build.is_file():
        return False
    asm_text = asm_support.read_text(encoding=TEXT_ENCODING, errors="ignore")
    build_text = runtime_build.read_text(encoding=TEXT_ENCODING, errors="ignore")
    return (
        "#if !defined(PANDA_TARGET_RISCV64)" in asm_text
        and "OsrEntryAfterCFrame" in asm_text
        and 'current_cpu == "riscv64"' in build_text
        and "arch/riscv64/osr_riscv64.S" in build_text
    )


def target_has_ark_ets_riscv64_bridge_source_evidence(target_root: Path) -> bool:
    subproject_sources = target_root / ARK_ETS_SUBPROJECT_SOURCES_REL
    if not subproject_sources.is_file():
        return False
    text = subproject_sources.read_text(encoding=TEXT_ENCODING, errors="ignore")
    required_text = [
        'srcs_runtime += [ "runtime/interop_js/arch/riscv64/call_bridge_riscv64.S" ]',
        '"runtime/napi/arch/riscv64/ets_napi_entry_point_riscv64.S"',
        '"runtime/napi/arch/riscv64/ets_async_entry_point_riscv64.S"',
        '"runtime/entrypoints/ets_proxy_entrypoints.cpp"',
        '"runtime/entrypoints/arch/riscv64/ets_proxy_entry_point_riscv64.S"',
    ]
    return all(item in text for item in required_text) and all(
        (target_root / rel_path).is_file() for rel_path in ARK_ETS_RISCV64_BRIDGE_SOURCE_RELS
    )


def target_has_skia_raster_pipeline_riscv64_sqrt_evidence(target_root: Path) -> bool:
    opts = target_root / SKIA_RASTER_PIPELINE_OPTS_REL
    if not opts.is_file():
        return False
    text = opts.read_text(encoding=TEXT_ENCODING, errors="ignore")
    return (
        "SI F asin_(F x)" in text
        and "#if defined(__x86_64__)" in text
        and "sqrt_result = std::sqrt(1.0f - x);" in text
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


def workspace_lume_asset_compiler_sources_set_riscv64_float_abi(workspace: Path) -> bool:
    app_path = workspace / "foundation/graphic/graphic_3d/lume/LumeBinaryCompile/lumeassetcompiler/src/app.cpp"
    elf_path = workspace / "foundation/graphic/graphic_3d/lume/LumeBinaryCompile/lumeassetcompiler/src/elf_common.h"
    if not (app_path.is_file() and elf_path.is_file()):
        return False
    app_text = app_path.read_text(encoding=TEXT_ENCODING, errors="ignore")
    elf_text = elf_path.read_text(encoding=TEXT_ENCODING, errors="ignore")
    return (
        "EF_RISCV_FLOAT_ABI_DOUBLE" in elf_text
        and "EF_RISCV_RVC" in elf_text
        and "o.head.e_flags = EF_RISCV_RVC | EF_RISCV_FLOAT_ABI_DOUBLE;" in app_text
    )


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


def generated_riscv64_elf_object_lacks_float_abi(path: Path) -> bool:
    try:
        data = path.read_bytes()[:64]
    except OSError:
        return False
    if len(data) < 52 or data[:4] != b"\x7fELF" or data[4] != 2 or data[5] != 1:
        return False
    machine = int.from_bytes(data[18:20], "little")
    if machine != 243:
        return False
    flags = int.from_bytes(data[48:52], "little")
    return (flags & 0x0004) == 0


def workspace_fake_rust_driver_enabled(workspace: Path) -> bool:
    rustc = workspace / "prebuilts/rustc-riscv/linux-x86_64/current/bin/rustc"
    if not rustc.is_file():
        return False
    try:
        data = rustc.read_bytes()
    except OSError:
        return False
    return b"Compile-only fake rustc/clippy-driver" in data


def rust_archive_path_suggests_fake_driver_output(path: Path) -> bool:
    rel = path.as_posix()
    return (
        "/rust/" in rel
        or "/rustc_" in rel
        or "/rust_" in rel
        or path.name.startswith("librust_")
        or path.suffix == ".rlib"
    )


def archive_contains_non_riscv_elf_objects(workspace: Path, archive: Path) -> bool:
    readelf = llvm_readelf_path(workspace)
    if not readelf.is_file() or not archive.is_file():
        return False
    try:
        proc = subprocess.run(
            [str(readelf), "-h", str(archive)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            errors="ignore",
            timeout=30,
            check=False,
        )
    except Exception:
        return False
    text = proc.stdout + proc.stderr
    if "File format not recognized" in text or "current ar archive" not in text and "File:" not in text:
        return False
    machines = re.findall(r"Machine:\s+(.+)", text)
    if not machines:
        return False
    return any("RISC-V" not in machine for machine in machines)


def elf_header_machine(workspace: Path, path: Path) -> str:
    readelf = llvm_readelf_path(workspace)
    if not readelf.is_file() or not path.is_file():
        return ""
    try:
        proc = subprocess.run(
            [str(readelf), "-h", str(path)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            errors="ignore",
            timeout=30,
            check=False,
        )
    except Exception:
        return ""
    text = proc.stdout + proc.stderr
    match = re.search(r"Machine:\s+(.+)", text)
    return match.group(1).strip() if match else ""


def cleanup_stale_fake_rust_archives(workspace: Path, product: str) -> list[dict[str, Any]]:
    cleanups: list[dict[str, Any]] = []
    if not workspace_fake_rust_driver_enabled(workspace):
        return cleanups
    obj_root = (workspace / "out" / product / "obj").resolve()
    workspace_resolved = workspace.resolve()
    if not obj_root.is_dir() or workspace_resolved not in obj_root.parents:
        return cleanups
    candidates: list[Path] = []
    for pattern in ("*.a", "*.rlib"):
        candidates.extend(sorted(obj_root.rglob(pattern)))
    for archive in candidates:
        if not rust_archive_path_suggests_fake_driver_output(archive):
            continue
        archive_resolved = archive.resolve()
        if workspace_resolved not in archive_resolved.parents:
            continue
        if not archive_contains_non_riscv_elf_objects(workspace, archive):
            continue
        archive.unlink()
        cleanups.append(
            {
                "path": str(archive),
                "status": "removed",
                "reason": "stale Rust archive contained non-RISC-V ELF objects while compile-only rustc-riscv fake driver is active",
            }
        )
    return cleanups


def cleanup_stale_fake_rust_build_scripts(workspace: Path, product: str) -> list[dict[str, Any]]:
    cleanups: list[dict[str, Any]] = []
    if not workspace_fake_rust_driver_enabled(workspace):
        return cleanups
    out_root = (workspace / "out" / product).resolve()
    workspace_resolved = workspace.resolve()
    if not out_root.is_dir() or workspace_resolved not in out_root.parents:
        return cleanups
    for script in sorted(out_root.rglob("*build_script")):
        if not script.is_file():
            continue
        script_resolved = script.resolve()
        if workspace_resolved not in script_resolved.parents:
            continue
        machine = elf_header_machine(workspace, script)
        if "RISC-V" not in machine:
            continue
        script.unlink()
        cleanups.append(
            {
                "path": str(script),
                "status": "removed",
                "reason": "stale Rust cargo build script was a RISC-V ELF but must execute on the host while the fake rustc-riscv driver is active",
            }
        )
    return cleanups


def cleanup_stale_mmi_fake_rust_key_library(workspace: Path, product: str) -> list[dict[str, Any]]:
    cleanups: list[dict[str, Any]] = []
    if not workspace_fake_rust_driver_enabled(workspace):
        return cleanups
    candidates = [
        workspace / "out" / product / "lib.unstripped/multimodalinput/input/libmmi_rust_key_config.z.so",
        workspace / "out" / product / "multimodalinput/input/libmmi_rust_key_config.z.so",
    ]
    workspace_resolved = workspace.resolve()
    for library in candidates:
        if not library.is_file():
            continue
        library_resolved = library.resolve()
        if workspace_resolved not in library_resolved.parents:
            continue
        symbols = {item.get("name") for item in collect_defined_dynsym_symbols(workspace, library)}
        if "ReadConfigInfo" in symbols:
            continue
        library.unlink()
        cleanups.append(
            {
                "path": str(library),
                "status": "removed",
                "reason": "stale fake Rust MMI key shared library did not export ReadConfigInfo after no_mangle symbol extraction was enabled",
            }
        )
    return cleanups


def cleanup_stale_mmi_fake_rust_motion_library(workspace: Path, product: str) -> list[dict[str, Any]]:
    cleanups: list[dict[str, Any]] = []
    if not workspace_fake_rust_driver_enabled(workspace):
        return cleanups
    required_symbols = {
        "HandleMotionDynamicAccelerateMouse",
        "HandleMotionAccelerateMouse",
        "HandleMotionDynamicAccelerateTouchpad",
        "HandleMotionAccelerateTouchpad",
        "HandleAxisAccelerateTouchpad",
    }
    candidates = [
        workspace / "out" / product / "lib.unstripped/multimodalinput/input/libmmi_rust.z.so",
        workspace / "out" / product / "multimodalinput/input/libmmi_rust.z.so",
    ]
    workspace_resolved = workspace.resolve()
    for library in candidates:
        if not library.is_file():
            continue
        library_resolved = library.resolve()
        if workspace_resolved not in library_resolved.parents:
            continue
        symbols = {clean_str(item.get("name"), "") for item in collect_defined_dynsym_symbols(workspace, library)}
        missing = sorted(required_symbols - symbols)
        if not missing:
            continue
        library.unlink()
        cleanups.append(
            {
                "path": str(library),
                "status": "removed",
                "reason": (
                    "stale fake Rust MMI motion shared library did not export "
                    + ", ".join(missing)
                    + " after no_mangle symbol extraction was enabled"
                ),
            }
        )
    return cleanups


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


def target_has_ffrt_riscv64_stack_magic_evidence(target_root: Path) -> bool:
    header = target_root / "foundation/resourceschedule/ffrt/include/eu/co_routine.h"
    if not header.is_file():
        return False
    text = header.read_text(encoding=TEXT_ENCODING, errors="ignore")
    return (
        "constexpr size_t STACK_MAGIC = 0x7BCDABCDABCDABCD;" in text
        and "#elif defined(__riscv) && __riscv_xlen == 64" in text
    )


def target_has_ffrt_riscv64_task_client_adapter_evidence(target_root: Path) -> bool:
    header = target_root / "foundation/resourceschedule/ffrt/src/sched/task_client_adapter.h"
    if not header.is_file():
        return False
    text = header.read_text(encoding=TEXT_ENCODING, errors="ignore")
    return (
        "#if defined(__aarch64__) || defined(__arm__) || (defined(__riscv) && __riscv_xlen == 64)" in text
        and "CTC_QueryIntervalFunc" in text
        and "CTC_QUERY_INTERVAL" in text
    )


def target_has_cj_environment_riscv64_evidence(target_root: Path) -> bool:
    build_gn = target_root / "foundation/ability/ability_runtime/cj_environment/frameworks/cj_environment/BUILD.gn"
    source = target_root / "foundation/ability/ability_runtime/cj_environment/frameworks/cj_environment/src/cj_environment.cpp"
    if not (build_gn.is_file() and source.is_file()):
        return False
    build_text = build_gn.read_text(encoding=TEXT_ENCODING, errors="ignore")
    source_text = source.read_text(encoding=TEXT_ENCODING, errors="ignore")
    return (
        'target_cpu == "riscv64"' in build_text
        and '"APP_USE_RISCV64"' in build_text
        and "APP_USE_RISCV64" in source_text
        and '#define APP_LIB_NAME "riscv64"' in source_text
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


def target_has_hidumper_memory_raw_param_standalone_evidence(target_root: Path) -> bool:
    target_build = target_root / "base/hiviewdfx/hidumper/services/BUILD.gn"
    target_raw_param = target_root / "base/hiviewdfx/hidumper/services/native/src/raw_param.cpp"
    if not target_build.is_file() or not target_raw_param.is_file():
        return False
    build_text = target_build.read_text(encoding=TEXT_ENCODING, errors="ignore")
    raw_text = target_raw_param.read_text(encoding=TEXT_ENCODING, errors="ignore")
    return (
        'ohos_source_set("hidumpermemory_source")' in build_text
        and '"native/src/raw_param.cpp"' in build_text
        and '"${hidumper_service_path}:zidl_config"' in build_text
        and "HIDUMPER_RAW_PARAM_STANDALONE" in build_text
        and "#ifndef HIDUMPER_RAW_PARAM_STANDALONE" in raw_text
        and 'DumpDelayedSpSingleton<DumpManagerService>::GetInstance()' in raw_text
    )


def target_has_mmi_rust_motion_no_mangle_evidence(target_root: Path) -> bool:
    target_lib = target_root / "foundation/multimodalinput/input/service/rust/src/lib.rs"
    if not target_lib.is_file():
        return False
    text = target_lib.read_text(encoding=TEXT_ENCODING, errors="ignore")
    required = {
        "HandleMotionDynamicAccelerateMouse",
        "HandleMotionAccelerateMouse",
        "HandleMotionDynamicAccelerateTouchpad",
        "HandleMotionAccelerateTouchpad",
        "HandleAxisAccelerateTouchpad",
    }
    return all(f"fn {name}" in text and "#[no_mangle]" in text for name in required)


def target_has_tee_riscv64_barrier_evidence(target_root: Path) -> bool:
    for rel_path in TEE_RISCV64_BARRIER_SOURCE_RELS:
        target_source = target_root / rel_path
        if not target_source.is_file():
            return False
        text = target_source.read_text(encoding=TEXT_ENCODING, errors="ignore")
        if not (
            "#elif defined(__riscv)" in text
            and '__asm__ volatile("fence.i");' in text
            and '__asm__ volatile("fence iorw, iorw");' in text
            and '__asm__ volatile("isb");' in text
            and '__asm__ volatile("dsb sy");' in text
        ):
            return False
    return True


def fake_rust_driver_script() -> str:
    return """#!/usr/bin/env python3
# Compile-only fake rustc/clippy-driver for missing riscv64 Rust prebuilts.
# It emits minimal RISC-V ELF placeholders so C/C++ porting can continue to
# the next real blocker. Replace rustc-riscv before runtime/package validation.
import pathlib
import re
import shlex
import subprocess
import sys
import tempfile


def find_arg_value(args, name):
    for index, arg in enumerate(args):
        if arg == name and index + 1 < len(args):
            return args[index + 1]
        if arg.startswith(name + "="):
            return arg.split("=", 1)[1]
    return None


def expand_response_args(args):
    expanded = []
    for arg in args:
        if not arg.startswith("@"):
            expanded.append(arg)
            continue
        rsp = pathlib.Path(arg[1:])
        if not rsp.is_absolute():
            rsp = pathlib.Path.cwd() / rsp
        try:
            expanded.extend(shlex.split(rsp.read_text(encoding="utf-8", errors="ignore")))
        except OSError:
            expanded.append(arg)
    return expanded


def find_emit_depfile(args):
    for arg in args:
        if not arg.startswith("--emit="):
            continue
        for item in arg.split("=", 1)[1].split(","):
            if item.startswith("dep-info="):
                return item.split("=", 1)[1]
    return None


def find_workspace_root():
    cwd = pathlib.Path.cwd().resolve()
    for candidate in [cwd, *cwd.parents]:
        clang = candidate / "prebuilts/clang/ohos/linux-x86_64/llvm/bin/clang"
        if clang.is_file():
            return candidate
    return cwd


def crate_type(args):
    value = find_arg_value(args, "--crate-type")
    if value:
        return value
    for arg in args:
        if arg.startswith("--crate-type="):
            return arg.split("=", 1)[1]
    return ""


def crate_name(args):
    value = find_arg_value(args, "--crate-name")
    return value or ""


def target_triple(args):
    value = find_arg_value(args, "--target")
    if value:
        return value
    for arg in args:
        if arg.startswith("--target="):
            return arg.split("=", 1)[1]
    return "riscv64-unknown-linux-ohos"


def rust_source_paths(args):
    paths = []
    cwd = pathlib.Path.cwd()
    for arg in args:
        if not arg.endswith(".rs"):
            continue
        path = pathlib.Path(arg)
        if not path.is_absolute():
            path = cwd / path
        path = path.resolve()
        if path.is_file():
            paths.append(path)
            src_dir = path.parent
            paths.extend(sorted(src_dir.rglob("*.rs")))
    unique = []
    seen = set()
    for path in paths:
        if path in seen:
            continue
        seen.add(path)
        unique.append(path)
    return unique


def is_build_script(args, output):
    kind = crate_type(args)
    if kind and kind != "bin":
        return False
    name = crate_name(args)
    out_name = pathlib.Path(output).name
    if name.endswith("_build_script") or out_name.endswith("_build_script"):
        return True
    return any(path.name == "build.rs" for path in rust_source_paths(args))


def collect_no_mangle_symbols(args):
    symbols = []
    seen = set()
    pattern = re.compile(
        r"#\\s*\\[\\s*no_mangle\\s*\\]\\s*(?:\\n\\s*#\\[[^\\n]+\\]\\s*)*\\n\\s*"
        r"(?:pub\\s+)?(?:unsafe\\s+)?extern(?:\\s+\\\"C\\\")?\\s+fn\\s+([A-Za-z_][A-Za-z0-9_]*)",
        re.MULTILINE,
    )
    for path in rust_source_paths(args):
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for match in pattern.finditer(text):
            name = match.group(1)
            if name in seen:
                continue
            seen.add(name)
            symbols.append(name)
    return symbols


def fake_rust_c_source(args):
    symbols = collect_no_mangle_symbols(args)
    lines = [
        "/* Compile-only fake Rust staticlib generated by the OpenHarmony porting assistant. */",
        "#include <stdint.h>",
        "__attribute__((visibility(\\\"default\\\"))) uintptr_t __ohos_fake_rust_dependency(void) { return 0; }",
    ]
    for name in symbols:
        lines.append(f"__attribute__((visibility(\\\"default\\\"))) uintptr_t {name}(void) {{ return 0; }}")
    return "\\n".join(lines) + "\\n"


def write_depfile(path, output):
    if not path:
        return
    dep = pathlib.Path(path)
    dep.parent.mkdir(parents=True, exist_ok=True)
    dep.write_text(f"{output}:\\n", encoding="utf-8")


def compile_placeholder(output, args):
    out = pathlib.Path(output)
    out.parent.mkdir(parents=True, exist_ok=True)
    root = find_workspace_root()
    clang = root / "prebuilts/clang/ohos/linux-x86_64/llvm/bin/clang"
    ar = root / "prebuilts/clang/ohos/linux-x86_64/llvm/bin/llvm-ar"
    kind = crate_type(args)
    target = target_triple(args)
    if is_build_script(args, output):
        target = "x86_64-unknown-linux-gnu"
    with tempfile.TemporaryDirectory() as tmpdir:
        src = pathlib.Path(tmpdir) / "fake_rust.c"
        obj = pathlib.Path(tmpdir) / "fake_rust.o"
        src.write_text(fake_rust_c_source(args), encoding="utf-8")
        if target == "x86_64-unknown-linux-gnu":
            base = [str(clang), "--target=x86_64-unknown-linux-gnu", "-fPIC", "-fno-builtin"]
        else:
            base = [
                str(clang),
                "--target=riscv64-linux-ohos",
                "-march=rv64imafdc",
                "-mabi=lp64d",
                "-fPIC",
                "-fno-builtin",
            ]
        if out.suffix in {".a", ".rlib"} or kind in {"rlib", "staticlib"}:
            subprocess.check_call([*base, "-c", str(src), "-o", str(obj)])
            subprocess.check_call([str(ar), "crs", str(out), str(obj)])
        elif out.suffix == ".so" or kind in {"cdylib", "dylib", "proc-macro"}:
            command = [*base, "-shared", str(src), "-Wl,-soname," + out.name, "-o", str(out)]
            if target != "x86_64-unknown-linux-gnu":
                command.insert(len(base) + 1, "-nostdlib")
            subprocess.check_call(command)
        else:
            entry = pathlib.Path(tmpdir) / "fake_rust_entry.c"
            if target == "x86_64-unknown-linux-gnu":
                entry.write_text("int main(void) { return 0; }\\n", encoding="utf-8")
                subprocess.check_call([*base, str(entry), "-o", str(out)])
            else:
                entry.write_text("void __ohos_fake_rust_entry(void) { for (;;) {} }\\n", encoding="utf-8")
                subprocess.check_call([*base, "-nostdlib", str(entry), "-Wl,-e,__ohos_fake_rust_entry", "-o", str(out)])


def main():
    args = expand_response_args(sys.argv[1:])
    if args and args[0].endswith("rustc"):
        args = args[1:]
    output = find_arg_value(args, "-o")
    if output:
        compile_placeholder(output, args)
    depfile = find_emit_depfile(args)
    if depfile and output:
        write_depfile(depfile, output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
"""


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

    if clean_str(seed.get("architecture")) == "riscv64" and target_has_riscv64_buildconfig_arch_evidence(target_root):
        actions.append(
            workspace_transform_action(
                "build/config/BUILDCONFIG.gn",
                "riscv64_buildconfig_arch_mapping",
                "L1_build_compatibility",
                (
                    "Add the target-evidenced riscv64 arch mapping so board/toolchain-derived "
                    "target triples do not fall back to arm defaults."
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

    if clean_str(seed.get("architecture")) == "riscv64" and target_has_riscv64_rust_toolchain_evidence(target_root):
        actions.append(
            target_source_transform_action(
                "build/rust/rustc_toolchain.gni",
                "rust_riscv64_toolchain_gni",
                "L1_build_compatibility",
                (
                    "Import the target-evidenced rustc-riscv toolchain selection and keep host "
                    "Rust tools on the normal x86 Rust prebuilt while riscv64 targets use rustc-riscv."
                ),
            )
        )
        actions.append(
            workspace_transform_action(
                "build/toolchain/ohos/BUILD.gn",
                "ohos_toolchain_riscv64_rust_abi_target",
                "L1_build_compatibility",
                (
                    "Switch the riscv64 OHOS toolchain Rust target from the GNU tuple to the "
                    "target-evidenced riscv64-unknown-linux-ohos tuple."
                ),
            )
        )
        for rel_path, role in [
            (
                "prebuilts/rustc-riscv/linux-x86_64/current/bin/rustc",
                "rust_riscv64_fake_rustc_driver",
            ),
            (
                "prebuilts/rustc-riscv/linux-x86_64/current/bin/clippy-driver",
                "rust_riscv64_fake_clippy_driver",
            ),
        ]:
            action = generated_fake_interface_action(
                rel_path,
                role,
                "L2_external_dependency_stub",
                (
                    "Create a compile-only fake Rust driver for the missing riscv64 rustc-riscv "
                    "prebuilt; it emits minimal placeholder ELF outputs while preserving dependency debt."
                ),
                fake_rust_driver_script(),
                "riscv64 rustc-riscv compiler prebuilt",
                str(target_root / rel_path),
                "replace with provenance-checked prebuilts/rustc-riscv toolchain before Rust/runtime validation",
            )
            action["force_executable"] = True
            actions.append(action)

    if clean_str(seed.get("architecture")) == "riscv64" and target_has_rust_template_source_forwarding_evidence(target_root):
        actions.append(
            workspace_transform_action(
                "build/templates/rust/rust_template.gni",
                "rust_template_restore_source_forwarding",
                "L1_build_compatibility",
                (
                    "Restore the target-evidenced Rust template source/rustflags forwarding for "
                    "riscv64. This removes an earlier compile-triage guard that suppressed Rust "
                    "sources and caused GN to reject crate_type assignments as unused."
                ),
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

    if clean_str(seed.get("architecture")) == "riscv64" and target_has_arkcompiler_runtime_riscv64_support_evidence(target_root):
        for rel_path, role, reason in [
            (
                "arkcompiler/runtime_core/static_core/libpandabase/utils/arch.h",
                "arkcompiler_runtime_riscv64_arch_traits",
                "Add target-evidenced RISC-V runtime Arch enum, ArchTraits, masks, string mapping, and RUNTIME_ARCH selection.",
            ),
            (
                "arkcompiler/runtime_core/static_core/runtime/arch/helpers.h",
                "arkcompiler_runtime_riscv64_ext_arch_traits",
                "Add target-evidenced RISC-V runtime argument/register extension traits.",
            ),
            (
                "arkcompiler/runtime_core/static_core/runtime/arch/memory_helpers.h",
                "arkcompiler_runtime_riscv64_memory_helpers",
                "Route runtime memory helpers to the target-evidenced RISC-V memory helper header.",
            ),
            (
                "arkcompiler/runtime_core/static_core/runtime/arch/asm_support.h",
                "arkcompiler_runtime_riscv64_asm_support",
                "Add target-evidenced RISC-V THREAD_REG and MAKE_ASM_NAME assembly support.",
            ),
            (
                "arkcompiler/runtime_core/static_core/runtime/fibers/fiber_context.h",
                "arkcompiler_runtime_riscv64_fiber_context",
                "Include the target-evidenced RISC-V fiber context layout instead of hitting Unsupported target.",
            ),
            (
                "arkcompiler/runtime_core/static_core/runtime/fibers/arch/asm_macros.h",
                "arkcompiler_runtime_riscv64_fiber_asm_macros",
                "Add target-evidenced RISC-V fiber assembly alignment macros.",
            ),
            (
                "arkcompiler/runtime_core/static_core/runtime/signal_handler.h",
                "arkcompiler_runtime_riscv64_signal_context",
                "Add target-evidenced RISC-V ucontext PC/SP/FP/LR mappings.",
            ),
            (
                "arkcompiler/runtime_core/static_core/runtime/include/object_accessor.h",
                "arkcompiler_runtime_riscv64_object_accessor_overlap_guard",
                "Avoid duplicate ObjectPointerType/coretypes::TaggedType overloads when RISC-V uses the same pointer representation.",
            ),
            (
                "arkcompiler/runtime_core/static_core/runtime/BUILD.gn",
                "arkcompiler_runtime_riscv64_build_sources",
                "Add target-evidenced RISC-V runtime arch, bridge, and fiber assembly sources.",
            ),
        ]:
            actions.append(workspace_transform_action(rel_path, role, "L1_build_compatibility", reason))

        for rel_path in [
            "arkcompiler/runtime_core/static_core/runtime/arch/riscv64/call_runtime.S",
            "arkcompiler/runtime_core/static_core/runtime/arch/riscv64/helpers_riscv64.S",
            "arkcompiler/runtime_core/static_core/runtime/arch/riscv64/interpreter_support.S",
            "arkcompiler/runtime_core/static_core/runtime/arch/riscv64/memory.h",
            "arkcompiler/runtime_core/static_core/runtime/arch/riscv64/osr_riscv64.S",
            "arkcompiler/runtime_core/static_core/runtime/arch/riscv64/shorty.S",
            "arkcompiler/runtime_core/static_core/runtime/arch/riscv64/tlab.S",
            "arkcompiler/runtime_core/static_core/runtime/bridge/arch/riscv64/compiled_code_to_interpreter_bridge_dyn_riscv64.S",
            "arkcompiler/runtime_core/static_core/runtime/bridge/arch/riscv64/compiled_code_to_interpreter_bridge_riscv64.S",
            "arkcompiler/runtime_core/static_core/runtime/bridge/arch/riscv64/compiled_code_to_runtime_bridge_riscv64.S",
            "arkcompiler/runtime_core/static_core/runtime/bridge/arch/riscv64/deoptimization_riscv64.S",
            "arkcompiler/runtime_core/static_core/runtime/bridge/arch/riscv64/expand_compiled_code_args_dyn_riscv64.S",
            "arkcompiler/runtime_core/static_core/runtime/bridge/arch/riscv64/interpreter_to_compiled_code_bridge_dyn_riscv64.S",
            "arkcompiler/runtime_core/static_core/runtime/bridge/arch/riscv64/interpreter_to_compiled_code_bridge_riscv64.S",
            "arkcompiler/runtime_core/static_core/runtime/fibers/arch/riscv64/context_layout.h",
            "arkcompiler/runtime_core/static_core/runtime/fibers/arch/riscv64/get.S",
            "arkcompiler/runtime_core/static_core/runtime/fibers/arch/riscv64/helpers.S",
            "arkcompiler/runtime_core/static_core/runtime/fibers/arch/riscv64/switch.S",
            "arkcompiler/runtime_core/static_core/runtime/fibers/arch/riscv64/update.S",
        ]:
            actions.append(
                copy_action(
                    rel_path,
                    "arkcompiler_runtime_riscv64_arch_source",
                    "L1_build_compatibility",
                    "Import target-evidenced RISC-V ArkCompiler runtime assembly/header source needed by the RISC-V build graph.",
                )
            )

    if clean_str(seed.get("architecture")) == "riscv64" and target_has_ark_runtime_riscv64_osr_guard_evidence(target_root):
        actions.append(
            workspace_transform_action(
                ARK_RUNTIME_ASM_SUPPORT_CPP_REL,
                "arkcompiler_runtime_riscv64_osr_fallback_guard",
                "L1_build_compatibility",
                (
                    "Apply the target-evidenced asm_support.cpp OSR fallback guard so the "
                    "C++ UNREACHABLE fallback does not duplicate the riscv64 osr_riscv64.S symbols."
                ),
            )
        )

    if clean_str(seed.get("architecture")) == "riscv64" and target_has_ark_ets_riscv64_bridge_source_evidence(target_root):
        actions.append(
            workspace_transform_action(
                ARK_ETS_SUBPROJECT_SOURCES_REL,
                "arkcompiler_ets_riscv64_bridge_sources",
                "L1_build_compatibility",
                (
                    "Add the target-evidenced ETS RISC-V NAPI entry, interop JS bridge, "
                    "and proxy entry source branches so libarkruntime has the required "
                    "Ets*/JSRuntime* bridge symbols."
                ),
            )
        )
        for rel_path in ARK_ETS_RISCV64_BRIDGE_SOURCE_RELS:
            if rel_path == ARK_ETS_PROXY_ENTRYPOINTS_CPP_REL and workspace_lacks_ark_ets_reflect_proxy_runtime(workspace):
                actions.append(
                    generated_fake_interface_action(
                        rel_path,
                        "arkcompiler_ets_riscv64_proxy_method_compile_only_stub",
                        "L2_source_compatibility_stub",
                        (
                            "Generate a compile-only EtsProxyMethodInvoke bridge because the "
                            "target-evidenced implementation depends on the newer ETS reflection "
                            "runtime API that is absent from the OpenHarmony 6.0 base tree."
                        ),
                        ark_ets_proxy_entrypoints_compile_only_stub(target_root),
                        "Ark ETS reflection proxy runtime API for real EtsProxyMethodInvoke",
                        str(target_root / rel_path),
                        (
                            "replace with a provenance-checked ETS reflection proxy source closure "
                            "before runtime, JS interop proxy, or managed proxy validation"
                        ),
                    )
                )
                continue
            actions.append(
                copy_action(
                    rel_path,
                    "arkcompiler_ets_riscv64_bridge_source",
                    "L1_build_compatibility",
                    (
                        "Import target-evidenced RISC-V ETS NAPI/interop bridge source "
                        "needed by libarkruntime."
                    ),
                )
            )

    if clean_str(seed.get("architecture")) == "riscv64" and target_has_arkcompiler_cross_values_riscv64_evidence(target_root):
        actions.append(
            workspace_transform_action(
                "arkcompiler/runtime_core/static_core/cross_values/BUILD.gn",
                "arkcompiler_cross_values_riscv64_arch",
                "L1_build_compatibility",
                (
                    "Add the target-evidenced RISCV64 arch-name mapping for ArkCompiler "
                    "cross_values generation so the generator receives input, output, and arch-name."
                ),
            )
        )

    if clean_str(seed.get("architecture")) == "riscv64" and target_has_arkcompiler_string_index_riscv64_evidence(target_root):
        actions.append(
            workspace_transform_action(
                "arkcompiler/runtime_core/static_core/runtime/entrypoints/string_index_of.h",
                "arkcompiler_riscv64_string_index_little_endian_guard",
                "L1_build_compatibility",
                (
                    "Add the target-evidenced PANDA_TARGET_RISCV64 little-endian guard exception "
                    "so StringIndexOf SWAR code does not reject riscv64 at compile time."
                ),
            )
        )

    if (
        clean_str(seed.get("architecture")) == "riscv64"
        and target_has_arkcompiler_ets_to_string_cache_riscv64_evidence(target_root)
    ):
        actions.append(
            workspace_transform_action(
                "arkcompiler/runtime_core/static_core/plugins/ets/runtime/intrinsics/helpers/ets_to_string_cache.cpp",
                "arkcompiler_riscv64_ets_to_string_cache_atomic_guard",
                "L1_build_compatibility",
                (
                    "Apply the target-evidenced RISC-V-safe guard around the EtsToStringCache "
                    "lock-free atomic assertion instead of disabling the ETS runtime target."
                ),
            )
        )

    compile_standard_whitelist_prefixes = target_compile_standard_whitelist_prefixes(seed)
    if any(
        target_has_compile_standard_whitelist_prefix_evidence(target_root, prefix)
        for prefix in compile_standard_whitelist_prefixes
    ):
        actions.append(
            workspace_transform_action(
                "build/compile_standard_whitelist.json",
                "target_compile_standard_whitelist_entries",
                "L1_build_compatibility",
                (
                    "Merge only target-evidenced compile-standard whitelist entries for this "
                    "vendor/product, board, and SoC label space so imported targets keep their "
                    "part/subsystem exceptions without hiding product features."
                ),
            )
        )

    if target_has_compile_app_root_ohpm_evidence(target_root):
        actions.append(
            workspace_transform_action(
                "build/scripts/compile_app.py",
                "compile_app_root_ohpm_path_resolution",
                "L1_build_compatibility",
                (
                    "Resolve the ohpm command-line tool from the OpenHarmony source root before "
                    "compile_app.py changes cwd into each app module, so app builds use the real "
                    "workspace prebuilt instead of an app-relative ../../prebuilts path."
                ),
            )
        )

    if clean_str(seed.get("architecture")) == "riscv64" and target_has_request_rust_cxxbridge_evidence(target_root):
        actions.append(
            workspace_transform_action(
                "build/templates/rust/rust_cxxbridge.py",
                "rust_cxxbridge_empty_output_fake_header_fallback",
                "L2_external_dependency_stub",
                (
                    "When the missing riscv64 Rust toolchain forces cxxbridge to be represented by "
                    "a compile-only fake host executable, generate minimal Rust-side opaque type "
                    "headers from the bridge source if cxxbridge returns empty stdout. This keeps "
                    "request Rust/C++ glue compiling while recording the real cxxbridge/Rust "
                    "toolchain as dependency debt."
                ),
            )
        )

    actions.extend(host_clang_x64_stdlib_fix_actions(workspace))

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
                RUN_OBJCOPY_REL,
                "build_scripts_run_objcopy_riscv64_compat",
                "L1_build_compatibility",
                (
                    "Add target-evidenced riscv64 llvm-objcopy output/BFD arch mappings and set "
                    "RISC-V generated object ELF flags to RVC double-float ABI so binary-to-object "
                    "resources can link with lp64d targets."
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

    if clean_str(seed.get("architecture")) == "riscv64" and target_has_ffrt_riscv64_stack_magic_evidence(target_root):
        actions.append(
            workspace_transform_action(
                "foundation/resourceschedule/ffrt/include/eu/co_routine.h",
                "ffrt_riscv64_stack_magic",
                "L1_build_compatibility",
                (
                    "Add the target-evidenced RISC-V STACK_MAGIC branch so FFRT coroutine code "
                    "compiles for riscv64."
                ),
            )
        )

    if clean_str(seed.get("architecture")) == "riscv64" and target_has_ffrt_riscv64_task_client_adapter_evidence(target_root):
        actions.append(
            workspace_transform_action(
                "foundation/resourceschedule/ffrt/src/sched/task_client_adapter.h",
                "ffrt_riscv64_task_client_adapter_ctc_query_interval",
                "L1_build_compatibility",
                (
                    "Add the target-evidenced RISC-V task-client CTC_QUERY_INTERVAL branch so "
                    "FFRT sched code does not hit the unsupported architecture guard."
                ),
            )
        )

    if clean_str(seed.get("architecture")) == "riscv64" and target_has_cj_environment_riscv64_evidence(target_root):
        for rel_path, role, reason in [
            (
                "foundation/ability/ability_runtime/cj_environment/frameworks/cj_environment/BUILD.gn",
                "cj_environment_riscv64_app_define",
                "Add the target-evidenced APP_USE_RISCV64 define for cj_environment.",
            ),
            (
                "foundation/ability/ability_runtime/cj_environment/frameworks/cj_environment/src/cj_environment.cpp",
                "cj_environment_riscv64_app_lib_name",
                "Add the target-evidenced riscv64 app-library subdirectory mapping for cj_environment.",
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

    if clean_str(seed.get("architecture")) == "riscv64" and target_has_arkui_napi_riscv64_evidence(target_root):
        actions.append(
            workspace_transform_action(
                "foundation/arkui/napi/BUILD.gn",
                "arkui_napi_riscv64_target_defines",
                "L1_build_compatibility",
                (
                    "Add target-evidenced NAPI_TARGET_RISCV64/NAPI_TARGET_64 and _RISCV64_ "
                    "defines so ArkUI NAPI CJ support compiles for riscv64."
                ),
            )
        )
        actions.append(
            copy_action(
                ARKUI_NAPI_RISCV64_CJ_SUPPORT_REL,
                "arkui_napi_riscv64_cj_support",
                "L1_build_compatibility",
                (
                    "Import target-evidenced ArkUI NAPI CJ support that maps riscv64 to "
                    "LIBS_NAME \"riscv_64\" and uses architecture-width ELF typedefs."
                ),
            )
        )

    if clean_str(seed.get("architecture")) == "riscv64" and target_has_graphic_2d_vsync_riscv64_log_evidence(target_root):
        actions.append(
            workspace_transform_action(
                GRAPHIC_2D_VSYNC_LOG_REL,
                "graphic_2d_vsync_riscv64_log_format_macros",
                "L1_build_compatibility",
                (
                    "Add the target-evidenced riscv64 LP64 condition to VSync logging format "
                    "macros so uint64_t/int64_t arguments compile with -Werror=format."
                ),
            )
        )

    if clean_str(seed.get("architecture")) == "riscv64" and target_has_lume_static_plugin_riscv64_section_evidence(target_root):
        actions.append(
            workspace_transform_action(
                LUME_STATIC_PLUGIN_DECL_REL,
                "graphic_3d_lume_riscv64_static_plugin_section",
                "L1_build_compatibility",
                (
                    "Add the target-evidenced RISC-V static-plugin section macro branch "
                    "so Lume generated plugin lists assemble with the riscv64 toolchain."
                ),
            )
        )

    if clean_str(seed.get("architecture")) == "riscv64" and target_has_skia_raster_pipeline_riscv64_sqrt_evidence(target_root):
        actions.append(
            workspace_transform_action(
                SKIA_RASTER_PIPELINE_OPTS_REL,
                "skia_raster_pipeline_riscv64_scalar_sqrt_fallback",
                "L1_build_compatibility",
                (
                    "Apply the target-evidenced non-x86 scalar sqrt path in SkRasterPipeline "
                    "so riscv64 does not index scalar fallback values as vectors."
                ),
            )
        )

    if clean_str(seed.get("architecture")) == "riscv64" and target_has_ark_jsruntime_riscv64_trampoline_evidence(target_root):
        actions.append(
            copy_action(
                ARK_ETS_RUNTIME_RISCV64_TRAMPOLINE_REL,
                "ark_jsruntime_riscv64_lazy_deopt_trampoline_source",
                "L1_build_compatibility",
                "Import the target-evidenced RISC-V LazyDeoptEntry trampoline source.",
            )
        )
        actions.append(
            workspace_transform_action(
                ARK_ETS_RUNTIME_BUILD_REL,
                "ark_jsruntime_riscv64_trampoline_source",
                "L1_build_compatibility",
                (
                    "Add the target-evidenced riscv64 raw_asm_stub.S source to Ark JS runtime "
                    "so LazyDeoptEntry is defined during libark_jsruntime linking."
                ),
            )
        )

    if clean_str(seed.get("architecture")) == "riscv64" and target_has_tee_riscv64_barrier_evidence(target_root):
        for rel_path in TEE_RISCV64_BARRIER_SOURCE_RELS:
            actions.append(
                workspace_transform_action(
                    rel_path,
                    "tee_riscv64_barrier_asm_compat",
                    "L1_build_compatibility",
                    (
                        "Replace ARM-only TEE barrier assembly with the target-evidenced "
                        "aarch64/riscv fence branches so teecd agents compile for riscv64."
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
                "third_party/musl/BUILD.gn",
                "riscv64_musl_shared_no_lto_compat",
                "L1_build_compatibility",
                (
                    "Use the existing musl_use_flto knob to disable shared musl LTO on riscv64 "
                    "when lld still emits mixed-ABI lto.tmp objects after all explicit inputs "
                    "carry the target-evidenced lp64d ABI."
                ),
            )
        )
        actions.append(
            workspace_transform_action(
                "third_party/musl/musl_template.gni",
                "riscv64_musl_hook_cflags_mabi_compat",
                "L1_build_compatibility",
                (
                    "Make musl hook LTO objects carry the same target-evidenced -mabi=lp64d "
                    "ABI as the rest of riscv64 musl; otherwise libc.so LTO emits mixed ABI "
                    "lto.tmp objects."
                ),
            )
        )
        actions.append(
            workspace_transform_action(
                "build/config/compiler/BUILD.gn",
                "riscv64_compiler_ldflags_mabi_compat",
                "L1_build_compatibility",
                (
                    "Align riscv64 compiler and linker ABI flags with the target-evidenced "
                    "hard-float ABI when lld reports mixed floating-point ABI objects."
                ),
            )
        )
        actions.append(
            workspace_transform_action(
                "build/config/compiler/compiler.gni",
                "riscv64_disable_thin_lto_compat",
                "L1_build_compatibility",
                (
                    "Disable default ThinLTO for riscv64 on the OpenHarmony 6.0 clang/lld stack "
                    "when lld-generated lto.tmp or thinlto-cache objects do not retain rv64imafdc/lp64d."
                ),
            )
        )
        if target_has_ark_ets_runtime_explicit_thin_lto_evidence(target_root):
            actions.append(
                workspace_transform_action(
                    ARK_ETS_RUNTIME_BUILD_REL,
                    "ark_jsruntime_riscv64_explicit_thin_lto_compat",
                    "L1_build_compatibility",
                    (
                        "Guard Ark JS runtime's explicit -flto=thin block for riscv64, "
                        "because it bypasses the global riscv64 ThinLTO off-ramp."
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

    if target_has_hidumper_memory_raw_param_standalone_evidence(target_root):
        actions.append(
            workspace_transform_action(
                "base/hiviewdfx/hidumper/services/BUILD.gn",
                "hidumper_memory_raw_param_standalone_closure",
                "L2_text_closure",
                (
                    "Add the target-evidenced RawParam text closure to hidumpermemory_source so "
                    "libhidumpermemory exports RawParam progress/output methods without pulling in "
                    "the full DumpManagerService runtime path."
                ),
            )
        )
        actions.append(
            target_source_transform_action(
                "base/hiviewdfx/hidumper/services/native/src/raw_param.cpp",
                "hidumper_raw_param_standalone_guard",
                "L2_text_closure",
                (
                    "Import the target-evidenced RawParam standalone guard that excludes "
                    "DumpManagerService singleton access when raw_param.cpp is compiled into "
                    "hidumpermemory_source."
                ),
            )
        )

    if clean_str(seed.get("architecture")) == "riscv64" and target_has_profiler_native_daemon_riscv64_evidence(target_root):
        for rel_path, role, reason in PROFILER_NATIVE_DAEMON_RISCV64_SOURCE_RELS:
            actions.append(
                copy_action(
                    rel_path,
                    role,
                    "L1_build_compatibility",
                    (
                        reason
                        + " This keeps native_hook/native_daemon building for riscv64 without disabling profiler features."
                    ),
                )
            )

    if clean_str(seed.get("architecture")) == "riscv64" and target_has_hiperf_riscv64_evidence(target_root):
        for rel_path, role, reason in HIPERF_RISCV64_SOURCE_RELS:
            actions.append(
                copy_action(
                    rel_path,
                    role,
                    "L1_build_compatibility",
                    (
                        reason
                        + " This keeps hiperf selected while closing the riscv64 arch support gap with text evidence."
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
        for rel_path in collect_webview_glue_prepare_input_file_rels(target_root):
            if is_text_closure_file(target_root / rel_path):
                actions.append(
                    copy_action(
                        rel_path,
                        "webview_glue_prepare_input_text_closure",
                        "L2_webview_local_module_text_closure",
                        (
                            "Import target WebView ohos_interface BUILD/input files used by "
                            "webview_glue_*_prepare actions so generated glue sources match "
                            "the copied ohos_glue BUILD rules instead of being faked under out/gen."
                        ),
                    )
                )
        actions.extend(
            collect_target_module_closure_actions(
                target_root,
                webview_glue_prepare_input_dirs(),
                "webview_glue_prepare_input_text_closure",
                "webview_glue_prepare_input_fake_payload",
                "L2_webview_local_module_text_closure",
                (
                    "Import the target WebView ohos_interface base/scripts plus nweb include "
                    "and glue input directories that copy_files.py copies into the generated "
                    "ohos_glue tree before translator.py creates the final wrapper/ctocpp outputs."
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
        "TEE riscv64 barrier assembly guards are applied only when target-source evidence contains matching aarch64/riscv fence branches in teecd agents.",
        "SmartPerf split component-registry migration removes legacy hiprofiler-hosted SmartPerf labels only when target evidence shows SmartPerf is owned by smartperf_host.",
        "Vendor product module text/config closures are imported only from direct target ohos.build module labels; non-text payloads become compile-only fake interfaces.",
        "Board module text/config closures are imported only from local labels in the target board root BUILD.gn; kernel modules, bootloader images, and firmware become compile-only fake interfaces.",
        "Board audio_alsa text/source closures are imported when target evidence provides board-specific audio adapter sources required by Ninja.",
        "Missing board BSP kernel source trees may use a tracked fake kernel-source marker plus a build_kernel.sh fake-output bridge so image generation remains visible during dependency triage.",
        "SoC module text/source closures are imported only from target board BUILD.gn labels under the selected SoC root; firmware and proprietary GPU/WiFi/shared-library payloads become compile-only fake interfaces.",
        "WebView local module text/source closures are imported from target ohos_nweb GN labels after resolving webview_path-style variables; binary/prebuilt payloads remain fake-interface debt.",
        "WebView generated glue sources are not faked: target-evidenced ohos_interface BUILD/base/scripts/input files are imported so the existing prepare/translator actions regenerate out/gen sources.",
        "WebView app_fwk_update component-registry labels are migrated to the target sa/app_fwk_update module when target evidence shows the service moved from the old flat sa target.",
        "WebView app_fwk_update test closures are migrated with target evidence when test deps would otherwise keep the old flat sa service in the GN graph.",
        "Hidumper RawParam is added to hidumpermemory only with the target-evidenced standalone guard, avoiding a broader DumpManagerService/plugin source import during compile triage.",
        "MMI Rust fake shared libraries are cleaned and regenerated when target-evidenced #[no_mangle] motion symbols are missing from stale fake-driver outputs.",
        "Hiperf RISC-V support is imported as a target-evidenced text closure for register/callstack/report handling, keeping the hiperf feature selected rather than filtering it out.",
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
    notes: list[str] = []
    anchor = "#define EM_AARCH64 183 /* ARM 64 bit */\n"

    if "EM_RISCV64" not in text:
        if anchor in text:
            text = text.replace(anchor, anchor + "#define EM_RISCV64 243 /* RISCV 64 bit */\n", 1)
            notes.append("added Lume asset compiler EM_RISCV64 id")
        else:
            notes.append("Lume asset compiler EM_RISCV64 insertion point not found")
    else:
        notes.append("Lume asset compiler RISC-V ELF machine id already present")

    if "EF_RISCV_FLOAT_ABI_DOUBLE" not in text:
        riscv_anchor = "#define EM_RISCV64 243 /* RISCV 64 bit */\n"
        riscv_flags = (
            riscv_anchor
            + "#define EF_RISCV_RVC 0x0001\n"
            + "#define EF_RISCV_FLOAT_ABI_DOUBLE 0x0004\n"
        )
        if riscv_anchor in text:
            text = text.replace(riscv_anchor, riscv_flags, 1)
            notes.append("added Lume asset compiler RISC-V ELF double-float ABI flag constants")
        else:
            notes.append("Lume asset compiler RISC-V ELF flag insertion point not found")
    else:
        notes.append("Lume asset compiler RISC-V ELF ABI flag constants already present")

    return text.encode(TEXT_ENCODING), notes


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

    if "o.head.e_flags = EF_RISCV_RVC | EF_RISCV_FLOAT_ABI_DOUBLE;" not in text:
        old = "    o.head.e_machine = arch; // machine id..\n"
        new = (
            old
            + "    if (arch == EM_RISCV64) {\n"
            + "        o.head.e_flags = EF_RISCV_RVC | EF_RISCV_FLOAT_ABI_DOUBLE;\n"
            + "    }\n"
        )
        if old in text:
            text = text.replace(old, new, 1)
            notes.append("set RISC-V generated ELF objects to RVC double-float ABI")
        else:
            notes.append("Lume asset compiler RISC-V ELF e_flags insertion point not found")
    else:
        notes.append("Lume asset compiler RISC-V ELF e_flags already set to double-float ABI")

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

    if '"--elf-flags", "5"' not in text:
        marker = "    ]\n\n    process = subprocess.Popen(\n"
        insertion = (
            "    ]\n\n"
            "    if args.arch == \"riscv64\":\n"
            "        cmd.extend([\"--elf-flags\", \"5\"])\n\n"
            "    process = subprocess.Popen(\n"
        )
        if marker in text:
            text = text.replace(marker, insertion, 1)
            notes.append("set riscv64 binary-to-object ELF flags to RVC double-float ABI")
        else:
            notes.append("riscv64 objcopy ELF flags insertion point not found")
    else:
        notes.append("riscv64 binary-to-object ELF flags already set to double-float ABI")

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


def apply_ffrt_riscv64_stack_magic_compat(data: bytes) -> tuple[bytes, list[str]]:
    text = data.decode(TEXT_ENCODING, errors="ignore")
    if "#elif defined(__riscv) && __riscv_xlen == 64" in text and "STACK_MAGIC = 0x7BCDABCDABCDABCD" in text:
        return data, ["FFRT riscv STACK_MAGIC branch already present"]
    old = "#elif defined(__x86_64__)\nconstexpr size_t STACK_MAGIC = 0x7BCDABCDABCDABCD;\n"
    new = old + "#elif defined(__riscv) && __riscv_xlen == 64\nconstexpr size_t STACK_MAGIC = 0x7BCDABCDABCDABCD;\n"
    if old in text:
        text = text.replace(old, new, 1)
        return text.encode(TEXT_ENCODING), ["added FFRT riscv STACK_MAGIC branch"]
    return data, ["FFRT riscv STACK_MAGIC insertion point not found"]


def apply_ffrt_riscv64_task_client_adapter_compat(data: bytes) -> tuple[bytes, list[str]]:
    text = data.decode(TEXT_ENCODING, errors="ignore")
    riscv_guard = "#if defined(__aarch64__) || defined(__arm__) || (defined(__riscv) && __riscv_xlen == 64)"
    if riscv_guard in text:
        return data, ["FFRT task-client RISC-V CTC_QUERY_INTERVAL branch already present"]
    old = "#if defined(__aarch64__) || defined(__arm__)\n#define CTC_QUERY_INTERVAL"
    new = f"{riscv_guard}\n#define CTC_QUERY_INTERVAL"
    if old in text:
        text = text.replace(old, new, 1)
        return text.encode(TEXT_ENCODING), ["added FFRT task-client RISC-V CTC_QUERY_INTERVAL guard"]
    return data, ["FFRT task-client RISC-V CTC_QUERY_INTERVAL insertion point not found"]


def apply_cj_environment_riscv64_app_define(data: bytes) -> tuple[bytes, list[str]]:
    text = data.decode(TEXT_ENCODING, errors="ignore")
    if '"APP_USE_RISCV64"' in text:
        return data, ["cj_environment APP_USE_RISCV64 define already present"]
    old = '  } else if (target_cpu == "x86_64") {\n    defines += [ "APP_USE_X86_64" ]\n'
    new = old + '  } else if (target_cpu == "riscv64") {\n    defines += [ "APP_USE_RISCV64" ]\n'
    if old in text:
        text = text.replace(old, new, 1)
        return text.encode(TEXT_ENCODING), ["added cj_environment APP_USE_RISCV64 define"]
    return data, ["cj_environment APP_USE_RISCV64 define insertion point not found"]


def apply_cj_environment_riscv64_app_lib_name(data: bytes) -> tuple[bytes, list[str]]:
    text = data.decode(TEXT_ENCODING, errors="ignore")
    if "APP_USE_RISCV64" in text and '#define APP_LIB_NAME "riscv64"' in text:
        return data, ["cj_environment riscv64 APP_LIB_NAME branch already present"]
    old = '#elif defined(NAPI_TARGET_ARM64)\n#define APP_LIB_NAME "arm64"\n'
    new = old + '#elif defined(APP_USE_RISCV64)\n#define APP_LIB_NAME "riscv64"\n'
    if old in text:
        text = text.replace(old, new, 1)
        return text.encode(TEXT_ENCODING), ["added cj_environment riscv64 APP_LIB_NAME branch"]
    return data, ["cj_environment riscv64 APP_LIB_NAME insertion point not found"]


def apply_arkui_napi_riscv64_target_defines(data: bytes) -> tuple[bytes, list[str]]:
    text = data.decode(TEXT_ENCODING, errors="ignore")
    notes: list[str] = []

    if "NAPI_TARGET_RISCV64" in text:
        notes.append("ArkUI NAPI RISC-V NAPI_TARGET_RISCV64 define already present")
    else:
        old = (
            '  } else if (current_cpu == "arm") {\n'
            "    defines += [\n"
            '      "NAPI_TARGET_ARM32",\n'
            '      "NAPI_TARGET_32",\n'
            "    ]\n"
            "  }\n"
        )
        new = (
            '  } else if (current_cpu == "arm") {\n'
            "    defines += [\n"
            '      "NAPI_TARGET_ARM32",\n'
            '      "NAPI_TARGET_32",\n'
            "    ]\n"
            '  } else if (current_cpu == "riscv64") {\n'
            "    defines += [\n"
            '      "NAPI_TARGET_RISCV64",\n'
            '      "NAPI_TARGET_64",\n'
            "    ]\n"
            "  }\n"
        )
        if old in text:
            text = text.replace(old, new, 1)
            notes.append("added ArkUI NAPI RISC-V target defines")
        else:
            notes.append("ArkUI NAPI RISC-V target define insertion point not found")

    if '_RISCV64_' in text:
        notes.append("ArkUI NAPI _RISCV64_ define already present")
    else:
        old = '  if (current_cpu == "arm64") {\n    defines += [ "_ARM64_" ]\n  }\n'
        new = (
            '  if (current_cpu == "arm64") {\n'
            '    defines += [ "_ARM64_" ]\n'
            '  } else if (current_cpu == "riscv64") {\n'
            '    defines += [ "_RISCV64_" ]\n'
            "  }\n"
        )
        if old in text:
            text = text.replace(old, new, 1)
            notes.append("added ArkUI NAPI _RISCV64_ define")
        else:
            notes.append("ArkUI NAPI _RISCV64_ define insertion point not found")

    return text.encode(TEXT_ENCODING), notes or ["ArkUI NAPI RISC-V target defines unchanged"]


def apply_graphic_2d_vsync_riscv64_log_format_macros(data: bytes) -> tuple[bytes, list[str]]:
    text = data.decode(TEXT_ENCODING, errors="ignore")
    riscv_condition = "(defined(__riscv) && __riscv_xlen == 64)"
    if riscv_condition in text:
        return data, ["graphic_2d vsync RISC-V LP64 log-format branch already present"]
    old = "#if (defined(__aarch64__) || defined(__x86_64__))\n"
    new = f"#if (defined(__aarch64__) || defined(__x86_64__) || {riscv_condition})\n"
    if old in text:
        text = text.replace(old, new, 1)
        return text.encode(TEXT_ENCODING), ["added graphic_2d vsync RISC-V LP64 log-format branch"]
    return data, ["graphic_2d vsync RISC-V log-format insertion point not found"]


def apply_lume_static_plugin_riscv64_section_alignment(data: bytes) -> tuple[bytes, list[str]]:
    text = data.decode(TEXT_ENCODING, errors="ignore")
    if "#elif __riscv" in text:
        return data, ["graphic_3d Lume static-plugin RISC-V section branch already present"]
    old = '#if __aarch64__\n#define SECTION(NAME) #NAME",\\"wa\\"\\n .align 3\\n"\n#elif __x86_64__\n'
    new = (
        '#if __aarch64__\n#define SECTION(NAME) #NAME",\\"wa\\"\\n .align 3\\n"\n'
        '#elif __riscv\n#define SECTION(NAME) #NAME",\\"wa\\"\\n .align 3\\n"\n#elif __x86_64__\n'
    )
    if old in text:
        text = text.replace(old, new, 1)
        return text.encode(TEXT_ENCODING), ["added graphic_3d Lume static-plugin RISC-V section branch"]
    return data, ["graphic_3d Lume static-plugin RISC-V section insertion point not found"]


def apply_riscv64_compiler_ldflags_mabi_compat(data: bytes) -> tuple[bytes, list[str]]:
    text = data.decode(TEXT_ENCODING, errors="ignore")
    notes: list[str] = []

    cflags_old = '        cflags += [ "-march=rv64imafdc" ]\n'
    cflags_new = (
        "        cflags += [\n"
        '          "-march=rv64imafdc",\n'
        '          "-mabi=lp64d",\n'
        "        ]\n"
    )
    if cflags_new in text:
        notes.append("riscv64 compiler cflags already carry -mabi=lp64d beside -march=rv64imafdc")
    elif cflags_old in text:
        text = text.replace(cflags_old, cflags_new, 1)
        notes.append("added riscv64 -mabi=lp64d compiler cflag beside -march=rv64imafdc")
    else:
        notes.append("riscv64 compiler cflag mabi insertion point not found")

    ldflags_old = '      ldflags += [ "-march=rv64imafdc" ]\n'
    ldflags_new = (
        "      ldflags += [\n"
        '        "-march=rv64imafdc",\n'
        '        "-mabi=lp64d",\n'
        "      ]\n"
    )
    if ldflags_new in text:
        notes.append("riscv64 linker mabi flag already present next to -march=rv64imafdc")
    elif ldflags_old in text:
        text = text.replace(ldflags_old, ldflags_new, 1)
        notes.append("added riscv64 -mabi=lp64d linker flag beside -march=rv64imafdc")
    else:
        notes.append("riscv64 linker mabi insertion point not found")
    return text.encode(TEXT_ENCODING), notes


def apply_riscv64_disable_thin_lto_compat(data: bytes) -> tuple[bytes, list[str]]:
    text = data.decode(TEXT_ENCODING, errors="ignore")
    guard = (
        '  if (current_cpu == "riscv64") {\n'
        "    # OpenHarmony 6.0 clang/lld can emit ThinLTO temp objects without rv64imafdc/lp64d.\n"
        "    use_thin_lto = false\n"
        "  }\n"
    )
    if guard in text:
        return data, ["riscv64 ThinLTO default is already disabled"]
    anchor = (
        "  if (use_libfuzzer) {\n"
        "    use_thin_lto = is_cfi || (is_ohos_or_android && is_official_build)\n"
        "  } else {\n"
        "    use_thin_lto = is_cfi || is_ohos_or_android\n"
        "  }\n"
    )
    if anchor in text:
        text = text.replace(anchor, anchor + "\n" + guard, 1)
        return text.encode(TEXT_ENCODING), ["disabled default ThinLTO for riscv64"]
    return data, ["riscv64 ThinLTO insertion point not found"]


def apply_ark_jsruntime_riscv64_explicit_thin_lto_compat(data: bytes) -> tuple[bytes, list[str]]:
    text = data.decode(TEXT_ENCODING, errors="ignore")
    if 'current_cpu != "riscv64"' in text and 'cflags_cc += [ "-flto=thin" ]' in text:
        return data, ["Ark JS runtime explicit ThinLTO block is already guarded for riscv64"]
    old = '  if (!is_mac && target_os != "ios" && !use_libfuzzer && !enable_lto_O0) {\n'
    new = (
        '  if (!is_mac && target_os != "ios" && !use_libfuzzer && !enable_lto_O0 &&\n'
        '      current_cpu != "riscv64") {\n'
    )
    if old in text:
        text = text.replace(old, new, 1)
        return text.encode(TEXT_ENCODING), ["guarded Ark JS runtime explicit ThinLTO block for riscv64"]
    return data, ["Ark JS runtime explicit ThinLTO insertion point not found"]


def apply_ark_jsruntime_riscv64_trampoline_source(data: bytes) -> tuple[bytes, list[str]]:
    text = data.decode(TEXT_ENCODING, errors="ignore")
    if "ecmascript/trampoline/riscv64/raw_asm_stub.S" in text:
        return data, ["Ark JS runtime RISC-V trampoline source already present"]
    old = (
        '  } else if (current_cpu == "arm") {\n'
        '    ecma_source += [ "ecmascript/trampoline/arm32/raw_asm_stub.S" ]\n'
        "  }\n"
    )
    new = (
        '  } else if (current_cpu == "arm") {\n'
        '    ecma_source += [ "ecmascript/trampoline/arm32/raw_asm_stub.S" ]\n'
        '  } else if (current_cpu == "riscv64") {\n'
        '    ecma_source += [ "ecmascript/trampoline/riscv64/raw_asm_stub.S" ]\n'
        "  }\n"
    )
    if old in text:
        text = text.replace(old, new, 1)
        return text.encode(TEXT_ENCODING), ["added Ark JS runtime RISC-V trampoline source"]
    return data, ["Ark JS runtime RISC-V trampoline insertion point not found"]


def apply_skia_raster_pipeline_riscv64_scalar_sqrt_fallback(data: bytes) -> tuple[bytes, list[str]]:
    text = data.decode(TEXT_ENCODING, errors="ignore")
    if "#if defined(__x86_64__)" in text and "sqrt_result = std::sqrt(1.0f - x);" in text:
        return data, ["SkRasterPipeline asin sqrt fallback is already guarded for non-x86"]
    old = (
        "    F sqrt_result = { 0.0f };\n"
        "    for (int32_t i = 0; i < 4; ++i) { // 4 is a 4-element vector\n"
        "        sqrt_result[i] = std::sqrt(1.0f - x[i]);\n"
        "    }\n"
    )
    new = (
        "    F sqrt_result = { 0.0f };\n"
        "#if defined(__x86_64__)\n"
        "    for (int i = 0; i < 4; ++i) {\n"
        "        sqrt_result[i] = std::sqrt(1.0f - x[i]);\n"
        "      }\n"
        "#else\n"
        "    sqrt_result = std::sqrt(1.0f - x);\n"
        "#endif\n"
    )
    if old in text:
        text = text.replace(old, new, 1)
        return text.encode(TEXT_ENCODING), ["added SkRasterPipeline non-x86 scalar sqrt fallback"]
    return data, ["SkRasterPipeline scalar sqrt fallback insertion point not found"]


def apply_riscv64_buildconfig_arch_compat(data: bytes) -> tuple[bytes, list[str]]:
    text = data.decode(TEXT_ENCODING, errors="ignore")
    if 'if (current_cpu == "riscv64") {\n    arch = "riscv64"\n  }\n' in text:
        return data, ["riscv64 buildconfig arch mapping already present"]
    old = (
        '  } else if (current_cpu == "riscv32") {\n'
        '    arch = "riscv32"\n'
        '  } else if (current_cpu == "loongarch64") {\n'
    )
    new = (
        '  } else if (current_cpu == "riscv32") {\n'
        '    arch = "riscv32"\n'
        '  } else if (current_cpu == "riscv64") {\n'
        '    arch = "riscv64"\n'
        '  } else if (current_cpu == "loongarch64") {\n'
    )
    if old in text:
        text = text.replace(old, new, 1)
        return text.encode(TEXT_ENCODING), ["added buildconfig riscv64 arch mapping"]
    old_split = (
        '  if (current_cpu == "arm64") {\n'
        '    arch = "aarch64"\n'
        "  }\n\n"
        '  if (current_cpu == "loongarch64") {\n'
    )
    new_split = (
        '  if (current_cpu == "arm64") {\n'
        '    arch = "aarch64"\n'
        "  }\n\n"
        '  if (current_cpu == "riscv64") {\n'
        '    arch = "riscv64"\n'
        "  }\n\n"
        '  if (current_cpu == "loongarch64") {\n'
    )
    if old_split in text:
        text = text.replace(old_split, new_split, 1)
        return text.encode(TEXT_ENCODING), ["added buildconfig riscv64 arch mapping"]
    return data, ["buildconfig riscv64 arch insertion point not found"]


def apply_ohos_toolchain_riscv64_rust_abi_target(data: bytes) -> tuple[bytes, list[str]]:
    text = data.decode(TEXT_ENCODING, errors="ignore")
    target = 'rust_abi_target = "riscv64-unknown-linux-ohos"'
    if target in text:
        return data, ["riscv64 OHOS Rust ABI target already uses OpenHarmony tuple"]
    old = 'rust_abi_target = "riscv64-unknown-linux-gnu"'
    if old in text:
        text = text.replace(old, target, 1)
        return text.encode(TEXT_ENCODING), ["changed riscv64 Rust ABI target from GNU to OpenHarmony tuple"]
    return data, ["riscv64 Rust ABI target insertion point not found"]


def apply_rust_riscv64_toolchain_host_split(data: bytes) -> tuple[bytes, list[str]]:
    text = data.decode(TEXT_ENCODING, errors="ignore")
    notes: list[str] = []
    if 'enable_rust_riscv && current_cpu == "riscv64"' in text:
        return data, ["Rust toolchain already scopes rustc-riscv to riscv64 target toolchains"]

    old_sysroot = (
        "    if (enable_rust_riscv) {\n"
        '      rust_sysroot = "//prebuilts/rustc-riscv/linux-x86_64/current"\n'
        "    } else {\n"
        '      rust_sysroot = "//prebuilts/rustc/linux-x86_64/current"\n'
        "    }\n"
    )
    new_sysroot = (
        '    if (enable_rust_riscv && current_cpu == "riscv64") {\n'
        '      rust_sysroot = "//prebuilts/rustc-riscv/linux-x86_64/current"\n'
        "    } else {\n"
        '      rust_sysroot = "//prebuilts/rustc/linux-x86_64/current"\n'
        "    }\n"
    )
    if old_sysroot in text:
        text = text.replace(old_sysroot, new_sysroot, 1)
        notes.append("scoped rust_sysroot rustc-riscv selection to riscv64 target toolchains")
    else:
        notes.append("rust_sysroot rustc-riscv selection insertion point not found")

    old_base = (
        "if (enable_rust_riscv) {\n"
        '  rust_base = rebase_path("//prebuilts/rustc-riscv", root_build_dir)\n'
        "} else {\n"
        '  rust_base = rebase_path("//prebuilts/rustc", root_build_dir)\n'
        "}\n"
    )
    new_base = (
        'if (enable_rust_riscv && current_cpu == "riscv64") {\n'
        '  rust_base = rebase_path("//prebuilts/rustc-riscv", root_build_dir)\n'
        "} else {\n"
        '  rust_base = rebase_path("//prebuilts/rustc", root_build_dir)\n'
        "}\n"
    )
    if old_base in text:
        text = text.replace(old_base, new_base, 1)
        notes.append("scoped rust_base rustc-riscv selection to riscv64 target toolchains")
    else:
        notes.append("rust_base rustc-riscv selection insertion point not found")
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


def apply_riscv64_musl_hook_cflags_mabi_compat(data: bytes) -> tuple[bytes, list[str]]:
    text = data.decode(TEXT_ENCODING, errors="ignore")
    if (
        'soft_musl_hook_${target_name}' in text
        and 'cflags += [ "-mabi=lp64d" ]' in text
        and 'musl_arch == "riscv64"' in text
    ):
        return data, ["musl hook riscv64 cflags already carry -mabi=lp64d"]

    anchor = (
        '    cflags = [\n'
        '      "-mllvm",\n'
        '      "--instcombine-max-iterations=0",\n'
        '      "-ffp-contract=fast",\n'
        '      "-O3",\n'
        '      "-Wno-int-conversion",\n'
        "    ]\n"
    )
    insertion = (
        anchor
        + "\n"
        + '    if (musl_arch == "riscv64") {\n'
        + '      # Keep musl hook LTO bitcode on the same hard-float ABI as musl libc.\n'
        + '      cflags += [ "-mabi=lp64d" ]\n'
        + "    }\n"
    )
    if anchor in text:
        text = text.replace(anchor, insertion, 1)
        return text.encode(TEXT_ENCODING), ["added musl hook riscv64 -mabi=lp64d cflag"]
    return data, ["musl hook riscv64 cflags insertion point not found"]


def apply_riscv64_musl_shared_no_lto_compat(data: bytes) -> tuple[bytes, list[str]]:
    text = data.decode(TEXT_ENCODING, errors="ignore")
    notes: list[str] = []

    def patch_shared_template(name: str, current_text: str) -> tuple[str, bool]:
        old = (
            f'  static_and_shared_libs_template("{name}") {{\n'
            "    musl_use_flto = true\n"
            "  }\n"
        )
        new = (
            f'  static_and_shared_libs_template("{name}") {{\n'
            '    if (musl_arch == "riscv64") {\n'
            "      # Avoid riscv64 LTO temp-object float-ABI mismatches during libc.so link.\n"
            "      musl_use_flto = false\n"
            "    } else {\n"
            "      musl_use_flto = true\n"
            "    }\n"
            "  }\n"
        )
        if new in current_text:
            return current_text, False
        if old in current_text:
            return current_text.replace(old, new, 1), True
        return current_text, False

    for template_name in ("shared", "shared_sp"):
        before = text
        text, changed = patch_shared_template(template_name, text)
        if changed:
            notes.append(f"disabled riscv64 musl LTO for {template_name} shared template")
        elif f'static_and_shared_libs_template("{template_name}")' in before and 'musl_arch == "riscv64"' in before:
            notes.append(f"musl {template_name} shared template already has riscv64 LTO guard")

    if not notes:
        notes.append("musl shared LTO insertion point not found")
    return text.encode(TEXT_ENCODING), notes


def apply_tee_riscv64_barrier_asm_compat(data: bytes) -> tuple[bytes, list[str]]:
    text = data.decode(TEXT_ENCODING, errors="ignore")
    if (
        "#elif defined(__riscv)" in text
        and '__asm__ volatile("fence.i");' in text
        and '__asm__ volatile("fence iorw, iorw");' in text
    ):
        return data, ["TEE RISC-V barrier asm branches already present"]

    pattern = re.compile(
        r'(?m)^(?P<indent>[ \t]*)__asm__ volatile\("isb"\);\n'
        r'(?P=indent)__asm__ volatile\("dsb sy"\);'
    )

    def guarded_barrier(match: re.Match[str]) -> str:
        indent = match.group("indent")
        return "\n".join(
            [
                f"{indent}#if defined(__aarch64__)",
                f'{indent}__asm__ volatile("isb");',
                f'{indent}__asm__ volatile("dsb sy");',
                f"{indent}#elif defined(__riscv)",
                f'{indent}__asm__ volatile("fence.i");',
                f'{indent}__asm__ volatile("fence iorw, iorw");',
                f"{indent}#else",
                f'{indent}#error "Unsupported architecture"',
                f"{indent}#endif",
            ]
        )

    text, count = pattern.subn(guarded_barrier, text)
    if count:
        return (
            text.encode(TEXT_ENCODING),
            [f"wrapped {count} TEE ARM barrier asm block(s) with target-evidenced riscv64 fences"],
        )
    return data, ["TEE ARM barrier asm insertion point not found"]


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


def apply_ark_runtime_riscv64_arch_traits(data: bytes) -> tuple[bytes, list[str]]:
    text = data.decode(TEXT_ENCODING, errors="ignore")
    notes: list[str] = []
    if "D(RISCV64)" not in text:
        text = text.replace("    D(AARCH64)       \\\n    D(X86)", "    D(AARCH64)       \\\n    D(RISCV64)       \\\n    D(X86)", 1)
        notes.append("added RISCV64 to ARCH_LIST")

    if "struct ArchTraits<Arch::RISCV64>" not in text:
        riscv_traits = r'''
template <>
struct ArchTraits<Arch::RISCV64> {
    static constexpr size_t CODE_ALIGNMENT = 16;
    static constexpr size_t INSTRUCTION_ALIGNMENT = 4;
    static constexpr size_t INSTRUCTION_MAX_SIZE_BITS = 32;
    static constexpr size_t POINTER_SIZE = 8;
    static constexpr bool IS_64_BITS = true;
    static constexpr size_t THREAD_REG = 28;
    static constexpr size_t CALLER_REG_MASK = 0x0007ffff;
    static constexpr size_t CALLER_FP_REG_MASK = 0xffff00ff;
    static constexpr size_t CALLEE_REG_MASK = 0x1ff80000;
    static constexpr size_t CALLEE_FP_REG_MASK = 0x0000ff00;
    static constexpr size_t IRTOC_OPTIMIZED_CALLEE_REG_MASK = 0x1ff80000;
    static constexpr size_t IRTOC_OPTIMIZED_CALLEE_FP_REG_MASK = ChooseIrtocOptimizedFpRegmask();
    static constexpr bool SUPPORT_OSR = true;
    static constexpr bool SUPPORT_DEOPTIMIZATION = true;
    static constexpr const char *ISA_NAME = "riscv64";
    static constexpr size_t DWARF_SP = 2;
    static constexpr size_t DWARF_RIP = 0;
    static constexpr size_t DWARF_FP = 8;
    static constexpr size_t DWARF_LR = 1;
    using WordType = uint64_t;
};

'''
        marker = "template <>\nstruct ArchTraits<Arch::X86> {"
        if marker in text:
            text = text.replace(marker, riscv_traits + marker, 1)
            notes.append("added target-evidenced RISCV64 ArchTraits")

    if "ArchTraits<Arch::RISCV64>::property" not in text:
        old = (
            "        if (arch == Arch::AARCH64) {                                                                  \\\n"
            "            /* CC-OFFNXT(G.PRE.02, G.PRE.05) namespace member, function gen */                        \\\n"
            "            return ArchTraits<Arch::AARCH64>::property;                                               \\\n"
            "        }                                                                                             \\\n"
        )
        new = old + (
            "        if (arch == Arch::RISCV64) {                                                                  \\\n"
            "            return ArchTraits<Arch::RISCV64>::property;                                               \\\n"
            "        }                                                                                             \\\n"
        )
        if old in text:
            text = text.replace(old, new, 1)
            notes.append("added RISCV64 arch property getter branch")

    if "case Arch::RISCV64:" not in text:
        text = text.replace(
            "        case Arch::AARCH64:\n"
            "            return isFp ? ArchTraits<Arch::AARCH64>::CALLER_FP_REG_MASK : ArchTraits<Arch::AARCH64>::CALLER_REG_MASK;\n"
            "        case Arch::X86:",
            "        case Arch::AARCH64:\n"
            "            return isFp ? ArchTraits<Arch::AARCH64>::CALLER_FP_REG_MASK : ArchTraits<Arch::AARCH64>::CALLER_REG_MASK;\n"
            "        case Arch::RISCV64:\n"
            "            return isFp ? ArchTraits<Arch::RISCV64>::CALLER_FP_REG_MASK : ArchTraits<Arch::RISCV64>::CALLER_REG_MASK;\n"
            "        case Arch::X86:",
            1,
        )
        text = text.replace(
            "        case Arch::X86:\n"
            "            return isFp ? ArchTraits<Arch::X86>::CALLEE_FP_REG_MASK : ArchTraits<Arch::X86>::CALLEE_REG_MASK;",
            "        case Arch::RISCV64:\n"
            "            return isFp ? ArchTraits<Arch::RISCV64>::CALLEE_FP_REG_MASK : ArchTraits<Arch::RISCV64>::CALLEE_REG_MASK;\n"
            "        case Arch::X86:\n"
            "            return isFp ? ArchTraits<Arch::X86>::CALLEE_FP_REG_MASK : ArchTraits<Arch::X86>::CALLEE_REG_MASK;",
            1,
        )
        notes.append("added RISCV64 caller/callee register mask branches")

    if "RUNTIME_ARCH = Arch::RISCV64" not in text:
        text = text.replace(
            "#elif defined(PANDA_TARGET_ARM64)\nstatic constexpr Arch RUNTIME_ARCH = Arch::AARCH64;\n#elif defined(PANDA_TARGET_X86)",
            "#elif defined(PANDA_TARGET_ARM64)\nstatic constexpr Arch RUNTIME_ARCH = Arch::AARCH64;\n#elif defined(PANDA_TARGET_RISCV64)\nstatic constexpr Arch RUNTIME_ARCH = Arch::RISCV64;\n#elif defined(PANDA_TARGET_X86)",
            1,
        )
        notes.append("added PANDA_TARGET_RISCV64 runtime arch selection")

    if 'str == "riscv64"' not in text:
        text = text.replace(
            '    if (str == "arm64") {\n        return Arch::AARCH64;\n    }\n',
            '    if (str == "arm64") {\n        return Arch::AARCH64;\n    }\n    if (str == "riscv64") {\n        return Arch::RISCV64;\n    }\n',
            1,
        )
        notes.append("added riscv64 string-to-arch mapping")
    if 'return "riscv64";' not in text:
        text = text.replace(
            '    if (arch == Arch::AARCH64) {\n        return "arm64";\n    }\n',
            '    if (arch == Arch::AARCH64) {\n        return "arm64";\n    }\n    if (arch == Arch::RISCV64) {\n        return "riscv64";\n    }\n',
            1,
        )
        notes.append("added RISCV64 arch-to-string mapping")

    return text.encode(TEXT_ENCODING), notes or ["ArkCompiler runtime RISCV64 arch traits already present"]


def apply_ark_runtime_riscv64_ext_arch_traits(data: bytes) -> tuple[bytes, list[str]]:
    text = data.decode(TEXT_ENCODING, errors="ignore")
    if "struct ExtArchTraits<Arch::RISCV64>" in text:
        return data, ["ArkCompiler RISCV64 ExtArchTraits already present"]
    marker = "template <class T>\ninline uint8_t *AlignPtr(uint8_t *ptr)"
    block = r'''template <>
struct ExtArchTraits<Arch::RISCV64> {
    using SignedWordType = int64_t;
    using UnsignedWordType = uint64_t;

    static constexpr size_t NUM_GP_ARG_REGS = 6;
    static constexpr size_t GP_ARG_NUM_BYTES = NUM_GP_ARG_REGS * ArchTraits<Arch::RISCV64>::POINTER_SIZE;
    static constexpr size_t NUM_FP_ARG_REGS = 8;
    static constexpr size_t FP_ARG_NUM_BYTES = NUM_FP_ARG_REGS * ArchTraits<Arch::RISCV64>::POINTER_SIZE;
    static constexpr size_t GPR_SIZE = ArchTraits<Arch::RISCV64>::POINTER_SIZE;
    static constexpr size_t FPR_SIZE = ArchTraits<Arch::RISCV64>::POINTER_SIZE;
    static constexpr bool HARDFP = true;
};

'''
    if marker in text:
        return text.replace(marker, block + marker, 1).encode(TEXT_ENCODING), ["added target-evidenced RISCV64 ExtArchTraits"]
    return data, ["ArkCompiler RISCV64 ExtArchTraits insertion point not found"]


def apply_ark_runtime_riscv64_memory_helpers(data: bytes) -> tuple[bytes, list[str]]:
    text = data.decode(TEXT_ENCODING, errors="ignore")
    if 'defined(PANDA_TARGET_RISCV64)' in text and '"riscv64/memory.h"' in text:
        return data, ["ArkCompiler RISCV64 memory helper include already present"]
    old = '#elif defined(PANDA_TARGET_AMD64)\n#include "amd64/memory.h"\n#else'
    new = '#elif defined(PANDA_TARGET_AMD64)\n#include "amd64/memory.h"\n#elif defined(PANDA_TARGET_RISCV64)\n#include "riscv64/memory.h"\n#else'
    if old in text:
        return text.replace(old, new, 1).encode(TEXT_ENCODING), ["added target-evidenced RISCV64 memory helper include"]
    return data, ["ArkCompiler RISCV64 memory helper insertion point not found"]


ARK_RISCV64_THREAD_ACCESS_HELPERS = (
    "// RISC-V load/store immediates are signed 12-bit; ManagedThread fields may live beyond that range.\n"
    ".macro ARK_LOAD_THREAD_X dst, offset\n"
    "    li \\dst, \\offset\n"
    "    add \\dst, \\dst, THREAD_REG\n"
    "    ld \\dst, 0(\\dst)\n"
    ".endm\n"
    "\n"
    ".macro ARK_LOAD_THREAD_U8 dst, offset\n"
    "    li \\dst, \\offset\n"
    "    add \\dst, \\dst, THREAD_REG\n"
    "    lbu \\dst, 0(\\dst)\n"
    ".endm\n"
    "\n"
    ".macro ARK_STORE_THREAD_X src, offset, scratch\n"
    "    li \\scratch, \\offset\n"
    "    add \\scratch, \\scratch, THREAD_REG\n"
    "    sd \\src, 0(\\scratch)\n"
    ".endm\n"
)


MISPLACED_ARK_RISCV64_THREAD_ACCESS_HELPERS_RE = re.compile(
    r"\n#ifdef PANDA_TARGET_RISCV64\n"
    r"// RISC-V load/store immediates are signed 12-bit; ManagedThread fields may live beyond that range\.\n"
    r"\.macro ARK_LOAD_THREAD_X dst, offset\n"
    r".*?"
    r"\.macro ARK_STORE_THREAD_X src, offset, scratch\n"
    r".*?"
    r"\.endm\n"
    r"#endif\n",
    re.S,
)


def ensure_ark_riscv64_thread_access_helpers(text: str) -> tuple[str, list[str]]:
    if ".macro ARK_LOAD_THREAD_X" in text and ".macro ARK_STORE_THREAD_X" in text:
        return text, ["RISC-V large ManagedThread offset access helpers already present"]
    anchor = '#include "arch/asm_support.h"\n'
    if anchor in text:
        return (
            text.replace(anchor, anchor + "\n" + ARK_RISCV64_THREAD_ACCESS_HELPERS + "\n", 1),
            ["added local RISC-V large ManagedThread offset access helpers"],
        )
    return text, ["RISC-V large ManagedThread offset helper insertion point not found"]


def apply_ark_runtime_riscv64_asm_support(data: bytes) -> tuple[bytes, list[str]]:
    text = data.decode(TEXT_ENCODING, errors="ignore")
    notes: list[str] = []

    text, removed_helper_count = MISPLACED_ARK_RISCV64_THREAD_ACCESS_HELPERS_RE.subn("\n", text)
    if removed_helper_count:
        notes.append("removed misplaced RISC-V assembly helper macros from asm_support.h C++ include surface")

    if "PANDA_TARGET_RISCV64" in text and "THREAD_REG tp" in text:
        notes.append("ArkCompiler RISCV64 asm THREAD_REG already present")
    else:
        old = (
            "#elif defined(PANDA_TARGET_AMD64)\n"
            "// NOLINTNEXTLINE(cppcoreguidelines-macro-usage)\n"
            "#define THREAD_REG r15\n"
            "#else"
        )
        new = (
            "#elif defined(PANDA_TARGET_AMD64)\n"
            "// NOLINTNEXTLINE(cppcoreguidelines-macro-usage)\n"
            "#define THREAD_REG r15\n"
            "#elif defined(PANDA_TARGET_RISCV64)\n"
            "#define THREAD_REG tp\n"
            "#else"
        )
        if old in text:
            text = text.replace(old, new, 1)
            notes.append("added target-evidenced RISCV64 asm THREAD_REG")
        else:
            notes.append("ArkCompiler RISCV64 asm THREAD_REG insertion point not found")

    if "MAKE_ASM_NAME(name)" in text:
        notes.append("ArkCompiler MAKE_ASM_NAME macro already present")
    else:
        old_type_function = (
            "#ifndef PANDA_TARGET_WINDOWS\n"
            "// NOLINTNEXTLINE(cppcoreguidelines-macro-usage)\n"
            "#define TYPE_FUNCTION(name) .type name, %function\n"
            "#else\n"
            "#define TYPE_FUNCTION(name)\n"
            "#endif\n"
        )
        new_type_function = (
            "#if !defined(PANDA_TARGET_WINDOWS) && !defined(PANDA_TARGET_MACOS)\n"
            "// NOLINTNEXTLINE(cppcoreguidelines-macro-usage)\n"
            "#define TYPE_FUNCTION(name) .type name, %function\n"
            "#else\n"
            "#define TYPE_FUNCTION(name)\n"
            "#endif\n"
            "\n"
            "#ifdef PANDA_TARGET_MACOS\n"
            "/* CC-OFFNXT(G.PRE.02) name part*/\n"
            "// NOLINTNEXTLINE(cppcoreguidelines-macro-usage)\n"
            "#define MAKE_ASM_NAME(name) _##name\n"
            "#else\n"
            "/* CC-OFFNXT(G.PRE.02) name part*/\n"
            "// NOLINTNEXTLINE(cppcoreguidelines-macro-usage)\n"
            "#define MAKE_ASM_NAME(name) name\n"
            "#endif\n"
        )
        if old_type_function in text:
            text = text.replace(old_type_function, new_type_function, 1)
            notes.append("added target-evidenced MAKE_ASM_NAME macro for ArkCompiler assembly labels")
        else:
            notes.append("ArkCompiler MAKE_ASM_NAME insertion point not found")

    return text.encode(TEXT_ENCODING), notes or ["ArkCompiler RISCV64 asm support already present"]


def replace_asm_lines(text: str, replacements: list[tuple[str, str]]) -> tuple[str, list[str]]:
    notes: list[str] = []
    for old, new in replacements:
        if new in text:
            notes.append(f"assembly replacement already present: {new.strip()}")
            continue
        count = text.count(old)
        if not count:
            notes.append(f"assembly replacement source not found: {old.strip()}")
            continue
        text = text.replace(old, new)
        notes.append(f"replaced {count} large-offset assembly access(es): {old.strip()} -> {new.strip()}")
    return text, notes


def apply_ark_riscv64_call_runtime_large_thread_offsets(data: bytes) -> tuple[bytes, list[str]]:
    text = data.decode(TEXT_ENCODING, errors="ignore")
    text, helper_notes = ensure_ark_riscv64_thread_access_helpers(text)
    text, notes = replace_asm_lines(
        text,
        [
            (
                "    ld t0, MANAGED_THREAD_EXCEPTION_OFFSET(THREAD_REG)",
                "    ARK_LOAD_THREAD_X t0, MANAGED_THREAD_EXCEPTION_OFFSET",
            ),
            (
                "    sd ra, MANAGED_THREAD_NATIVE_PC_OFFSET(THREAD_REG)",
                "    ARK_STORE_THREAD_X ra, MANAGED_THREAD_NATIVE_PC_OFFSET, t0",
            ),
            (
                "    sd t0, MANAGED_THREAD_FRAME_OFFSET(THREAD_REG)",
                "    ARK_STORE_THREAD_X t0, MANAGED_THREAD_FRAME_OFFSET, t1",
            ),
            (
                "    sd s0, MANAGED_THREAD_FRAME_OFFSET(THREAD_REG)",
                "    ARK_STORE_THREAD_X s0, MANAGED_THREAD_FRAME_OFFSET, t0",
            ),
        ],
    )
    return text.encode(TEXT_ENCODING), helper_notes + notes


def apply_ark_riscv64_compiled_bridge_large_thread_offsets(data: bytes) -> tuple[bytes, list[str]]:
    text = data.decode(TEXT_ENCODING, errors="ignore")
    text, notes = replace_asm_lines(
        text,
        [
            (
                "    lbu t0, MANAGED_THREAD_FRAME_KIND_OFFSET(THREAD_REG)",
                "    ARK_LOAD_THREAD_U8 t0, MANAGED_THREAD_FRAME_KIND_OFFSET",
            ),
            (
                "    ld t0, MANAGED_THREAD_RUNTIME_CALL_ENABLED_OFFSET(THREAD_REG)",
                "    ARK_LOAD_THREAD_X t0, MANAGED_THREAD_RUNTIME_CALL_ENABLED_OFFSET",
            ),
            (
                "    sd zero, MANAGED_THREAD_RUNTIME_CALL_ENABLED_OFFSET(THREAD_REG)",
                "    ARK_STORE_THREAD_X zero, MANAGED_THREAD_RUNTIME_CALL_ENABLED_OFFSET, t0",
            ),
            (
                "    sd s1, MANAGED_THREAD_RUNTIME_CALL_ENABLED_OFFSET(THREAD_REG)",
                "    ARK_STORE_THREAD_X s1, MANAGED_THREAD_RUNTIME_CALL_ENABLED_OFFSET, t0",
            ),
            (
                "    sd ra, MANAGED_THREAD_NATIVE_PC_OFFSET(THREAD_REG)",
                "    ARK_STORE_THREAD_X ra, MANAGED_THREAD_NATIVE_PC_OFFSET, t0",
            ),
            (
                "    sd s0, MANAGED_THREAD_FRAME_OFFSET(THREAD_REG)",
                "    ARK_STORE_THREAD_X s0, MANAGED_THREAD_FRAME_OFFSET, t0",
            ),
        ],
    )
    return text.encode(TEXT_ENCODING), notes


def apply_ark_riscv64_tlab_large_thread_offsets(data: bytes) -> tuple[bytes, list[str]]:
    text = data.decode(TEXT_ENCODING, errors="ignore")
    text, helper_notes = ensure_ark_riscv64_thread_access_helpers(text)
    text, notes = replace_asm_lines(
        text,
        [
            (
                "  ld \\reg_tlab_size, MANAGED_THREAD_TLAB_OFFSET(THREAD_REG)",
                "  ARK_LOAD_THREAD_X \\reg_tlab_size, MANAGED_THREAD_TLAB_OFFSET",
            ),
            (
                "  ld t0, MANAGED_THREAD_TLAB_OFFSET(THREAD_REG)",
                "  ARK_LOAD_THREAD_X t0, MANAGED_THREAD_TLAB_OFFSET",
            ),
        ],
    )
    return text.encode(TEXT_ENCODING), helper_notes + notes


def apply_ark_riscv64_string_index_guard(data: bytes) -> tuple[bytes, list[str]]:
    text = data.decode(TEXT_ENCODING, errors="ignore")
    if "!defined(PANDA_TARGET_RISCV64)" in text:
        return data, ["ArkCompiler StringIndexOf RISCV64 guard already present"]
    old = (
        "#if !defined(PANDA_TARGET_ARM64) && !defined(PANDA_TARGET_ARM32) && !defined(PANDA_TARGET_AMD64) && \\\n"
        "    !defined(PANDA_TARGET_X86)"
    )
    new = (
        "#if !defined(PANDA_TARGET_ARM64) && !defined(PANDA_TARGET_ARM32) && !defined(PANDA_TARGET_AMD64) && \\\n"
        "    !defined(PANDA_TARGET_X86) && !defined(PANDA_TARGET_RISCV64)"
    )
    if old in text:
        return (
            text.replace(old, new, 1).encode(TEXT_ENCODING),
            ["added target-evidenced StringIndexOf PANDA_TARGET_RISCV64 little-endian guard"],
        )
    return data, ["ArkCompiler StringIndexOf RISCV64 guard insertion point not found"]


def apply_ark_riscv64_ets_to_string_cache_atomic_guard(data: bytes) -> tuple[bytes, list[str]]:
    text = data.decode(TEXT_ENCODING, errors="ignore")
    target_guard = "#if !defined(ARK_HYBRID) && defined(PANDA_32_BIT_MANAGED_POINTER) && defined(PANDA_TARGET_64)"
    if target_guard in text:
        return data, ["ArkCompiler EtsToStringCache atomic guard already target-compatible"]
    old = "#if !defined(ARK_HYBRID)\n    static_assert(std::atomic<Data>::is_always_lock_free);\n#endif"
    new = target_guard + "\n    static_assert(std::atomic<Data>::is_always_lock_free);\n#endif"
    if old in text:
        return (
            text.replace(old, new, 1).encode(TEXT_ENCODING),
            ["narrowed EtsToStringCache lock-free atomic assertion with target-evidenced RISC-V-safe guard"],
        )
    return data, ["ArkCompiler EtsToStringCache atomic guard insertion point not found"]


def apply_ark_runtime_riscv64_fiber_context(data: bytes) -> tuple[bytes, list[str]]:
    text = data.decode(TEXT_ENCODING, errors="ignore")
    if "runtime/fibers/arch/riscv64/context_layout.h" in text:
        return data, ["ArkCompiler RISCV64 fiber context include already present"]
    old = '#elif defined(PANDA_TARGET_AMD64)\n#include "runtime/fibers/arch/amd64/context_layout.h"\n#else'
    new = '#elif defined(PANDA_TARGET_AMD64)\n#include "runtime/fibers/arch/amd64/context_layout.h"\n#elif defined(PANDA_TARGET_RISCV64)\n#include "runtime/fibers/arch/riscv64/context_layout.h"\n#else'
    if old in text:
        return text.replace(old, new, 1).encode(TEXT_ENCODING), ["added target-evidenced RISCV64 fiber context include"]
    return data, ["ArkCompiler RISCV64 fiber context insertion point not found"]


def apply_ark_runtime_riscv64_fiber_asm_macros(data: bytes) -> tuple[bytes, list[str]]:
    text = data.decode(TEXT_ENCODING, errors="ignore")
    if "PANDA_TARGET_RISCV64" in text and "FUNC_ALIGNMENT_BYTES 32" in text:
        return data, ["ArkCompiler RISCV64 fiber asm macros already present"]
    old = "#elif defined(PANDA_TARGET_AMD64)\n#define FUNC_ALIGNMENT_BYTES 16\n#else"
    new = "#elif defined(PANDA_TARGET_AMD64)\n#define FUNC_ALIGNMENT_BYTES 16\n#elif defined(PANDA_TARGET_RISCV64)\n#define FUNC_ALIGNMENT_BYTES 32\n#else"
    if old in text:
        return text.replace(old, new, 1).encode(TEXT_ENCODING), ["added target-evidenced RISCV64 fiber function alignment"]
    return data, ["ArkCompiler RISCV64 fiber asm macro insertion point not found"]


def apply_ark_runtime_riscv64_signal_context(data: bytes) -> tuple[bytes, list[str]]:
    text = data.decode(TEXT_ENCODING, errors="ignore")
    notes: list[str] = []
    if "PANDA_TARGET_RISCV64" not in text or "CONTEXT_PC uc_->uc_mcontext.__gregs[0]" not in text:
        old = "#elif defined(PANDA_TARGET_ARM64)\n#ifdef __APPLE__"
        new = (
            "#elif defined(PANDA_TARGET_RISCV64)\n"
            "#define CONTEXT_PC uc_->uc_mcontext.__gregs[0]  // NOLINT(cppcoreguidelines-macro-usage)\n"
            "#define CONTEXT_SP uc_->uc_mcontext.__gregs[2]  // NOLINT(cppcoreguidelines-macro-usage)\n"
            "#define CONTEXT_FP uc_->uc_mcontext.__gregs[8]  // NOLINT(cppcoreguidelines-macro-usage)\n"
            "#define CONTEXT_LR uc_->uc_mcontext.__gregs[1]  // NOLINT(cppcoreguidelines-macro-usage)\n"
            "#elif defined(PANDA_TARGET_ARM64)\n#ifdef __APPLE__"
        )
        if old in text:
            text = text.replace(old, new, 1)
            notes.append("added target-evidenced RISCV64 ucontext register macros")
    old_cond = "#if (defined(PANDA_TARGET_ARM64) || defined(PANDA_TARGET_ARM32))"
    new_cond = "#if (defined(PANDA_TARGET_ARM64) || defined(PANDA_TARGET_ARM32) || defined(PANDA_TARGET_RISCV64))"
    if old_cond in text:
        text = text.replace(old_cond, new_cond, 1)
        notes.append("included RISCV64 in SignalContext LR accessors")
    return text.encode(TEXT_ENCODING), notes or ["ArkCompiler RISCV64 signal context already present"]


def apply_ark_runtime_riscv64_object_accessor_guard(data: bytes) -> tuple[bytes, list[str]]:
    text = data.decode(TEXT_ENCODING, errors="ignore")
    old = "#if !defined(ARK_HYBRID)\n    static bool IsHeapObject(coretypes::TaggedType v)"
    new = "#if !defined(ARK_HYBRID) && !defined(PANDA_TARGET_RISCV64)\n    static bool IsHeapObject(coretypes::TaggedType v)"
    if new in text:
        return data, ["ArkCompiler RISCV64 object accessor overload guard already present"]
    if old in text:
        return text.replace(old, new, 1).encode(TEXT_ENCODING), [
            "guarded duplicate TaggedType overloads for RISCV64 ObjectPointerType representation"
        ]
    return data, ["ArkCompiler RISCV64 object accessor guard insertion point not found"]


def apply_ark_runtime_riscv64_build_sources(data: bytes) -> tuple[bytes, list[str]]:
    text = data.decode(TEXT_ENCODING, errors="ignore")
    if 'current_cpu == "riscv64"' in text and "arch/riscv64/interpreter_support.S" in text:
        return data, ["ArkCompiler RISCV64 runtime BUILD.gn sources already present"]
    old = '  } else if (current_cpu == "x86") {\n    sources += ['
    riscv_branch = '''  } else if (current_cpu == "riscv64") {
    sources += [
      "arch/riscv64/interpreter_support.S",
      "arch/riscv64/osr_riscv64.S",
      "bridge/arch/riscv64/compiled_code_to_interpreter_bridge_riscv64.S",
      "bridge/arch/riscv64/compiled_code_to_interpreter_bridge_dyn_riscv64.S",
      "bridge/arch/riscv64/compiled_code_to_runtime_bridge_riscv64.S",
      "bridge/arch/riscv64/deoptimization_riscv64.S",
      "bridge/arch/riscv64/expand_compiled_code_args_dyn_riscv64.S",
      "bridge/arch/riscv64/interpreter_to_compiled_code_bridge_riscv64.S",
      "bridge/arch/riscv64/interpreter_to_compiled_code_bridge_dyn_riscv64.S",
      "fibers/arch/riscv64/get.S",
      "fibers/arch/riscv64/switch.S",
      "fibers/arch/riscv64/update.S",
    ]
'''
    if old in text:
        return text.replace(old, riscv_branch + old, 1).encode(TEXT_ENCODING), [
            "added target-evidenced RISCV64 runtime arch/bridge/fiber sources"
        ]
    return data, ["ArkCompiler RISCV64 runtime BUILD.gn source insertion point not found"]


def apply_ark_runtime_riscv64_osr_fallback_guard(data: bytes) -> tuple[bytes, list[str]]:
    text = data.decode(TEXT_ENCODING, errors="ignore")
    if "#if !defined(PANDA_TARGET_RISCV64)" in text and "OsrEntryAfterCFrame" in text:
        return data, ["ArkCompiler RISCV64 OSR fallback guard already present"]
    old = "#if !defined(PANDA_TARGET_ARM64)\nextern \"C\" void OsrEntryAfterCFrame"
    new = "#if !defined(PANDA_TARGET_RISCV64)\nextern \"C\" void OsrEntryAfterCFrame"
    if old in text:
        return text.replace(old, new, 1).encode(TEXT_ENCODING), [
            "guarded asm_support.cpp OSR fallback symbols when riscv64 osr_riscv64.S is linked"
        ]
    return data, ["ArkCompiler RISCV64 OSR fallback guard insertion point not found"]


def apply_ark_ets_riscv64_bridge_sources(data: bytes) -> tuple[bytes, list[str]]:
    text = data.decode(TEXT_ENCODING, errors="ignore")
    notes: list[str] = []

    interop_line = '    srcs_runtime += [ "runtime/interop_js/arch/riscv64/call_bridge_riscv64.S" ]'
    if interop_line not in text:
        old = (
            '  } else if (current_cpu == "arm") {\n'
            '    srcs_runtime += [ "runtime/interop_js/arch/arm32/call_bridge_arm32.S" ]\n'
            "  }\n"
        )
        new = (
            '  } else if (current_cpu == "arm") {\n'
            '    srcs_runtime += [ "runtime/interop_js/arch/arm32/call_bridge_arm32.S" ]\n'
            '  } else if (current_cpu == "riscv64") {\n'
            f"{interop_line}\n"
            "  }\n"
        )
        if old in text:
            text = text.replace(old, new, 1)
            notes.append("added ETS interop JS RISC-V call bridge source branch")
        else:
            notes.append("ETS interop JS RISC-V call bridge insertion point not found")
    else:
        notes.append("ETS interop JS RISC-V call bridge source branch already present")

    napi_marker = '"runtime/napi/arch/riscv64/ets_napi_entry_point_riscv64.S"'
    if napi_marker not in text:
        old = (
            '} else if (current_cpu == "arm") {\n'
            "  srcs_runtime += [\n"
            '    "runtime/napi/arch/arm32/ets_napi_entry_point_arm32.S",\n'
            '    "runtime/napi/arch/arm32/ets_async_entry_point_arm32.S",\n'
            "  ]\n"
            "}\n"
        )
        new = (
            '} else if (current_cpu == "arm") {\n'
            "  srcs_runtime += [\n"
            '    "runtime/napi/arch/arm32/ets_napi_entry_point_arm32.S",\n'
            '    "runtime/napi/arch/arm32/ets_async_entry_point_arm32.S",\n'
            "  ]\n"
            '} else if (current_cpu == "riscv64") {\n'
            "  srcs_runtime += [\n"
            '    "runtime/napi/arch/riscv64/ets_napi_entry_point_riscv64.S",\n'
            '    "runtime/napi/arch/riscv64/ets_async_entry_point_riscv64.S",\n'
            '    "runtime/entrypoints/arch/riscv64/ets_proxy_entry_point_riscv64.S",\n'
            "  ]\n"
            "}\n"
        )
        if old in text:
            text = text.replace(old, new, 1)
            notes.append("added ETS NAPI/proxy RISC-V entry source branch")
        else:
            notes.append("ETS NAPI/proxy RISC-V entry insertion point not found")
    else:
        notes.append("ETS NAPI/proxy RISC-V entry source branch already present")

    proxy_cpp_line = '  "runtime/entrypoints/ets_proxy_entrypoints.cpp",'
    if proxy_cpp_line not in text:
        inserted = False
        for anchor in (
            '  "runtime/static_type_converter.cpp",\n',
            '  "stdlib/native/init_native_methods.cpp",\n',
        ):
            if anchor in text:
                text = text.replace(anchor, proxy_cpp_line + "\n" + anchor, 1)
                inserted = True
                break
        if inserted:
            notes.append("added ETS proxy entrypoint C++ runtime source")
        else:
            notes.append("ETS proxy entrypoint C++ runtime source insertion point not found")
    else:
        notes.append("ETS proxy entrypoint C++ runtime source already present")

    return text.encode(TEXT_ENCODING), notes


def apply_ark_riscv64_proxy_entrypoint_large_thread_offsets(data: bytes) -> tuple[bytes, list[str]]:
    text = data.decode(TEXT_ENCODING, errors="ignore")
    text, helper_notes = ensure_ark_riscv64_thread_access_helpers(text)
    text, notes = replace_asm_lines(
        text,
        [
            (
                "    lbu   s4, MANAGED_THREAD_FRAME_KIND_OFFSET(THREAD_REG)",
                "    ARK_LOAD_THREAD_U8 s4, MANAGED_THREAD_FRAME_KIND_OFFSET",
            ),
            (
                "    sd    s0, MANAGED_THREAD_FRAME_OFFSET(THREAD_REG)",
                "    ARK_STORE_THREAD_X s0, MANAGED_THREAD_FRAME_OFFSET, t0",
            ),
            (
                "    ld    t1, MANAGED_THREAD_EXCEPTION_OFFSET(THREAD_REG)",
                "    ARK_LOAD_THREAD_X t1, MANAGED_THREAD_EXCEPTION_OFFSET",
            ),
        ],
    )
    return text.encode(TEXT_ENCODING), helper_notes + notes


def apply_ark_cross_values_riscv64_arch(data: bytes) -> tuple[bytes, list[str]]:
    text = data.decode(TEXT_ENCODING, errors="ignore")
    if 'current_cpu == "riscv64"' in text and 'arch = "RISCV64"' in text:
        return data, ["ArkCompiler cross_values RISCV64 arch mapping already present"]
    old = '  } else if (current_cpu == "amd64" || current_cpu == "x64" ||\n'
    new = '  } else if (current_cpu == "riscv64") {\n    arch = "RISCV64"\n' + old
    if old in text:
        return text.replace(old, new, 1).encode(TEXT_ENCODING), [
            "added target-evidenced RISCV64 arch mapping to cross_values generation"
        ]
    return data, ["ArkCompiler cross_values RISCV64 arch insertion point not found"]


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
            notes.append(f"added {added} target-evidenced compile-standard whitelist entries to {key}")
        else:
            notes.append(f"target-evidenced compile-standard whitelist entries already present in {key}")

    if not notes:
        notes.append("no target-evidenced compile-standard whitelist entries matched requested prefixes")
    return (json.dumps(current, ensure_ascii=False, indent=4) + "\n").encode(TEXT_ENCODING), notes


def apply_hidumper_memory_raw_param_standalone_closure(data: bytes) -> tuple[bytes, list[str]]:
    text = data.decode(TEXT_ENCODING, errors="ignore")
    notes: list[str] = []
    start = text.find('ohos_source_set("hidumpermemory_source") {')
    if start < 0:
        return data, ["hidumpermemory_source insertion point not found"]

    def replace_after_start(old: str, new: str, note: str, already: str) -> None:
        nonlocal text
        if already in text[start:]:
            notes.append(f"{note} already present")
            return
        index = text.find(old, start)
        if index < 0:
            notes.append(f"{note} insertion point not found")
            return
        text = text[:index] + new + text[index + len(old):]
        notes.append(note)

    replace_after_start(
        '    "native/src/dump_common_utils.cpp",\n  ]',
        '    "native/src/dump_common_utils.cpp",\n    "native/src/raw_param.cpp",\n  ]',
        "added raw_param.cpp to hidumpermemory_source",
        '"native/src/raw_param.cpp"',
    )
    replace_after_start(
        '    "${hidumper_service_path}:service_config",\n  ]',
        '    "${hidumper_service_path}:service_config",\n    "${hidumper_service_path}:zidl_config",\n  ]',
        "added zidl_config to hidumpermemory_source configs",
        '"${hidumper_service_path}:zidl_config"',
    )
    replace_after_start(
        '  deps = [ "${hidumper_utils_path}:utils" ]',
        '  deps = [\n    "${hidumper_service_path}:zidl_service",\n    "${hidumper_utils_path}:utils",\n  ]',
        "added zidl_service dependency to hidumpermemory_source",
        '"${hidumper_service_path}:zidl_service"',
    )
    replace_after_start(
        "  defines = []",
        '  defines = []\n  defines += [ "HIDUMPER_RAW_PARAM_STANDALONE" ]',
        "added HIDUMPER_RAW_PARAM_STANDALONE define to hidumpermemory_source",
        "HIDUMPER_RAW_PARAM_STANDALONE",
    )
    return text.encode(TEXT_ENCODING), notes


def apply_hidumper_raw_param_standalone_guard(data: bytes) -> tuple[bytes, list[str]]:
    text = data.decode(TEXT_ENCODING, errors="ignore")
    notes: list[str] = []
    if "#ifndef HIDUMPER_RAW_PARAM_STANDALONE" in text:
        notes.append("RawParam standalone guard already present")
    else:
        include_old = '#include "hilog_wrapper.h"\n#include "dump_manager_service.h"\n'
        include_new = (
            '#include "hilog_wrapper.h"\n'
            "#ifndef HIDUMPER_RAW_PARAM_STANDALONE\n"
            '#include "dump_manager_service.h"\n'
            "#endif\n"
        )
        if include_old in text:
            text = text.replace(include_old, include_new, 1)
            notes.append("guarded dump_manager_service include for standalone RawParam use")
        else:
            notes.append("RawParam include guard insertion point not found")

        singleton_old = (
            "    auto dumpManagerService = DumpDelayedSpSingleton<DumpManagerService>::GetInstance();\n"
            "    if (dumpManagerService == nullptr) {\n"
            "        return;\n"
            "    }\n"
        )
        singleton_new = (
            "#ifndef HIDUMPER_RAW_PARAM_STANDALONE\n"
            + singleton_old
            + "#endif\n"
        )
        if singleton_old in text:
            text = text.replace(singleton_old, singleton_new, 1)
            notes.append("guarded DumpManagerService singleton lookup for standalone RawParam use")
        else:
            notes.append("RawParam singleton guard insertion point not found")
    return text.encode(TEXT_ENCODING), notes


def apply_compile_app_root_ohpm_path_resolution(data: bytes) -> tuple[bytes, list[str]]:
    text = data.decode(TEXT_ENCODING, errors="ignore")
    desired_root = "    root_dir = os.path.abspath(get_root_dir())\n"
    desired_path = 'ohpm_path = os.path.join(root_dir, "prebuilts/tool/command-line-tools/ohpm/bin/ohpm")'
    notes: list[str] = []

    if desired_root not in text and "    root_dir = get_root_dir()\n" in text:
        text = text.replace("    root_dir = get_root_dir()\n", desired_root, 1)
        notes.append("normalized OpenHarmony root to an absolute path before app cwd switch")

    if desired_path not in text:
        if "import os\n" not in text:
            text = text.replace("import sys\n", "import sys\nimport os\n", 1)
            notes.append("added os import for source-root ohpm path resolution")

        root_block = (
            desired_root
            + f"    {desired_path}\n"
            + "    if not os.path.exists(ohpm_path):\n"
            + '        ohpm_path = "ohpm"\n'
        )
        if desired_root not in text and "    root_dir = get_root_dir()\n" not in text and "    cur_dir = os.getcwd()\n" in text:
            text = text.replace("    cur_dir = os.getcwd()\n", "    cur_dir = os.getcwd()\n" + root_block, 1)
            notes.append("inserted source-root ohpm path before app cwd switch")
        elif desired_root in text or "    root_dir = get_root_dir()\n" in text:
            text = re.sub(
                r"    ohpm_path\s*=\s*['\"][^'\"]*prebuilts/tool/command-line-tools/ohpm/bin/ohpm['\"]\n",
                f"    {desired_path}\n",
                text,
                count=1,
            )
            if desired_path in text:
                notes.append("rewrote ohpm_path to source-root prebuilt path")

    replacements = [
        (
            "        ohpm_install_cmd = ['../../prebuilts/tool/command-line-tools/ohpm/bin/ohpm', 'install']",
            "        ohpm_install_cmd = [ohpm_path, 'install']",
        ),
        (
            '        ohpm_install_cmd = ["../../prebuilts/tool/command-line-tools/ohpm/bin/ohpm", "install"]',
            "        ohpm_install_cmd = [ohpm_path, 'install']",
        ),
        (
            "        ohpm_install_cmd = [os.path.join('../../prebuilts/tool/command-line-tools/ohpm/bin/ohpm'), 'install']",
            "        ohpm_install_cmd = [ohpm_path, 'install']",
        ),
    ]
    for old, new in replacements:
        if old in text:
            text = text.replace(old, new, 1)
            notes.append("rewrote ohpm install command to use resolved ohpm_path")

    if desired_path in text and "ohpm_install_cmd = [ohpm_path, 'install']" in text:
        if not notes:
            notes.append("compile_app.py already resolves ohpm from the OpenHarmony source root")
        return text.encode(TEXT_ENCODING), notes
    return data, notes or ["compile_app.py ohpm path transform skipped: insertion point not found"]


def apply_rust_cxxbridge_empty_output_fake_header_fallback(data: bytes) -> tuple[bytes, list[str]]:
    text = data.decode(TEXT_ENCODING, errors="ignore")
    marker = "OPENHARMONY_PORTING_FAKE_CXXBRIDGE_EMPTY_OUTPUT_V5"
    legacy_markers = [
        "OPENHARMONY_PORTING_FAKE_CXXBRIDGE_EMPTY_OUTPUT_V4",
        "OPENHARMONY_PORTING_FAKE_CXXBRIDGE_EMPTY_OUTPUT_V3",
        "OPENHARMONY_PORTING_FAKE_CXXBRIDGE_EMPTY_OUTPUT_V2",
        "OPENHARMONY_PORTING_FAKE_CXXBRIDGE_EMPTY_OUTPUT",
    ]
    if marker in text:
        return data, ["rust_cxxbridge.py already has typed empty-output fake header fallback scoped to bridge module body"]

    notes: list[str] = []
    if "import re\n" not in text:
        if "import argparse\n" in text:
            text = text.replace("import argparse\n", "import argparse\nimport re\n", 1)
            notes.append("added re import for cxxbridge source parsing")
        else:
            return data, ["rust_cxxbridge fallback transform skipped: import insertion point not found"]

    helper = r'''

# OPENHARMONY_PORTING_FAKE_CXXBRIDGE_EMPTY_OUTPUT_V5
def _fake_bridge_source_path(args):
    for arg in args:
        if arg == "--" or not arg.endswith(".rs"):
            continue
        path = arg if os.path.isabs(arg) else os.path.abspath(arg)
        if os.path.isfile(path):
            return path
    return None


def _fake_bridge_namespace(source_text):
    match = re.search(r"#\s*\[\s*cxx::bridge\s*(?:\(\s*namespace\s*=\s*\"([^\"]+)\"\s*\))?\s*\]", source_text)
    if not match:
        return ""
    return match.group(1) or ""


def _fake_bridge_body(source_text):
    bridge_match = re.search(r"#\s*\[\s*cxx::bridge[^\]]*\]\s*mod\s+[A-Za-z_][A-Za-z0-9_]*\s*\{", source_text)
    if not bridge_match:
        bridge_pos = source_text.find("#[cxx::bridge")
        return source_text[bridge_pos:] if bridge_pos != -1 else source_text
    start = bridge_match.end()
    depth = 1
    index = start
    while index < len(source_text):
        char = source_text[index]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return source_text[start:index]
        index += 1
    return source_text[start:]


def _fake_bridge_cpp_type(rust_type, type_namespaces=None):
    type_namespaces = type_namespaces or {}
    rust_type = (rust_type or "").strip()
    rust_type = re.sub(r"^pub(?:\([^)]*\))?\s+", "", rust_type)
    rust_type = re.sub(r"\s+", " ", rust_type)
    rust_type = re.sub(r"^&\s*'static\s+", "&", rust_type)
    rust_type = rust_type.replace("&'a str", "&str").replace("& str", "&str")
    mapping = {
        "i8": "int8_t",
        "i16": "int16_t",
        "i32": "int32_t",
        "i64": "int64_t",
        "u8": "uint8_t",
        "u16": "uint16_t",
        "u32": "uint32_t",
        "u64": "uint64_t",
        "usize": "size_t",
        "bool": "bool",
        "f32": "float",
        "f64": "double",
        "String": "rust::String",
        "&str": "rust::Str",
        "&[u8]": "rust::Slice<const uint8_t>",
        "*const CacheDownloadService": "const CacheDownloadService *",
    }
    if rust_type in mapping:
        return mapping[rust_type]
    shared = re.fullmatch(r"SharedPtr\s*<\s*([A-Za-z_][A-Za-z0-9_]*)\s*>", rust_type)
    if shared:
        inner = _fake_bridge_cpp_type(shared.group(1), type_namespaces)
        return f"std::shared_ptr<{inner}>"
    unique = re.fullmatch(r"UniquePtr\s*<\s*([A-Za-z_][A-Za-z0-9_]*)\s*>", rust_type)
    if unique:
        inner = _fake_bridge_cpp_type(unique.group(1), type_namespaces)
        return f"std::unique_ptr<{inner}>"
    vec = re.fullmatch(r"Vec\s*<\s*(.*?)\s*>", rust_type)
    if vec:
        item_type = _fake_bridge_cpp_type(vec.group(1), type_namespaces)
        return f"rust::Vec<{item_type}>"
    if rust_type in type_namespaces:
        namespace = type_namespaces[rust_type]
        return f"{namespace}::{rust_type}" if namespace else rust_type
    if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", rust_type):
        return rust_type
    return "void"


def _fake_bridge_return_type(ret, type_namespaces=None):
    cpp_type = _fake_bridge_cpp_type(ret, type_namespaces)
    mapping = {
        "int8_t": "return 0;",
        "int16_t": "return 0;",
        "int32_t": "return 0;",
        "int64_t": "return 0;",
        "uint8_t": "return 0;",
        "uint16_t": "return 0;",
        "uint32_t": "return 0;",
        "uint64_t": "return 0;",
        "size_t": "return 0;",
        "bool": "return false;",
        "float": "return 0.0F;",
        "double": "return 0.0;",
        "const CacheDownloadService *": "return nullptr;",
    }
    if cpp_type == "void":
        return "void", ""
    return cpp_type, mapping.get(cpp_type, "return {};")


def _fake_bridge_structs(source_text):
    source_text = _fake_bridge_body(source_text)
    structs = []
    for match in re.finditer(
        r"(?:pub(?:\([^)]*\))?\s+)?struct\s+([A-Za-z_][A-Za-z0-9_]*)(?:\s*<[^>{}]+>)?\s*\{(.*?)\}",
        source_text,
        flags=re.S,
    ):
        name = match.group(1)
        body = match.group(2)
        fields = []
        for field_match in re.finditer(
            r"(?:pub(?:\([^)]*\))?\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*:\s*([^,\n]+),",
            body,
        ):
            fields.append((field_match.group(1), field_match.group(2)))
        if fields:
            structs.append((name, fields))
    return structs


def _fake_bridge_struct_dependencies(field_type, struct_names):
    return {
        token
        for token in re.findall(r"[A-Za-z_][A-Za-z0-9_]*", field_type or "")
        if token in struct_names
    }


def _fake_bridge_order_structs(structs):
    struct_names = {name for name, _fields in structs}
    emitted = set()
    ordered = []
    pending = list(structs)
    while pending:
        next_pending = []
        progressed = False
        for name, fields in pending:
            deps = set()
            for _field_name, field_type in fields:
                deps.update(_fake_bridge_struct_dependencies(field_type, struct_names))
            deps.discard(name)
            if deps.issubset(emitted):
                ordered.append((name, fields))
                emitted.add(name)
                progressed = True
            else:
                next_pending.append((name, fields))
        if not progressed:
            ordered.extend(next_pending)
            break
        pending = next_pending
    return ordered


def _fake_bridge_enum_underlying(attrs):
    repr_match = re.search(r"#\s*\[\s*repr\s*\(\s*([A-Za-z0-9_]+)\s*\)\s*\]", attrs or "")
    repr_name = repr_match.group(1) if repr_match else "u32"
    mapping = {
        "u8": "uint8_t",
        "u16": "uint16_t",
        "u32": "uint32_t",
        "u64": "uint64_t",
        "i8": "int8_t",
        "i16": "int16_t",
        "i32": "int32_t",
        "i64": "int64_t",
    }
    return mapping.get(repr_name, "uint32_t")


def _fake_bridge_enum_variants(body):
    variants = []
    for raw_entry in (body or "").split(","):
        entry = re.sub(r"//.*", "", raw_entry)
        entry = re.sub(r"(?m)^\s*///.*$", "", entry)
        entry = re.sub(r"#\s*\[[^\]]+\]\s*", "", entry)
        entry = entry.strip()
        if not entry:
            continue
        match = re.match(r"([A-Za-z_][A-Za-z0-9_]*)(?:\s*=\s*([^,]+))?", entry)
        if not match:
            continue
        value = (match.group(2) or "").strip()
        variants.append((match.group(1), value))
    return variants


def _fake_bridge_enums(source_text):
    source_text = _fake_bridge_body(source_text)
    enums = []
    enum_re = re.compile(
        r"((?:(?:\s*#\s*\[[^\]]+\]\s*)|(?:\s*///[^\n]*\n))*)"
        r"(?:pub(?:\([^)]*\))?\s+)?enum\s+([A-Za-z_][A-Za-z0-9_]*)\s*\{(.*?)\}",
        flags=re.S,
    )
    for match in enum_re.finditer(source_text):
        attrs = match.group(1) or ""
        name = match.group(2)
        variants = _fake_bridge_enum_variants(match.group(3))
        if variants:
            enums.append((name, _fake_bridge_enum_underlying(attrs), variants))
    return enums


def _fake_bridge_includes(source_text):
    source_text = _fake_bridge_body(source_text)
    includes = []
    seen = set()
    for include in re.findall(r'include!\s*\(\s*"([^"]+)"\s*\)', source_text):
        if include in seen:
            continue
        seen.add(include)
        includes.append(include)
    return includes


def _fake_bridge_type_namespaces(source_text):
    source_text = _fake_bridge_body(source_text)
    type_namespaces = {}
    pattern = re.compile(
        r'(?:#\s*\[\s*namespace\s*=\s*"([^"]+)"\s*\]\s*)?'
        r'(?:#\s*\[[^\]]+\]\s*)*'
        r'(?:enum|type)\s+([A-Za-z_][A-Za-z0-9_]*)',
        flags=re.S,
    )
    for namespace, name in pattern.findall(source_text):
        if namespace:
            type_namespaces[name] = namespace
    return type_namespaces


def _fake_bridge_rust_items(source_text):
    source_text = _fake_bridge_body(source_text)
    blocks = re.findall(r'extern\s+"Rust"\s*\{(.*?)\}', source_text, flags=re.S)
    rust_types = {}
    free_functions = []
    token_re = re.compile(
        r"type\s+([A-Za-z_][A-Za-z0-9_]*)\s*;"
        r"|(?:unsafe\s+)?fn\s+([A-Za-z_][A-Za-z0-9_]*)\s*\((.*?)\)\s*(?:->\s*([^;{}]+))?\s*;",
        flags=re.S,
    )
    for block in blocks:
        current_type = None
        for match in token_re.finditer(block):
            if match.group(1):
                current_type = match.group(1)
                rust_types.setdefault(current_type, [])
                continue
            fn_name = match.group(2)
            params = match.group(3) or ""
            ret = match.group(4) or ""
            owner = None
            for pattern in (
                r"self\s*:\s*&\s*(?:'[A-Za-z_][A-Za-z0-9_]*\s+)?mut\s*([A-Za-z_][A-Za-z0-9_]*)",
                r"self\s*:\s*&\s*(?:'[A-Za-z_][A-Za-z0-9_]*\s+)?([A-Za-z_][A-Za-z0-9_]*)",
                r"self\s*:\s*Pin\s*<\s*&\s*mut\s*([A-Za-z_][A-Za-z0-9_]*)\s*>",
            ):
                owner_match = re.search(pattern, params)
                if owner_match:
                    owner = owner_match.group(1)
                    break
            if owner is None and re.search(r"(^|,)\s*(?:&\s*mut\s+self|&\s*self|self)\s*(?:,|$)", params):
                owner = current_type
            if owner:
                rust_types.setdefault(owner, []).append((fn_name, ret))
            else:
                free_functions.append((fn_name, ret))
    return rust_types, free_functions


def _fake_bridge_qualified(namespace, type_name):
    parts = [part for part in namespace.split("::") if part]
    return "::" + "::".join(parts + [type_name]) if parts else "::" + type_name


def _fake_bridge_method_line(fn_name, ret, type_namespaces):
    cpp_ret, statement = _fake_bridge_return_type(ret, type_namespaces)
    prefix = f"    template <typename... Args> {cpp_ret} {fn_name}(Args&&...) const noexcept"
    if statement:
        return f"{prefix} {{ {statement} }}"
    return f"{prefix} {{}}"


def _fake_bridge_free_function_line(fn_name, ret, type_namespaces):
    cpp_ret, statement = _fake_bridge_return_type(ret, type_namespaces)
    prefix = f"template <typename... Args> {cpp_ret} {fn_name}(Args&&...) noexcept"
    if statement:
        return f"{prefix} {{ {statement} }}"
    return f"{prefix} {{}}"


def _fake_bridge_header(source_text):
    rust_types, free_functions = _fake_bridge_rust_items(source_text)
    structs = _fake_bridge_order_structs(_fake_bridge_structs(source_text))
    enums = _fake_bridge_enums(source_text)
    includes = _fake_bridge_includes(source_text)
    type_namespaces = _fake_bridge_type_namespaces(source_text)
    if not rust_types and not free_functions and not structs and not enums:
        return None
    namespace = _fake_bridge_namespace(source_text)
    lines = [
        "#pragma once",
        "/* Compile-only fake cxxbridge header generated because cxxbridge produced empty output. */",
        "#include <cstddef>",
        "#include <cstdint>",
        "#include <memory>",
        "#include \"cxx.h\"",
    ]
    for include in includes:
        lines.append(f"#include \"{include}\"")
    lines.append("")
    namespace_parts = [part for part in namespace.split("::") if part]
    for part in namespace_parts:
        lines.append(f"namespace {part} {{")
    for enum_name, underlying, variants in enums:
        lines.append(f"enum class {enum_name} : {underlying} {{")
        for variant_name, value in variants:
            suffix = f" = {value}" if value else ""
            lines.append(f"    {variant_name}{suffix},")
        lines.append("};")
        lines.append("")
    for struct_name, fields in structs:
        lines.append(f"struct {struct_name} {{")
        for field_name, field_type in fields:
            lines.append(f"    {_fake_bridge_cpp_type(field_type, type_namespaces)} {field_name};")
        lines.append("};")
        lines.append("")
    for type_name, methods in rust_types.items():
        lines.append(f"struct {type_name} final {{")
        if not methods:
            lines.append(f"    {type_name}() = default;")
        for fn_name, ret in methods:
            lines.append(_fake_bridge_method_line(fn_name, ret, type_namespaces))
        lines.append("};")
        lines.append("")
    for fn_name, ret in free_functions:
        lines.append(_fake_bridge_free_function_line(fn_name, ret, type_namespaces))
    for part in reversed(namespace_parts):
        lines.append(f"}} // namespace {part}")
    lines.extend(
        [
            "namespace rust {",
            "inline namespace cxxbridge1 {",
        ]
    )
    for type_name in rust_types:
        lines.append(f"template <> inline void Box<{_fake_bridge_qualified(namespace, type_name)}>::drop() noexcept {{}}")
    lines.extend(
        [
            "} // namespace cxxbridge1",
            "} // namespace rust",
            "",
        ]
    )
    return ("\n".join(lines) + "\n").encode("utf-8")


def _fake_bridge_empty_output(args, is_header_file):
    source_path = _fake_bridge_source_path(args)
    if source_path is None:
        return None
    try:
        source_text = open(source_path, encoding="utf-8", errors="ignore").read()
    except OSError:
        return None
    if "#[cxx::bridge" not in source_text:
        return None
    if is_header_file:
        return _fake_bridge_header(source_text)
    return b"/* Compile-only fake cxxbridge cc generated because cxxbridge produced empty output. */\n"
'''

    if "\ndef run(cxx_exe, args, output, is_header_file):\n" not in text:
        return data, ["rust_cxxbridge fallback transform skipped: run() insertion point not found"]
    legacy_start = -1
    for legacy_marker in legacy_markers:
        legacy_start = text.find("\n# " + legacy_marker)
        if legacy_start != -1:
            break
    if legacy_start != -1:
        start = legacy_start
        end = text.find("\ndef run(cxx_exe, args, output, is_header_file):\n", start)
        if start == -1 or end == -1:
            return data, ["rust_cxxbridge fallback transform skipped: legacy helper replacement bounds not found"]
        text = text[:start] + helper + text[end:]
        notes.append("upgraded compile-only cxxbridge fallback to typed template method stubs")
    else:
        text = text.replace("\ndef run(cxx_exe, args, output, is_header_file):\n", helper + "\ndef run(cxx_exe, args, output, is_header_file):\n", 1)
        notes.append("inserted compile-only cxxbridge empty-output fallback helpers")

    old = (
        "    if res.returncode != 0:\n"
        "        return res.returncode\n"
        "    with build_utils.atomic_output(output) as output:\n"
        "        output.write(res.stdout)\n"
    )
    new = (
        "    if res.returncode != 0:\n"
        "        return res.returncode\n"
        "    stdout = res.stdout\n"
        "    if not stdout:\n"
        "        fake_stdout = _fake_bridge_empty_output(args, is_header_file)\n"
        "        if fake_stdout is not None:\n"
        "            stdout = fake_stdout\n"
        "    with build_utils.atomic_output(output) as output:\n"
        "        output.write(stdout)\n"
    )
    if old not in text:
        if "fake_stdout = _fake_bridge_empty_output(args, is_header_file)" in text and "output.write(stdout)" in text:
            notes.append("empty cxxbridge stdout routing already present")
            return text.encode(TEXT_ENCODING), notes
        return data, ["rust_cxxbridge fallback transform skipped: run() output write block not found"]
    text = text.replace(old, new, 1)
    notes.append("routed empty cxxbridge stdout through fake header/cc generator")
    return text.encode(TEXT_ENCODING), notes


def apply_rust_template_restore_source_forwarding(data: bytes) -> tuple[bytes, list[str]]:
    text = data.decode(TEXT_ENCODING, errors="ignore")
    notes: list[str] = []

    sources_exclusion = '                             "sources",\n'
    if sources_exclusion in text:
        text = text.replace(sources_exclusion, "", 1)
        notes.append("removed stale sources exclusion so invoker.sources is forwarded into rust targets")

    stale_guard = (
        '    if (target_cpu != "riscv64") {\n'
        "      rustflags = _rustflags\n"
        "      sources = invoker.sources\n"
        "    }\n"
    )
    if stale_guard in text:
        text = text.replace(stale_guard, "    rustflags = _rustflags\n", 1)
        notes.append("removed stale riscv64 Rust source-suppression guard")

    if not notes and "rustflags = _rustflags" in text and sources_exclusion not in text:
        notes.append("Rust template source forwarding already matches target-evidenced form")
        return data, notes
    if notes:
        return text.encode(TEXT_ENCODING), notes
    return data, ["Rust template source-forwarding transform skipped: stale guard not found"]


def gn_flag_path(path: str) -> str:
    path = path.strip()
    if not path or re.search(r"[\s\"$]", path):
        return ""
    return path


def apply_host_clang_x64_cxx_stdlib_paths(
    data: bytes,
    include_paths: list[str],
    library_paths: list[str],
) -> tuple[bytes, list[str]]:
    text = data.decode(TEXT_ENCODING, errors="ignore")
    marker = 'clang_toolchain("clang_x64") {'
    start = text.find(marker)
    if start < 0:
        return data, ["linux clang_x64 toolchain block not found"]

    brace = text.find("{", start)
    depth = 0
    end = -1
    for index in range(brace, len(text)):
        char = text[index]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                end = index + 1
                break
    if end < 0:
        return data, ["linux clang_x64 toolchain block end not found"]

    block = text[start:end]
    sentinel = "# OpenHarmony porting: scope host GCC C++ stdlib paths to clang_x64 only."
    if sentinel in block:
        return data, ["host clang_x64 C++ stdlib paths already scoped in toolchain block"]
    if "extra_cxxflags" in block:
        return data, ["host clang_x64 C++ stdlib transform skipped: extra_cxxflags already defined"]

    safe_includes = [gn_flag_path(path) for path in include_paths]
    safe_includes = [path for path in safe_includes if path]
    if not safe_includes:
        return data, ["host clang_x64 C++ stdlib transform skipped: no safe include paths"]
    safe_libs = [gn_flag_path(path) for path in library_paths]
    safe_libs = [path for path in safe_libs if path]

    lines = [
        "",
        f"  {sentinel}",
        '  extra_cxxflags = "' + " ".join(f"-isystem{path}" for path in safe_includes) + '"',
    ]
    if safe_libs and "extra_ldflags" not in block:
        lines.append('  extra_ldflags = "' + " ".join(f"-L{path}" for path in safe_libs) + '"')
    elif safe_libs:
        lines.append("  # Host C++ library paths detected but extra_ldflags is already defined in this block.")
    insertion = "\n".join(lines) + "\n"

    anchor = "  enable_linker_map = true\n"
    anchor_index = block.find(anchor)
    if anchor_index < 0:
        return data, ["host clang_x64 C++ stdlib insertion point not found"]
    insert_at = anchor_index + len(anchor)
    new_block = block[:insert_at] + insertion + block[insert_at:]
    new_text = text[:start] + new_block + text[end:]
    notes = [
        "scoped host C++ stdlib include paths to linux clang_x64 extra_cxxflags",
        f"include_paths={safe_includes}",
    ]
    if safe_libs:
        notes.append(f"library_paths={safe_libs}")
    return new_text.encode(TEXT_ENCODING), notes


def apply_clang_toolchain_extra_flags_forwarding(data: bytes) -> tuple[bytes, list[str]]:
    text = data.decode(TEXT_ENCODING, errors="ignore")
    if '"extra_cxxflags"' in text and '"extra_ldflags"' in text:
        return data, ["clang_toolchain already forwards extra_cxxflags and extra_ldflags"]
    anchor = '                             "rust_abi_target",\n'
    if anchor not in text:
        return data, ["clang_toolchain extra flag forwarding insertion point not found"]
    insertion = (
        anchor
        + '                             "extra_cxxflags",\n'
        + '                             "extra_ldflags",\n'
    )
    new_text = text.replace(anchor, insertion, 1)
    return new_text.encode(TEXT_ENCODING), [
        "forwarded extra_cxxflags and extra_ldflags from clang_toolchain invoker to gcc_toolchain"
    ]


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
    if action.get("content_source") == "generated_fake_shared_library":
        source_path = target_root / clean_str(action.get("source_path"), rel_path)
        data, notes = generate_fake_shared_library_bytes(workspace, target, rel_path, source_path)
        if data is None:
            return None, str(source_path), "fake_shared_library_generation_failed", notes
        return data, str(source_path), "available", notes
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
        elif (
            rel_path == "build/rust/rustc_toolchain.gni"
            and action.get("source_role") == "rust_riscv64_toolchain_gni"
            and target.get("architecture") == "riscv64"
        ):
            data, transforms = apply_rust_riscv64_toolchain_host_split(data)
        elif (
            rel_path == "base/hiviewdfx/hidumper/services/native/src/raw_param.cpp"
            and action.get("source_role") == "hidumper_raw_param_standalone_guard"
        ):
            data, transforms = apply_hidumper_raw_param_standalone_guard(data)
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
            rel_path == "arkcompiler/runtime_core/static_core/libpandabase/utils/arch.h"
            and action.get("source_role") == "arkcompiler_runtime_riscv64_arch_traits"
            and target.get("architecture") == "riscv64"
        ):
            data, transforms = apply_ark_runtime_riscv64_arch_traits(data)
        elif (
            rel_path == "arkcompiler/runtime_core/static_core/runtime/arch/helpers.h"
            and action.get("source_role") == "arkcompiler_runtime_riscv64_ext_arch_traits"
            and target.get("architecture") == "riscv64"
        ):
            data, transforms = apply_ark_runtime_riscv64_ext_arch_traits(data)
        elif (
            rel_path == "arkcompiler/runtime_core/static_core/runtime/arch/memory_helpers.h"
            and action.get("source_role") == "arkcompiler_runtime_riscv64_memory_helpers"
            and target.get("architecture") == "riscv64"
        ):
            data, transforms = apply_ark_runtime_riscv64_memory_helpers(data)
        elif (
            rel_path == "arkcompiler/runtime_core/static_core/runtime/arch/asm_support.h"
            and action.get("source_role") == "arkcompiler_runtime_riscv64_asm_support"
            and target.get("architecture") == "riscv64"
        ):
            data, transforms = apply_ark_runtime_riscv64_asm_support(data)
        elif (
            rel_path == "arkcompiler/runtime_core/static_core/runtime/fibers/fiber_context.h"
            and action.get("source_role") == "arkcompiler_runtime_riscv64_fiber_context"
            and target.get("architecture") == "riscv64"
        ):
            data, transforms = apply_ark_runtime_riscv64_fiber_context(data)
        elif (
            rel_path == "arkcompiler/runtime_core/static_core/runtime/fibers/arch/asm_macros.h"
            and action.get("source_role") == "arkcompiler_runtime_riscv64_fiber_asm_macros"
            and target.get("architecture") == "riscv64"
        ):
            data, transforms = apply_ark_runtime_riscv64_fiber_asm_macros(data)
        elif (
            rel_path == "arkcompiler/runtime_core/static_core/runtime/signal_handler.h"
            and action.get("source_role") == "arkcompiler_runtime_riscv64_signal_context"
            and target.get("architecture") == "riscv64"
        ):
            data, transforms = apply_ark_runtime_riscv64_signal_context(data)
        elif (
            rel_path == "arkcompiler/runtime_core/static_core/runtime/include/object_accessor.h"
            and action.get("source_role") == "arkcompiler_runtime_riscv64_object_accessor_overlap_guard"
            and target.get("architecture") == "riscv64"
        ):
            data, transforms = apply_ark_runtime_riscv64_object_accessor_guard(data)
        elif (
            rel_path == "arkcompiler/runtime_core/static_core/runtime/BUILD.gn"
            and action.get("source_role") == "arkcompiler_runtime_riscv64_build_sources"
            and target.get("architecture") == "riscv64"
        ):
            data, transforms = apply_ark_runtime_riscv64_build_sources(data)
        elif (
            rel_path == ARK_RUNTIME_ASM_SUPPORT_CPP_REL
            and action.get("source_role") == "arkcompiler_runtime_riscv64_osr_fallback_guard"
            and target.get("architecture") == "riscv64"
        ):
            data, transforms = apply_ark_runtime_riscv64_osr_fallback_guard(data)
        elif (
            rel_path == ARK_ETS_SUBPROJECT_SOURCES_REL
            and action.get("source_role") == "arkcompiler_ets_riscv64_bridge_sources"
            and target.get("architecture") == "riscv64"
        ):
            data, transforms = apply_ark_ets_riscv64_bridge_sources(data)
        elif (
            rel_path == "arkcompiler/runtime_core/static_core/runtime/bridge/arch/riscv64/proxy_entrypoint_riscv64.S"
            and action.get("source_role") == "arkcompiler_ets_riscv64_bridge_source"
            and target.get("architecture") == "riscv64"
        ):
            data, transforms = apply_ark_riscv64_proxy_entrypoint_large_thread_offsets(data)
        elif (
            rel_path == "arkcompiler/runtime_core/static_core/cross_values/BUILD.gn"
            and action.get("source_role") == "arkcompiler_cross_values_riscv64_arch"
            and target.get("architecture") == "riscv64"
        ):
            data, transforms = apply_ark_cross_values_riscv64_arch(data)
        elif (
            rel_path == "arkcompiler/runtime_core/static_core/runtime/entrypoints/string_index_of.h"
            and action.get("source_role") == "arkcompiler_riscv64_string_index_little_endian_guard"
            and target.get("architecture") == "riscv64"
        ):
            data, transforms = apply_ark_riscv64_string_index_guard(data)
        elif (
            rel_path
            == "arkcompiler/runtime_core/static_core/plugins/ets/runtime/intrinsics/helpers/ets_to_string_cache.cpp"
            and action.get("source_role") == "arkcompiler_riscv64_ets_to_string_cache_atomic_guard"
            and target.get("architecture") == "riscv64"
        ):
            data, transforms = apply_ark_riscv64_ets_to_string_cache_atomic_guard(data)
        elif (
            rel_path == "build/compile_standard_whitelist.json"
            and action.get("source_role")
            in {"soc_display_compile_standard_whitelist_entries", "target_compile_standard_whitelist_entries"}
        ):
            if action.get("source_role") == "soc_display_compile_standard_whitelist_entries":
                prefixes = [
                    f"//device/soc/{clean_str(target.get('soc_vendor'))}/{clean_str(target.get('soc'))}/hardware/display"
                ]
            else:
                prefixes = target_compile_standard_whitelist_prefixes(target)
            data, transforms = apply_target_compile_standard_whitelist_prefix_entries(data, target_root, prefixes)
        elif (
            rel_path == "base/hiviewdfx/hidumper/services/BUILD.gn"
            and action.get("source_role") == "hidumper_memory_raw_param_standalone_closure"
        ):
            data, transforms = apply_hidumper_memory_raw_param_standalone_closure(data)
        elif (
            rel_path == "build/scripts/compile_app.py"
            and action.get("source_role") == "compile_app_root_ohpm_path_resolution"
        ):
            data, transforms = apply_compile_app_root_ohpm_path_resolution(data)
        elif (
            rel_path == "build/templates/rust/rust_cxxbridge.py"
            and action.get("source_role") == "rust_cxxbridge_empty_output_fake_header_fallback"
        ):
            data, transforms = apply_rust_cxxbridge_empty_output_fake_header_fallback(data)
        elif (
            rel_path == "build/templates/rust/rust_template.gni"
            and action.get("source_role") == "rust_template_restore_source_forwarding"
        ):
            data, transforms = apply_rust_template_restore_source_forwarding(data)
        elif (
            rel_path == "build/toolchain/linux/BUILD.gn"
            and action.get("source_role") == "host_clang_x64_cxx_stdlib_paths"
        ):
            data, transforms = apply_host_clang_x64_cxx_stdlib_paths(
                data,
                [clean_str(path, "") for path in action.get("host_cxx_include_paths") or []],
                [clean_str(path, "") for path in action.get("host_cxx_library_paths") or []],
            )
        elif (
            rel_path == "build/toolchain/gcc_toolchain.gni"
            and action.get("source_role") == "clang_toolchain_extra_flags_forwarding"
        ):
            data, transforms = apply_clang_toolchain_extra_flags_forwarding(data)
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
            rel_path == RUN_OBJCOPY_REL
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
            rel_path == "foundation/resourceschedule/ffrt/include/eu/co_routine.h"
            and action.get("source_role") == "ffrt_riscv64_stack_magic"
            and target.get("architecture") == "riscv64"
        ):
            data, transforms = apply_ffrt_riscv64_stack_magic_compat(data)
        elif (
            rel_path == "foundation/resourceschedule/ffrt/src/sched/task_client_adapter.h"
            and action.get("source_role") == "ffrt_riscv64_task_client_adapter_ctc_query_interval"
            and target.get("architecture") == "riscv64"
        ):
            data, transforms = apply_ffrt_riscv64_task_client_adapter_compat(data)
        elif (
            rel_path == "foundation/ability/ability_runtime/cj_environment/frameworks/cj_environment/BUILD.gn"
            and action.get("source_role") == "cj_environment_riscv64_app_define"
            and target.get("architecture") == "riscv64"
        ):
            data, transforms = apply_cj_environment_riscv64_app_define(data)
        elif (
            rel_path == "foundation/ability/ability_runtime/cj_environment/frameworks/cj_environment/src/cj_environment.cpp"
            and action.get("source_role") == "cj_environment_riscv64_app_lib_name"
            and target.get("architecture") == "riscv64"
        ):
            data, transforms = apply_cj_environment_riscv64_app_lib_name(data)
        elif (
            rel_path == "foundation/arkui/napi/BUILD.gn"
            and action.get("source_role") == "arkui_napi_riscv64_target_defines"
            and target.get("architecture") == "riscv64"
        ):
            data, transforms = apply_arkui_napi_riscv64_target_defines(data)
        elif (
            rel_path == GRAPHIC_2D_VSYNC_LOG_REL
            and action.get("source_role") == "graphic_2d_vsync_riscv64_log_format_macros"
            and target.get("architecture") == "riscv64"
        ):
            data, transforms = apply_graphic_2d_vsync_riscv64_log_format_macros(data)
        elif (
            rel_path == LUME_STATIC_PLUGIN_DECL_REL
            and action.get("source_role") == "graphic_3d_lume_riscv64_static_plugin_section"
            and target.get("architecture") == "riscv64"
        ):
            data, transforms = apply_lume_static_plugin_riscv64_section_alignment(data)
        elif (
            rel_path == "foundation/arkui/ace_engine/build/tools/run_objcopy.py"
            and action.get("source_role") == "arkui_run_objcopy_riscv64_compat"
            and target.get("architecture") == "riscv64"
        ):
            data, transforms = apply_riscv64_objcopy_compat(data)
        elif (
            rel_path == "build/config/BUILDCONFIG.gn"
            and action.get("source_role") == "riscv64_buildconfig_arch_mapping"
            and target.get("architecture") == "riscv64"
        ):
            data, transforms = apply_riscv64_buildconfig_arch_compat(data)
        elif (
            rel_path == "build/rust/rustc_toolchain.gni"
            and action.get("source_role") == "rust_riscv64_toolchain_gni"
            and target.get("architecture") == "riscv64"
        ):
            data, transforms = apply_rust_riscv64_toolchain_host_split(data)
        elif (
            rel_path == "build/toolchain/ohos/BUILD.gn"
            and action.get("source_role") == "ohos_toolchain_riscv64_rust_abi_target"
            and target.get("architecture") == "riscv64"
        ):
            data, transforms = apply_ohos_toolchain_riscv64_rust_abi_target(data)
        elif (
            rel_path == "build/config/compiler/BUILD.gn"
            and action.get("source_role") == "riscv64_compiler_ldflags_mabi_compat"
            and target.get("architecture") == "riscv64"
        ):
            data, transforms = apply_riscv64_compiler_ldflags_mabi_compat(data)
        elif (
            rel_path == "build/config/compiler/compiler.gni"
            and action.get("source_role") == "riscv64_disable_thin_lto_compat"
            and target.get("architecture") == "riscv64"
        ):
            data, transforms = apply_riscv64_disable_thin_lto_compat(data)
        elif (
            rel_path == ARK_ETS_RUNTIME_BUILD_REL
            and action.get("source_role") == "ark_jsruntime_riscv64_explicit_thin_lto_compat"
            and target.get("architecture") == "riscv64"
        ):
            data, transforms = apply_ark_jsruntime_riscv64_explicit_thin_lto_compat(data)
        elif (
            rel_path == ARK_ETS_RUNTIME_BUILD_REL
            and action.get("source_role") == "ark_jsruntime_riscv64_trampoline_source"
            and target.get("architecture") == "riscv64"
        ):
            data, transforms = apply_ark_jsruntime_riscv64_trampoline_source(data)
        elif (
            rel_path == SKIA_RASTER_PIPELINE_OPTS_REL
            and action.get("source_role") == "skia_raster_pipeline_riscv64_scalar_sqrt_fallback"
            and target.get("architecture") == "riscv64"
        ):
            data, transforms = apply_skia_raster_pipeline_riscv64_scalar_sqrt_fallback(data)
        elif (
            rel_path == "build/config/components/musl/BUILD.gn"
            and action.get("source_role") == "riscv64_musl_cflags_mabi_compat"
            and target.get("architecture") == "riscv64"
        ):
            data, transforms = apply_riscv64_musl_cflags_mabi_compat(data)
        elif (
            rel_path == "third_party/musl/BUILD.gn"
            and action.get("source_role") == "riscv64_musl_shared_no_lto_compat"
            and target.get("architecture") == "riscv64"
        ):
            data, transforms = apply_riscv64_musl_shared_no_lto_compat(data)
        elif (
            rel_path == "third_party/musl/musl_template.gni"
            and action.get("source_role") == "riscv64_musl_hook_cflags_mabi_compat"
            and target.get("architecture") == "riscv64"
        ):
            data, transforms = apply_riscv64_musl_hook_cflags_mabi_compat(data)
        elif (
            rel_path in TEE_RISCV64_BARRIER_SOURCE_RELS
            and action.get("source_role") == "tee_riscv64_barrier_asm_compat"
            and target.get("architecture") == "riscv64"
        ):
            data, transforms = apply_tee_riscv64_barrier_asm_compat(data)
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
    if (
        target.get("architecture") == "riscv64"
        and action.get("source_role") == "arkcompiler_runtime_riscv64_arch_source"
    ):
        if rel_path == "arkcompiler/runtime_core/static_core/runtime/arch/riscv64/call_runtime.S":
            data, asm_transforms = apply_ark_riscv64_call_runtime_large_thread_offsets(data)
            transforms.extend(asm_transforms)
        elif (
            rel_path
            == "arkcompiler/runtime_core/static_core/runtime/bridge/arch/riscv64/compiled_code_to_runtime_bridge_riscv64.S"
        ):
            data, asm_transforms = apply_ark_riscv64_compiled_bridge_large_thread_offsets(data)
            transforms.extend(asm_transforms)
        elif rel_path == "arkcompiler/runtime_core/static_core/runtime/arch/riscv64/tlab.S":
            data, asm_transforms = apply_ark_riscv64_tlab_large_thread_offsets(data)
            transforms.extend(asm_transforms)
    if (
        target.get("architecture") == "riscv64"
        and action.get("source_role") == "arkcompiler_ets_riscv64_bridge_source"
        and rel_path == "arkcompiler/runtime_core/static_core/runtime/bridge/arch/riscv64/proxy_entrypoint_riscv64.S"
    ):
        data, asm_transforms = apply_ark_riscv64_proxy_entrypoint_large_thread_offsets(data)
        transforms.extend(asm_transforms)
    data, subsystem_transforms = normalize_ohos_build_subsystem(data, action, target, normalize_subsystems)
    transforms.extend(subsystem_transforms)
    return data, str(source_path), "available", transforms


def fake_dependency_category(item: dict[str, Any]) -> tuple[str, str, str]:
    path = clean_str(item.get("path"), "")
    role = clean_str(item.get("source_role"), "")
    missing = clean_str(item.get("missing_dependency"), "").lower()
    lower_path = path.lower()
    if role == "fake_component_registry" or "/fake_components/" in f"/{lower_path}":
        return (
            "fake_component_registry",
            "Compile-only bundle registry shims that preserve product selection while real source parts are missing.",
            "Replace with real component source/bundle evidence, or remove only after an explicit product-scope decision.",
        )
    if "rustc-riscv" in lower_path or "rust" in lower_path or "rust" in missing:
        return (
            "rust_toolchain",
            "RISC-V Rust toolchain or Rust prebuilt placeholders used only to keep compile flow moving.",
            "Replace with provenance-checked prebuilts/rustc-riscv payloads before Rust, package, or runtime validation.",
        )
    if "base/web/webview" in lower_path or lower_path.endswith(".hap") or "prebuilt hap" in missing:
        return (
            "webview_prebuilt_apps",
            "WebView or prebuilt application payload placeholders.",
            "Replace with target-compatible HAP/prebuilt artifacts before image packaging or runtime validation.",
        )
    if lower_path.startswith("kernel/linux/"):
        return (
            "kernel_bsp_source",
            "Board kernel/BSP source markers or fake build bridges.",
            "Replace with provenance-checked board kernel source before boot, driver, or image validation.",
        )
    if "/kernel/ko/" in lower_path or lower_path.endswith(".ko"):
        return (
            "kernel_modules",
            "Board kernel module placeholders.",
            "Replace with modules produced by the real board kernel build before runtime validation.",
        )
    if "/kernel/boot/" in lower_path or lower_path.endswith((".bin", ".img", ".dtb", ".hcd")):
        return (
            "boot_firmware",
            "Bootloader, firmware, Bluetooth firmware, or board image placeholders.",
            "Replace with provenance-checked firmware/boot payloads before boot or hardware validation.",
        )
    if lower_path.startswith("device/soc/") and lower_path.endswith((".so", ".so.1", ".lib", ".bin")):
        return (
            "soc_proprietary_payloads",
            "SoC firmware or proprietary shared-library placeholders, including linkable ELF stubs.",
            "Replace with licensed target SoC vendor payloads before graphics, media, WiFi, or runtime validation.",
        )
    if lower_path.startswith("device/board/") or lower_path.startswith("vendor/"):
        return (
            "board_vendor_payloads",
            "Board/vendor payload placeholders outside the main kernel and SoC buckets.",
            "Replace with provenance-checked board/vendor payloads before device validation.",
        )
    return (
        "other_compile_only_fakes",
        "Other compile-only fake interfaces.",
        "Review and replace with real source or dependency evidence before completion claims.",
    )


def summarize_dependency_debt(fake_interfaces: list[dict[str, Any]]) -> dict[str, Any]:
    buckets: dict[str, dict[str, Any]] = {}
    for item in fake_interfaces:
        category, risk, follow_up = fake_dependency_category(item)
        bucket = buckets.setdefault(
            category,
            {
                "category": category,
                "count": 0,
                "risk": risk,
                "follow_up": follow_up,
                "sample_paths": [],
            },
        )
        bucket["count"] += 1
        if len(bucket["sample_paths"]) < 12:
            bucket["sample_paths"].append(clean_str(item.get("path"), "unknown"))
    categories = sorted(buckets.values(), key=lambda item: (-int(item["count"]), str(item["category"])))
    fake_component_count = sum(1 for item in fake_interfaces if fake_dependency_category(item)[0] == "fake_component_registry")
    return {
        "total_fake_interface_count": len(fake_interfaces),
        "category_count": len(categories),
        "categories": categories,
        "fake_component_registry_review": {
            "count": fake_component_count,
            "rule": (
                "Do not treat fake component bundle.json files as final porting work. "
                "If a real source component exists in the workspace or target-source evidence can import it, "
                "replace the fake registry with the real component before completion claims."
            ),
        },
    }


def readelf_header_text(workspace: Path, path: Path) -> str:
    readelf = llvm_readelf_path(workspace)
    if not readelf.is_file() or not path.is_file():
        return ""
    try:
        proc = subprocess.run(
            [str(readelf), "-h", str(path)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            errors="ignore",
            timeout=20,
            check=False,
        )
    except Exception:
        return ""
    if proc.returncode != 0:
        return proc.stdout + proc.stderr
    return proc.stdout


def skipped_regression_check(check_id: str, expectation: str, reason: str) -> dict[str, Any]:
    return {
        "id": check_id,
        "status": "skipped",
        "checked_count": 0,
        "sample_failures": [],
        "expectation": expectation,
        "reason": reason,
    }


def check_fake_shared_library_elf_headers(
    workspace: Path,
    target: dict[str, Any],
    results: list[dict[str, Any]],
) -> dict[str, Any]:
    fake_shared_libs = [
        workspace / clean_str(item.get("path"), "")
        for item in results
        if item.get("dependency_policy") == "compile_only_fake_shared_library"
    ]
    checked = 0
    failures: list[dict[str, str]] = []
    arch = clean_str(target.get("architecture"), "")
    for path in fake_shared_libs[:80]:
        if not path.is_file():
            failures.append({"path": str(path), "reason": "missing fake shared library in workspace"})
            continue
        header = readelf_header_text(workspace, path)
        checked += 1
        if arch == "riscv64":
            if "Machine:" not in header or "RISC-V" not in header:
                failures.append({"path": str(path), "reason": "ELF machine is not RISC-V"})
            elif "double-float ABI" not in header:
                failures.append({"path": str(path), "reason": "RISC-V ELF flags do not advertise double-float ABI"})
    status = "pass" if not failures else "fail"
    if not fake_shared_libs:
        status = "skipped"
    return {
        "id": "fake_shared_library_target_elf_header",
        "status": status,
        "checked_count": checked,
        "total_count": len(fake_shared_libs),
        "sample_failures": failures[:10],
        "command": "llvm-readelf -h",
        "expectation": "compile-only fake shared libraries match the target ELF machine/ABI",
    }


def check_riscv64_generated_objcopy_elf_flags(workspace: Path, product: str, target: dict[str, Any]) -> dict[str, Any]:
    if clean_str(target.get("architecture")) != "riscv64":
        return skipped_regression_check(
            "riscv64_generated_objcopy_elf_flags",
            "run_objcopy.py generated RISC-V resource objects advertise RVC double-float ABI",
            "target architecture is not riscv64",
        )
    candidates = [
        workspace / "out" / product / "obj/developtools/syscap_codec/napi/query_syscap.o",
    ]
    existing = [path for path in candidates if path.is_file()]
    if not existing:
        return skipped_regression_check(
            "riscv64_generated_objcopy_elf_flags",
            "run_objcopy.py generated RISC-V resource objects advertise RVC double-float ABI",
            "syscap generated object has not been produced yet",
        )
    failures: list[dict[str, str]] = []
    for path in existing:
        header = readelf_header_text(workspace, path)
        if "Machine:" not in header or "RISC-V" not in header:
            failures.append({"path": str(path), "reason": "ELF machine is not RISC-V"})
        elif "double-float ABI" not in header or "RVC" not in header:
            failures.append({"path": str(path), "reason": "RISC-V generated object is missing RVC double-float ABI flags"})
    return {
        "id": "riscv64_generated_objcopy_elf_flags",
        "status": "pass" if not failures else "fail",
        "checked_count": len(existing),
        "sample_failures": failures[:10],
        "command": "llvm-readelf -h",
        "expectation": "run_objcopy.py generated RISC-V resource objects advertise RVC double-float ABI",
    }


def check_rust_fake_archive_archives(workspace: Path, product: str, target: dict[str, Any]) -> dict[str, Any]:
    if clean_str(target.get("architecture")) != "riscv64" or not workspace_fake_rust_driver_enabled(workspace):
        return skipped_regression_check(
            "riscv64_fake_rust_archive_arch",
            "fake rustc-riscv archives contain only RISC-V ELF objects",
            "riscv64 fake rust driver is not active",
        )
    obj_root = workspace / "out" / product / "obj"
    if not obj_root.is_dir():
        return skipped_regression_check(
            "riscv64_fake_rust_archive_arch",
            "fake rustc-riscv archives contain only RISC-V ELF objects",
            "out/<product>/obj does not exist",
        )
    checked = 0
    failures: list[dict[str, str]] = []
    max_checked = 120
    for pattern in ("*.a", "*.rlib"):
        for archive in sorted(obj_root.rglob(pattern)):
            if not rust_archive_path_suggests_fake_driver_output(archive):
                continue
            checked += 1
            if archive_contains_non_riscv_elf_objects(workspace, archive):
                failures.append({"path": str(archive), "reason": "archive contains non-RISC-V ELF object(s)"})
                if len(failures) >= 10:
                    break
            if checked >= max_checked:
                break
        if len(failures) >= 10:
            break
        if checked >= max_checked:
            break
    return {
        "id": "riscv64_fake_rust_archive_arch",
        "status": "pass" if not failures else "fail",
        "checked_count": checked,
        "sample_failures": failures,
        "expectation": "fake rustc-riscv archives contain only RISC-V ELF objects",
    }


def check_build_log_old_errors_absent(build_result: dict[str, Any] | None) -> dict[str, Any]:
    patterns = {
        "libbt_vendor_compile_standard_mismatch": [
            "subsystem name or part name is incorrect",
            "//vendor/iscas/rvbook/bluetooth:libbt_vendor",
        ],
        "old_rust_wrong_arch_archive": [
            "is incompatible with elf64lriscv",
            "librust_",
            ".rcgu.",
        ],
        "old_objcopy_riscv64_keyerror": [
            "run_objcopy.py",
            "KeyError: 'riscv64'",
        ],
        "old_lto_float_abi_mismatch": [
            "cannot link object files with different floating-point ABI",
            "-flto=thin",
        ],
        "old_profiler_native_daemon_riscv64_arch_missing": [
            "developtools/profiler/device/plugins/native_daemon/include/register.h",
            "NOT SUPPORT ARCH",
            "buildArchType",
        ],
        "old_hiperf_riscv64_arch_missing": [
            "developtools/hiperf/include/register.h",
            "NOT SUPPORT ARCH",
            "BUILD_ARCH_TYPE",
        ],
        "old_arkui_napi_cj_support_riscv64_platform_missing": [
            "foundation/arkui/napi/native_engine/impl/ark/cj_support.cpp",
            "current platform not supported",
            "LIBS_NAME",
        ],
        "old_graphic_2d_vsync_riscv64_log_format_mismatch": [
            "foundation/graphic/graphic_2d/rosen/modules/composer/vsync",
            "format specifies type",
            "VPUB",
        ],
        "old_graphic_3d_lume_riscv64_static_plugin_section_missing": [
            "foundation/graphic/graphic_3d/lume",
            "static_plugin_decl.h",
            "DEFINE_STATIC_PLUGIN",
            "expected ')'",
        ],
        "old_skia_raster_pipeline_riscv64_sqrt_vector_index": [
            "third_party/skia/m133/src/opts/SkRasterPipeline_opts.h",
            "subscripted value is not an array",
            "SkOpts.o",
        ],
        "old_ark_jsruntime_riscv64_lazy_deopt_entry_missing": [
            "arkcompiler/ets_runtime/libark_jsruntime.so",
            "undefined symbol: LazyDeoptEntry",
        ],
        "old_riscv64_generated_objcopy_elf_flags_missing": [
            "libsystemcapability",
            "query_syscap.o",
            "cannot link object files with different floating-point ABI",
        ],
        "old_ark_runtime_riscv64_osr_duplicate_symbols": [
            "duplicate symbol: OsrEntryAfterCFrame",
            "asm_support.o",
            "osr_riscv64.o",
        ],
        "old_ark_ets_riscv64_bridge_sources_missing": [
            "arkcompiler/runtime_core/libarkruntime.so",
            "undefined symbol: EtsAsyncEntryPoint",
            "undefined symbol: JSRuntimeCallJSBridge",
        ],
        "old_ark_ets_riscv64_proxy_large_thread_offsets": [
            "ets_proxy_entry_point_riscv64.S",
            "operand must be a symbol",
            "2392(tp)",
        ],
        "old_ark_ets_riscv64_proxy_method_invoke_missing": [
            "arkcompiler/runtime_core/libarkruntime.so",
            "undefined protected symbol: EtsProxyMethodInvoke",
            "ets_proxy_entry_point_riscv64.S",
        ],
        "old_ark_ets_riscv64_proxy_reflect_api_gap": [
            "ets_proxy_entrypoints.cpp",
            "fatal error: 'plugins/ets/runtime/types/ets_reflect_method.h' file not found",
        ],
        "old_riscv64_rust_build_script_wrong_arch": [
            "run_build_script.py",
            "cxx_lib_unknown_build_script",
            "/lib/ld-musl-riscv64.so.1: No such file or directory",
        ],
        "old_riscv64_mmi_rust_key_missing_symbol": [
            "multimodalinput/input/libmmi-util.z.so",
            "undefined symbol: ReadConfigInfo",
        ],
        "old_hidumper_memory_raw_param_missing_symbols": [
            "hiviewdfx/hidumper/libhidumpermemory.z.so",
            "undefined symbol: OHOS::HiviewDFX::RawParam::GetOutputFd()",
        ],
        "old_riscv64_mmi_rust_motion_missing_symbols": [
            "multimodalinput/input/libmmi-server.z.so",
            "undefined symbol: HandleMotionAccelerateTouchpad",
        ],
        "old_request_rust_cxxbridge_empty_outputs": [
            "base/request/request/common",
            "wrapper.rs.h",
            "member access into incomplete type",
        ],
        "old_rust_template_riscv64_sources_suppressed_unused_crate_type": [
            "build/templates/rust/rust_template.gni",
            "Assignment had no effect",
            "crate_type = _crate_type",
        ],
    }
    if not build_result:
        return {
            "id": "build_log_old_error_absence",
            "status": "skipped",
            "checked_count": 0,
            "sample_failures": [],
            "expectation": "previously fixed build-log blockers remain absent",
        }
    log_paths = [Path(clean_str(build_result.get("log_path"), ""))]
    probe = build_result.get("ninja_probe")
    if isinstance(probe, dict):
        log_paths.append(Path(clean_str(probe.get("log_path"), "")))
    text = "\n".join(read_text_sample(path, 1_000_000) for path in log_paths)
    plain = strip_ansi(text)
    failures = []
    for name, needles in patterns.items():
        if name == "libbt_vendor_compile_standard_mismatch":
            bad_lines = [
                line.strip()
                for line in plain.splitlines()
                if all(needle in line for needle in needles) and "warning" not in line.lower()
            ]
            if bad_lines:
                failures.append({"pattern": name, "needles": "; ".join(needles), "lines": bad_lines[:3]})
            continue
        if all(needle in plain for needle in needles):
            failures.append({"pattern": name, "needles": "; ".join(needles)})
    return {
        "id": "build_log_old_error_absence",
        "status": "pass" if not failures else "fail",
        "checked_count": len(patterns),
        "sample_failures": failures,
        "expectation": "previously fixed build-log blockers remain absent",
    }


def run_regression_checks(
    workspace: Path,
    product: str,
    target: dict[str, Any],
    results: list[dict[str, Any]],
    build_result: dict[str, Any] | None,
    enabled: bool,
) -> list[dict[str, Any]]:
    if not enabled:
        return [
            skipped_regression_check(
                "fake_shared_library_target_elf_header",
                "compile-only fake shared libraries match the target ELF machine/ABI",
                "regression checks are skipped for pure dry-run planning",
            ),
            skipped_regression_check(
                "riscv64_fake_rust_archive_arch",
                "fake rustc-riscv archives contain only RISC-V ELF objects",
                "regression checks are skipped for pure dry-run planning",
            ),
            skipped_regression_check(
                "riscv64_generated_objcopy_elf_flags",
                "run_objcopy.py generated RISC-V resource objects advertise RVC double-float ABI",
                "regression checks are skipped for pure dry-run planning",
            ),
            skipped_regression_check(
                "build_log_old_error_absence",
                "previously fixed build-log blockers remain absent",
                "regression checks are skipped for pure dry-run planning",
            ),
        ]
    return [
        check_fake_shared_library_elf_headers(workspace, target, results),
        check_rust_fake_archive_archives(workspace, product, target),
        check_riscv64_generated_objcopy_elf_flags(workspace, product, target),
        check_build_log_old_errors_absent(build_result),
    ]


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
        f"- Regression checks: {summary.get('regression_check_count', 0)}",
        f"- Regression check failures: {summary.get('regression_check_fail_count', 0)}",
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
        probe = build.get("ninja_probe")
        if isinstance(probe, dict):
            lines.extend(
                [
                    "### Direct Ninja Probe",
                    "",
                    f"- Command: `{probe.get('command', 'unknown')}`",
                    f"- Return code: `{probe.get('return_code', 'unknown')}`",
                    f"- Timed out: `{probe.get('timed_out', False)}`",
                    f"- Skipped: `{probe.get('skipped', False)}`",
                    f"- Log: `{probe.get('log_path', 'unknown')}`",
                    f"- Reason: `{probe.get('reason', 'not recorded')}`",
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
    regression_checks = manifest.get("regression_checks") or []
    if regression_checks:
        lines.extend(["## Regression Checks", ""])
        for check in regression_checks:
            lines.extend(
                [
                    f"- `{check.get('id', 'unknown')}`: `{check.get('status', 'unknown')}`",
                    f"  - Checked: {check.get('checked_count', 0)}",
                    f"  - Expectation: {check.get('expectation', 'not recorded')}",
                ]
            )
            failures = check.get("sample_failures") or []
            if failures:
                lines.append(f"  - Sample failures: `{failures[:3]}`")
        lines.append("")
    if manifest["blocking_issues"]:
        lines.extend(["## Blocking Issues", ""])
        for issue in manifest["blocking_issues"]:
            lines.append(f"- `{issue['path']}`: {issue['reason']}")
        lines.append("")
    fake_interfaces = manifest.get("fake_interfaces") or []
    debt_summary = manifest.get("dependency_debt_summary") or {}
    debt_categories = debt_summary.get("categories") or []
    if debt_categories:
        lines.extend(["## Dependency Debt Summary", ""])
        lines.append(f"- Total fake interfaces: {debt_summary.get('total_fake_interface_count', len(fake_interfaces))}")
        lines.append(f"- Categories: {debt_summary.get('category_count', len(debt_categories))}")
        review = debt_summary.get("fake_component_registry_review") or {}
        if review:
            lines.append(f"- Fake component registries: {review.get('count', 0)}")
            lines.append(f"- Fake component review rule: {review.get('rule', 'replace with real source evidence when available')}")
        lines.append("")
        for bucket in debt_categories:
            lines.extend(
                [
                    f"### {bucket.get('category', 'unknown')}",
                    "",
                    f"- Count: {bucket.get('count', 0)}",
                    f"- Risk: {bucket.get('risk', 'compile-only fake dependency')}",
                    f"- Follow-up: {bucket.get('follow_up', 'replace with real dependency evidence')}",
                    f"- Sample paths: `{'; '.join(bucket.get('sample_paths') or []) or 'none'}`",
                    "",
                ]
            )
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


def compile_standard_mismatch_lines(text: str, target_path: str) -> list[str]:
    return [
        line.strip()
        for line in strip_ansi(text).splitlines()
        if "subsystem name or part name is incorrect" in line and target_path in line
    ]


def compile_standard_mismatch_is_warning_only(text: str, target_path: str) -> bool:
    lines = compile_standard_mismatch_lines(text, target_path)
    return bool(lines) and all("warning" in line.lower() for line in lines)


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
    ninja_probe = build_result.get("ninja_probe")
    if isinstance(ninja_probe, dict):
        candidate_logs.append(Path(clean_str(ninja_probe.get("log_path"), "")))
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

    missing_stdlib_headers = sorted(
        {
            header
            for header in re.findall(r"fatal error: '([^']+)' file not found", plain_text)
            if header in CXX_STDLIB_HEADER_NAMES
        }
    )
    if missing_stdlib_headers and (
        "clang_x64/" in plain_text
        or "//build/toolchain/linux:clang_x64" in plain_text
        or "prebuilts/clang/ohos/linux-x86_64/llvm/bin/clang++" in plain_text
    ):
        evidence_paths = [
            str(path)
            for path, text in texts
            if any(f"'{header}' file not found" in strip_ansi(text) for header in missing_stdlib_headers)
        ]
        diagnostics.append(
            build_diagnostic(
                "host_sdk_cxx_stdlib_headers_missing",
                "host_or_prebuilt_toolchain",
                (
                    "The SDK/host clang_x64 stage cannot find C++ standard headers: "
                    + ", ".join(f"<{header}>" for header in missing_stdlib_headers[:8])
                    + (" ..." if len(missing_stdlib_headers) > 8 else "")
                    + "."
                ),
                (
                    "Scope the detected host GCC C++ include/library paths to build/toolchain/linux:clang_x64 "
                    "instead of exporting CPLUS_INCLUDE_PATH globally; keep this classified as host/prebuilt "
                    "toolchain repair rather than target-source porting."
                ),
                evidence_paths,
                matching_lines(all_text, ["fatal error:", "clang_x64", *missing_stdlib_headers[:6]], 12),
            )
        )

    if (
        "Assignment had no effect" in plain_text
        and "extra_cxxflags" in plain_text
        and 'clang_toolchain("clang_x64")' in plain_text
    ):
        diagnostics.append(
            build_diagnostic(
                "clang_x64_extra_cxxflags_not_forwarded",
                "host_or_prebuilt_toolchain_build_config",
                "GN rejected the host clang_x64 stdlib repair because clang_toolchain does not forward extra_cxxflags/extra_ldflags to gcc_toolchain.",
                "Patch build/toolchain/gcc_toolchain.gni so clang_toolchain forwards extra_cxxflags and extra_ldflags from invoker, then rerun GN/build.",
                [
                    str(path)
                    for path, text in texts
                    if "Assignment had no effect" in strip_ansi(text) and "extra_cxxflags" in strip_ansi(text)
                ]
                or [str(log_path)],
                matching_lines(
                    all_text,
                    ["Assignment had no effect", "extra_cxxflags", 'clang_toolchain("clang_x64")'],
                    12,
                ),
            )
        )

    if (
        clean_str(target.get("architecture")) == "riscv64"
        and "Assignment had no effect" in plain_text
        and "build/templates/rust/rust_template.gni" in plain_text
        and "crate_type = _crate_type" in plain_text
    ):
        diagnostics.append(
            build_diagnostic(
                "rust_template_riscv64_sources_suppressed_unused_crate_type",
                "rust_build_template_compatibility",
                (
                    "GN rejected rust_template.gni because an earlier riscv64 guard suppressed "
                    "Rust source/rustflag forwarding, leaving crate_type assigned but unused inside "
                    "ohos_rust_library expansion."
                ),
                (
                    "Restore the target-evidenced Rust template form: allow invoker.sources to be "
                    "forwarded normally and set rustflags = _rustflags without a target_cpu != "
                    "\"riscv64\" guard. Keep request/Rust components selected so real or fake "
                    "cxxbridge issues remain visible."
                ),
                [
                    str(path)
                    for path, text in texts
                    if "build/templates/rust/rust_template.gni" in strip_ansi(text)
                    and "crate_type = _crate_type" in strip_ansi(text)
                ]
                or [str(log_path)],
                matching_lines(
                    all_text,
                    [
                        "Assignment had no effect",
                        "build/templates/rust/rust_template.gni",
                        "crate_type = _crate_type",
                        "ohos_rust_library",
                    ],
                    16,
                ),
            )
        )

    if (
        clean_str(target.get("architecture")) == "riscv64"
        and "cross_values_generator.rb" in plain_text
        and "Failed: input file, output file and arch-name required" in plain_text
    ):
        diagnostics.append(
            build_diagnostic(
                "arkcompiler_cross_values_riscv64_arch_missing",
                "source_build_compatibility",
                "ArkCompiler cross_values_generate produced _values_gen.h without an arch-name because cross_values/BUILD.gn lacks the riscv64 -> RISCV64 mapping.",
                "Apply the target-evidenced minimal cross_values/BUILD.gn patch adding current_cpu == \"riscv64\" with arch = \"RISCV64\", without importing broader ArkCompiler 6.1 libarkbase renames.",
                [
                    str(path)
                    for path, text in texts
                    if "cross_values_generator.rb" in strip_ansi(text)
                    and "arch-name required" in strip_ansi(text)
                ]
                or [str(log_path), str(target_root / "arkcompiler/runtime_core/static_core/cross_values/BUILD.gn")],
                matching_lines(
                    all_text,
                    ["cross_values_generator.rb", "_values_gen.h", "arch-name required", "cross_values_generate"],
                    12,
                ),
            )
        )

    if (
        clean_str(target.get("architecture")) == "riscv64"
        and "compiled_code_to_runtime_bridge_riscv64.S" in plain_text
        and "MAKE_ASM_NAME" in plain_text
        and ("expected register" in plain_text or "unexpected token" in plain_text)
    ):
        diagnostics.append(
            build_diagnostic(
                "arkcompiler_riscv64_asm_make_asm_name_missing",
                "source_build_compatibility",
                "ArkCompiler RISC-V bridge assembly references MAKE_ASM_NAME, but asm_support.h has not imported the target-evidenced symbol-name macro support.",
                "Patch runtime/arch/asm_support.h with the target-evidenced MAKE_ASM_NAME macro block, together with the existing riscv64 THREAD_REG support.",
                [
                    str(path)
                    for path, text in texts
                    if "compiled_code_to_runtime_bridge_riscv64.S" in strip_ansi(text)
                    and "MAKE_ASM_NAME" in strip_ansi(text)
                ]
                or [
                    str(log_path),
                    str(target_root / "arkcompiler/runtime_core/static_core/runtime/arch/asm_support.h"),
                ],
                matching_lines(
                    all_text,
                    [
                        "compiled_code_to_runtime_bridge_riscv64.S",
                        "MAKE_ASM_NAME",
                        "expected register",
                        "unexpected token",
                    ],
                    16,
                ),
            )
        )

    if (
        clean_str(target.get("architecture")) == "riscv64"
        and "operand must be a symbol with %lo/%pcrel_lo/%tprel_lo modifier" in plain_text
        and "(tp)" in plain_text
        and "compiled_code_to_runtime_bridge_riscv64.S" in plain_text
    ):
        diagnostics.append(
            build_diagnostic(
                "arkcompiler_riscv64_thread_offset_large_immediate",
                "source_build_compatibility",
                "ArkCompiler RISC-V bridge assembly emitted direct tp-relative loads/stores whose generated ManagedThread offsets exceed the signed 12-bit immediate range.",
                "Apply the minimal RISC-V ManagedThread large-offset load/store helper to the affected ArkCompiler assembly sources, or reconcile the generated ManagedThread layout before treating this as external dependency debt.",
                [
                    str(path)
                    for path, text in texts
                    if "operand must be a symbol with %lo/%pcrel_lo/%tprel_lo modifier" in strip_ansi(text)
                    and "(tp)" in strip_ansi(text)
                ]
                or [str(log_path)],
                matching_lines(
                    all_text,
                    [
                        "operand must be a symbol with %lo/%pcrel_lo/%tprel_lo modifier",
                        "(tp)",
                        "compiled_code_to_runtime_bridge_riscv64.S",
                        "MANAGED_THREAD_",
                    ],
                    16,
                ),
            )
        )

    if (
        clean_str(target.get("architecture")) == "riscv64"
        and "asm_support.h" in plain_text
        and ".macro ARK_LOAD_THREAD_X" in plain_text
        and "cannot use dot operator on a type" in plain_text
    ):
        diagnostics.append(
            build_diagnostic(
                "arkcompiler_riscv64_thread_helper_in_cxx_header",
                "source_build_compatibility",
                "RISC-V assembly helper macros were placed in asm_support.h, which is also included by a C++ compilation unit.",
                "Move the RISC-V ManagedThread large-offset helper macros into the affected .S sources and remove them from asm_support.h.",
                [
                    str(path)
                    for path, text in texts
                    if "asm_support.h" in strip_ansi(text)
                    and ".macro ARK_LOAD_THREAD_X" in strip_ansi(text)
                ]
                or [str(log_path)],
                matching_lines(all_text, ["asm_support.h", ".macro ARK_LOAD_THREAD_X", "cannot use dot operator"], 12),
            )
        )

    if (
        clean_str(target.get("architecture")) == "riscv64"
        and "EtsToStringCacheElement" in plain_text
        and "std::atomic" in plain_text
        and "is_always_lock_free" in plain_text
    ):
        diagnostics.append(
            build_diagnostic(
                "arkcompiler_riscv64_ets_to_string_cache_atomic_guard",
                "source_build_compatibility",
                "EtsToStringCache asserts std::atomic<Data>::is_always_lock_free for RISC-V, where the target-evidenced guard narrows that assertion.",
                "Apply the target-evidenced EtsToStringCache guard requiring PANDA_32_BIT_MANAGED_POINTER with PANDA_TARGET_64 instead of disabling ETS runtime sources.",
                [
                    str(path)
                    for path, text in texts
                    if "EtsToStringCacheElement" in strip_ansi(text)
                    and "is_always_lock_free" in strip_ansi(text)
                ]
                or [
                    str(log_path),
                    str(
                        target_root
                        / "arkcompiler/runtime_core/static_core/plugins/ets/runtime/intrinsics/helpers/ets_to_string_cache.cpp"
                    ),
                ],
                matching_lines(all_text, ["EtsToStringCacheElement", "is_always_lock_free", "static assertion"], 12),
            )
        )

    if (
        clean_str(target.get("architecture")) == "riscv64"
        and "string_index_of.h" in plain_text
        and "Unknown target architecture" in plain_text
        and "IndexOf implementation assumes" in plain_text
    ):
        diagnostics.append(
            build_diagnostic(
                "arkcompiler_riscv64_string_index_guard",
                "source_build_compatibility",
                "StringIndexOf rejects PANDA_TARGET_RISCV64 even though the target source treats RISC-V as little-endian for this SWAR implementation.",
                "Apply the target-evidenced minimal string_index_of.h guard adding !defined(PANDA_TARGET_RISCV64), without importing broader ArkCompiler 6.1 runtime renames.",
                [
                    str(path)
                    for path, text in texts
                    if "string_index_of.h" in strip_ansi(text)
                    and "Unknown target architecture" in strip_ansi(text)
                ]
                or [
                    str(log_path),
                    str(target_root / "arkcompiler/runtime_core/static_core/runtime/entrypoints/string_index_of.h"),
                ],
                matching_lines(all_text, ["string_index_of.h", "Unknown target architecture", "IndexOf implementation"], 12),
            )
        )

    if (
        clean_str(target.get("architecture")) == "riscv64"
        and "foundation/arkui/napi/native_engine/impl/ark/cj_support.cpp" in plain_text
        and "current platform not supported" in plain_text
        and "LIBS_NAME" in plain_text
    ):
        diagnostics.append(
            build_diagnostic(
                "arkui_napi_cj_support_riscv64_platform_missing",
                "source_build_compatibility",
                "ArkUI NAPI CJ support is compiled for riscv64 without NAPI_TARGET_RISCV64/LIBS_NAME platform support.",
                (
                    "Apply the target-evidenced foundation/arkui/napi/BUILD.gn RISC-V target defines "
                    "and import the target cj_support.cpp ELF typedef/LIBS_NAME support; keep CJ/ArkUI "
                    "features selected."
                ),
                [
                    str(log_path),
                    str(target_root / "foundation/arkui/napi/BUILD.gn"),
                    str(target_root / ARKUI_NAPI_RISCV64_CJ_SUPPORT_REL),
                ],
                matching_lines(
                    all_text,
                    [
                        "foundation/arkui/napi/native_engine/impl/ark/cj_support.cpp",
                        "current platform not supported",
                        "LIBS_NAME",
                        "NAPI_TARGET_RISCV64",
                    ],
                    16,
                ),
            )
        )

    if (
        clean_str(target.get("architecture")) == "riscv64"
        and "foundation/graphic/graphic_2d/rosen/modules/composer/vsync" in plain_text
        and "format specifies type" in plain_text
        and ("uint64_t" in plain_text or "int64_t" in plain_text)
        and ("VPUBU64" in plain_text or "VPUBI64" in plain_text)
    ):
        diagnostics.append(
            build_diagnostic(
                "graphic_2d_vsync_riscv64_log_format_macros",
                "source_build_compatibility",
                "graphic_2d VSync logging macros still treat riscv64 as LLP64-style, so LP64 uint64_t/int64_t arguments fail -Werror=format.",
                (
                    "Apply the target-evidenced vsync_log.h condition that groups "
                    "(__riscv && __riscv_xlen == 64) with aarch64/x86_64 for VPUBI64/VPUBU64."
                ),
                [
                    str(log_path),
                    str(target_root / GRAPHIC_2D_VSYNC_LOG_REL),
                ],
                matching_lines(
                    all_text,
                    [
                        "foundation/graphic/graphic_2d/rosen/modules/composer/vsync",
                        "format specifies type",
                        "uint64_t",
                        "int64_t",
                        "VPUB",
                    ],
                    18,
                ),
            )
        )

    if (
        clean_str(target.get("architecture")) == "riscv64"
        and "foundation/graphic/graphic_3d/lume" in plain_text
        and "static_plugin_decl.h" in plain_text
        and "DEFINE_STATIC_PLUGIN" in plain_text
        and "expected ')'" in plain_text
        and ("SECTION(spl.1)" in plain_text or ".pushsection" in plain_text)
    ):
        diagnostics.append(
            build_diagnostic(
                "graphic_3d_lume_riscv64_static_plugin_section",
                "source_build_compatibility",
                "graphic_3d Lume static-plugin section macros lack a RISC-V branch, so SECTION(...) is not defined for riscv64 inline assembly.",
                (
                    "Apply the target-evidenced static_plugin_decl.h __riscv SECTION branch "
                    "using the same writable section and .align 3 rule as the reference target."
                ),
                [
                    str(log_path),
                    str(target_root / LUME_STATIC_PLUGIN_DECL_REL),
                ],
                matching_lines(
                    all_text,
                    [
                        "foundation/graphic/graphic_3d/lume",
                        "static_plugin_decl.h",
                        "DEFINE_STATIC_PLUGIN",
                        "SECTION(spl.1)",
                        ".pushsection",
                        "expected ')'",
                    ],
                    18,
                ),
            )
        )

    if (
        "compile_app.py" in plain_text
        and "prebuilts/tool/command-line-tools/ohpm/bin/ohpm" in plain_text
        and (
            "FileNotFoundError" in plain_text
            or "No such file or directory" in plain_text
        )
    ):
        diagnostics.append(
            build_diagnostic(
                "compile_app_ohpm_path_resolved_from_app_cwd",
                "host_or_prebuilt_toolchain_path",
                "Application packaging invokes ohpm through an app-relative prebuilts path, so the real workspace ohpm prebuilt is not found after compile_app.py changes cwd.",
                "Patch build/scripts/compile_app.py to normalize os.path.abspath(get_root_dir()) before resolving prebuilts/tool/command-line-tools/ohpm/bin/ohpm, and keep this as a real prebuilt tool dependency rather than a fake interface.",
                [
                    str(path)
                    for path, text in texts
                    if "prebuilts/tool/command-line-tools/ohpm/bin/ohpm" in strip_ansi(text)
                ]
                or [str(log_path)],
                matching_lines(
                    all_text,
                    [
                        "compile_app.py",
                        "prebuilts/tool/command-line-tools/ohpm/bin/ohpm",
                        "FileNotFoundError",
                        "No such file or directory",
                    ],
                    14,
                ),
            )
        )

    if (
        "base/request/request/common" in plain_text
        and "wrapper.rs.h" in plain_text
        and "member access into incomplete type" in plain_text
        and (
            "ClosureWrapper" in plain_text
            or "OpenCallbackWrapper" in plain_text
            or "CallbackWrapper" in plain_text
            or "RustPerformanceInfo" in plain_text
        )
    ):
        diagnostics.append(
            build_diagnostic(
                "request_rust_cxxbridge_empty_outputs",
                "rust_toolchain_fake_interface",
                (
                    "Request Rust/C++ bridge headers are empty or incomplete, so C++ wrapper code "
                    "only sees opaque Rust callback types and fails on member calls."
                ),
                (
                    "Treat this as missing functional host cxxbridge/Rust toolchain debt. During "
                    "compile triage, patch build/templates/rust/rust_cxxbridge.py so empty "
                    "cxxbridge stdout for cxx::bridge sources emits a minimal compile-only fake "
                    "header/cc; replace the fake Rust toolchain with real prebuilts before runtime "
                    "or API validation."
                ),
                [
                    str(path)
                    for path, text in texts
                    if "base/request/request/common" in strip_ansi(text)
                    and "member access into incomplete type" in strip_ansi(text)
                ]
                or [str(log_path)],
                matching_lines(
                    all_text,
                    [
                        "base/request/request/common",
                        "wrapper.rs.h",
                        "member access into incomplete type",
                        "ClosureWrapper",
                        "OpenCallbackWrapper",
                        "CallbackWrapper",
                        "RustPerformanceInfo",
                    ],
                    18,
                ),
            )
        )

    duplicate_warning_count = plain_text.count("ninja: warning: multiple rules generate")
    if (
        duplicate_warning_count >= 20
        and "BUILD Failed!" in plain_text
        and "FAILED:" not in plain_text
    ):
        diagnostics.append(
            build_diagnostic(
                "hb_build_failed_after_duplicate_output_warnings",
                "build_log_infrastructure",
                f"hb reported BUILD Failed after {duplicate_warning_count} duplicate-output warnings without preserving a concrete FAILED command in the sampled log.",
                "Do not treat duplicate-output warnings alone as the primary porting blocker; inspect the direct Ninja probe log for the first real failing action, then fix that blocker while tracking duplicate-output graph debt separately.",
                [
                    str(path)
                    for path, text in texts
                    if "ninja: warning: multiple rules generate" in strip_ansi(text)
                ]
                or [str(log_path)],
                matching_lines(
                    all_text,
                    ["ninja: warning: multiple rules generate", "BUILD Failed!", "direct_ninja"],
                    14,
                ),
                severity="warning",
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

    if (
        clean_str(target.get("architecture")) == "riscv64"
        and "arkcompiler/runtime_core/static_core" in plain_text
        and (
            "runtime/fibers/fiber_context.h" in plain_text
            or "runtime/signal_handler.h" in plain_text
            or "runtime/include/object_accessor.h" in plain_text
            or "libpandabase/utils/arch.h" in plain_text
        )
        and (
            '"Unsupported target"' in plain_text
            or "CONTEXT_PC" in plain_text
            or "class member cannot be redeclared" in plain_text
            or "GetCalleeRegsMask" in plain_text
        )
    ):
        diagnostics.append(
            build_diagnostic(
                "arkcompiler_runtime_core_riscv64_support_missing",
                "source_build_compatibility",
                "ArkCompiler static_core reaches RISC-V runtime compilation but runtime arch traits, signal context, object accessor overloads, or fiber context support are incomplete.",
                "Apply the target-evidenced minimal RISC-V runtime support set: arch traits, runtime arch helpers, signal/fiber context mappings, object_accessor overlap guard, and RISC-V runtime assembly sources.",
                [
                    str(log_path),
                    str(target_root / "arkcompiler/runtime_core/static_core/libarkbase/utils/arch.h"),
                    str(target_root / "arkcompiler/runtime_core/static_core/runtime/fibers/arch/riscv64/context_layout.h"),
                    str(target_root / "arkcompiler/runtime_core/static_core/runtime/signal_handler.h"),
                ],
                matching_lines(
                    all_text,
                    [
                        "object_accessor.h",
                        "class member cannot be redeclared",
                        "cframe_layout.h",
                        "GetCalleeRegsMask",
                        "signal_handler.h",
                        "CONTEXT_PC",
                        "fiber_context.h",
                        "Unsupported target",
                    ],
                    18,
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

    webview_missing_generated_sources = sorted(
        set(
            re.findall(
                r"(?:clang\+\+|clang): error: no such file or directory: '([^']*gen/base/web/webview/ohos_glue/ohos_nweb/[^']+\.(?:cpp|h))'",
                plain_text,
            )
        )
    )
    for raw_source_path in webview_missing_generated_sources[:8]:
        missing_rel = normalize_ninja_source_path(raw_source_path, workspace)
        evidence_lines = matching_lines(all_text, ["no such file or directory", raw_source_path], 8)
        evidence_lines.append(f"normalized_missing_generated_source={missing_rel}")
        diagnostics.append(
            build_diagnostic(
                "webview_glue_generated_source_missing",
                "source_text_closure_missing",
                (
                    "WebView ohos_glue BUILD rules expect generated glue source "
                    f"{missing_rel}, but the prepare inputs did not produce it."
                ),
                (
                    "Import the target-evidenced base/web/webview/ohos_interface BUILD/input "
                    "text closure so prepare.sh/copy_files.py/translator.py regenerate the "
                    "missing out/gen source; do not hand-write a fake generated .cpp/.h file."
                ),
                [
                    str(log_path),
                    str(target_root / "base/web/webview/ohos_interface/BUILD.gn"),
                    str(target_root / "base/web/webview/ohos_interface/ohos_glue/ohos_nweb"),
                ],
                evidence_lines,
            )
        )

    webview_translate_type_failures = sorted(
        set(re.findall(r"Exception: Failed to translate type: ([A-Za-z0-9_]+)", plain_text))
    )
    if webview_translate_type_failures and (
        "base/web/webview/ohos_glue:ohos_glue_nweb_prepare" in plain_text
        or "base/web/webview/prepare.sh translate" in plain_text
    ):
        diagnostics.append(
            build_diagnostic(
                "webview_glue_translator_type_missing",
                "source_text_closure_missing",
                (
                    "WebView glue translator does not recognize target type(s): "
                    + ", ".join(webview_translate_type_failures[:8])
                    + (" ..." if len(webview_translate_type_failures) > 8 else "")
                    + "."
                ),
                (
                    "Import the target-evidenced ohos_interface/ohos_glue base and scripts "
                    "text closure together with the nweb glue input closure; keep the generated "
                    "out/gen files produced by translator.py instead of faking them."
                ),
                [
                    str(log_path),
                    str(target_root / "base/web/webview/ohos_interface/ohos_glue/scripts"),
                    str(target_root / "base/web/webview/ohos_interface/ohos_glue/base"),
                ],
                matching_lines(all_text, ["Failed to translate type", "ohos_glue_nweb_prepare", "prepare.sh translate"], 12),
            )
        )

    fake_python_script_paths = sorted(
        set(re.findall(r'File "([^"]+\.py)", line \d+.*\n\s*reference=', plain_text))
    )
    if fake_python_script_paths and "SyntaxError: invalid syntax" in plain_text:
        diagnostics.append(
            build_diagnostic(
                "python_script_misclassified_as_fake_payload",
                "source_text_closure_missing",
                (
                    "A Python build/generator script was executed as a compile-only fake marker: "
                    + ", ".join(fake_python_script_paths[:4])
                    + (" ..." if len(fake_python_script_paths) > 4 else "")
                    + "."
                ),
                (
                    "Treat .py files as text/source closure inputs and copy the target-evidenced "
                    "script content; fake payloads are only for real binary/prebuilt/non-text dependencies."
                ),
                [str(log_path)],
                matching_lines(all_text, ["SyntaxError: invalid syntax", "reference=", ".py"], 12),
            )
        )

    if (
        clean_str(target.get("architecture")) == "riscv64"
        and "developtools/profiler/device/plugins/native_daemon/include/register.h" in plain_text
        and "NOT SUPPORT ARCH" in plain_text
        and ("buildArchType" in plain_text or "target_cpu_riscv64" in plain_text)
    ):
        diagnostics.append(
            build_diagnostic(
                "profiler_native_daemon_riscv64_arch_missing",
                "source_build_compatibility",
                (
                    "Profiler native_daemon/native_hook is compiling for riscv64, but "
                    "register.h lacks the target-evidenced RISC-V buildArchType/register branches."
                ),
                (
                    "Import the target-evidenced native_daemon register.h/register.cpp/call_stack.cpp "
                    "RISC-V support set; keep profiler product features selected rather than hiding "
                    "native_hook from the build graph."
                ),
                [
                    str(log_path),
                    str(target_root / "developtools/profiler/device/plugins/native_daemon/include/register.h"),
                    str(target_root / "developtools/profiler/device/plugins/native_daemon/src/register.cpp"),
                    str(target_root / "developtools/profiler/device/plugins/native_daemon/src/call_stack.cpp"),
                ],
                matching_lines(
                    all_text,
                    [
                        "developtools/profiler/device/plugins/native_daemon/include/register.h",
                        "NOT SUPPORT ARCH",
                        "buildArchType",
                        "hook_client.cpp",
                    ],
                    16,
                ),
            )
        )

    if (
        clean_str(target.get("architecture")) == "riscv64"
        and "developtools/hiperf/include/register.h" in plain_text
        and "NOT SUPPORT ARCH" in plain_text
        and ("BUILD_ARCH_TYPE" in plain_text or "target_cpu_riscv64" in plain_text)
    ):
        diagnostics.append(
            build_diagnostic(
                "hiperf_riscv64_arch_missing",
                "source_build_compatibility",
                (
                    "Hiperf is compiling for riscv64, but its register.h lacks the "
                    "target-evidenced RISC-V BUILD_ARCH_TYPE and perf register branches."
                ),
                (
                    "Import the target-evidenced hiperf register.h/register.cpp/callstack.cpp/"
                    "hiperf_libreport.cpp text closure; keep hiperf selected and track only "
                    "non-text payloads as dependency debt."
                ),
                [
                    str(log_path),
                    str(target_root / "developtools/hiperf/include/register.h"),
                    str(target_root / "developtools/hiperf/src/register.cpp"),
                    str(target_root / "developtools/hiperf/src/callstack.cpp"),
                    str(target_root / "developtools/hiperf/src/hiperf_libreport.cpp"),
                ],
                matching_lines(
                    all_text,
                    [
                        "developtools/hiperf/include/register.h",
                        "NOT SUPPORT ARCH",
                        "BUILD_ARCH_TYPE",
                        "perf_events.cpp",
                    ],
                    16,
                ),
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
        and not compile_standard_mismatch_is_warning_only(plain_text, target_path)
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
        if compile_standard_mismatch_is_warning_only(plain_text, target_path):
            continue
        target_whitelist_has_label = target_compile_standard_whitelist_contains_label(target_root, target_path)
        diagnostic_id = (
            "target_compile_standard_whitelist_missing"
            if target_whitelist_has_label
            else "compile_standard_part_subsystem_mismatch"
        )
        suggested_next_action = (
            "Merge the exact target-source compile_standard_whitelist.json entry for this label, then rerun without dropping the product feature."
            if target_whitelist_has_label
            else "Compare the target path against target-source compile_standard_whitelist evidence or correct the component ownership metadata without dropping product features."
        )
        evidence_lines = matching_lines(all_text, ["subsystem name or part name is incorrect", target_path], 10)
        if target_whitelist_has_label:
            evidence_lines.append(f"target-source compile_standard_whitelist.json contains exact label {target_path}")
        diagnostics.append(
            build_diagnostic(
                diagnostic_id,
                "source_build_compatibility",
                f"Compile-standard check rejects {target_path} for subsystem {subsystem_name} and part {part_name}.",
                suggested_next_action,
                [str(log_path), str(target_root / "build/compile_standard_whitelist.json")],
                evidence_lines,
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

    fake_shared_library_script_errors = sorted(
        set(
            normalize_ninja_source_path(path, workspace)
            for path in re.findall(
                r"ld\.lld:\s+error:\s+([^:\s]+\.so):1:\s+unknown directive:\s+FAKE_OPENHARMONY_PORTING_INTERFACE=1",
                plain_text,
            )
        )
    )
    for fake_so in fake_shared_library_script_errors[:8]:
        diagnostics.append(
            build_diagnostic(
                "fake_shared_library_placeholder_not_elf",
                "external_prebuilt_dependency",
                f"The compile-only placeholder for {fake_so} is text, so lld interprets it as an invalid linker script.",
                "Generate a target-architecture ELF shared-library stub from the reference dependency's dynamic symbol table instead of writing a text marker, then report the real vendor binary as dependency debt.",
                [str(log_path), str(target_root / fake_so)],
                matching_lines(
                    all_text,
                    [
                        fake_so,
                        "unknown directive: FAKE_OPENHARMONY_PORTING_INTERFACE=1",
                        "ld.lld",
                    ],
                    12,
                ),
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
        and "foundation/resourceschedule/ffrt/src/eu/co_routine.cpp" in plain_text
        and "STACK_MAGIC" in plain_text
        and "use of undeclared identifier" in plain_text
    ):
        diagnostics.append(
            build_diagnostic(
                "ffrt_co_routine_riscv64_stack_magic_missing",
                "source_build_compatibility",
                "FFRT coroutine code uses STACK_MAGIC, but co_routine.h lacks the RISC-V STACK_MAGIC branch.",
                "Apply the target-evidenced foundation/resourceschedule/ffrt/include/eu/co_routine.h patch that defines STACK_MAGIC for __riscv && __riscv_xlen == 64, then rerun the build.",
                [
                    str(log_path),
                    str(target_root / "foundation/resourceschedule/ffrt/include/eu/co_routine.h"),
                ],
                matching_lines(
                    all_text,
                    ["co_routine.cpp", "STACK_MAGIC", "use of undeclared identifier"],
                    12,
                ),
            )
        )

    if (
        clean_str(target.get("architecture")) == "riscv64"
        and "foundation/resourceschedule/ffrt/src/sched/task_client_adapter.h" in plain_text
        and "Unsupported architecture" in plain_text
        and "CTC_QUERY_INTERVAL" in plain_text
    ):
        diagnostics.append(
            build_diagnostic(
                "ffrt_task_client_adapter_riscv64_ctc_query_interval_missing",
                "source_build_compatibility",
                "FFRT sched task_client_adapter.h lacks the RISC-V CTC_QUERY_INTERVAL architecture guard, so multi_workgroup.cpp hits the unsupported architecture path.",
                "Apply the target-evidenced task_client_adapter.h patch that treats __riscv && __riscv_xlen == 64 like the ARM runtime CTC query path, then rerun the build.",
                [
                    str(log_path),
                    str(target_root / "foundation/resourceschedule/ffrt/src/sched/task_client_adapter.h"),
                ],
                matching_lines(
                    all_text,
                    ["task_client_adapter.h", "Unsupported architecture", "CTC_QUERY_INTERVAL"],
                    12,
                ),
            )
        )

    if (
        clean_str(target.get("architecture")) == "riscv64"
        and "foundation/ability/ability_runtime/cj_environment/frameworks/cj_environment/src/cj_environment.cpp" in plain_text
        and "unsupported platform" in plain_text
        and "APP_LIB_NAME" in plain_text
    ):
        diagnostics.append(
            build_diagnostic(
                "cj_environment_riscv64_platform_mapping_missing",
                "source_build_compatibility",
                "cj_environment lacks an APP_USE_RISCV64 define and APP_LIB_NAME riscv64 branch, so RISC-V compilation hits the unsupported platform guard.",
                "Apply the target-evidenced cj_environment BUILD.gn/source patch adding APP_USE_RISCV64 and APP_LIB_NAME \"riscv64\", then rerun the build.",
                [
                    str(log_path),
                    str(target_root / "foundation/ability/ability_runtime/cj_environment/frameworks/cj_environment/BUILD.gn"),
                    str(target_root / "foundation/ability/ability_runtime/cj_environment/frameworks/cj_environment/src/cj_environment.cpp"),
                ],
                matching_lines(
                    all_text,
                    ["cj_environment.cpp", "unsupported platform", "APP_LIB_NAME"],
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
        and ("-flto=thin" in plain_text or "thinlto-cache" in plain_text or "lto.tmp" in plain_text)
    ):
        diagnostics.append(
            build_diagnostic(
                "riscv64_global_thinlto_float_abi_mismatch",
                "source_build_compatibility",
                "RISC-V target links fail while ThinLTO is enabled because lld-generated lto.tmp or thinlto-cache objects do not retain the same rv64imafdc/lp64d ABI as the final link.",
                "Disable the default riscv64 ThinLTO path in build/config/compiler/compiler.gni for this OpenHarmony 6.0 toolchain, keep product features selected, and rerun the compile flow.",
                [
                    str(log_path),
                    str(workspace / "build/config/compiler/compiler.gni"),
                    str(workspace / "build/config/compiler/BUILD.gn"),
                ],
                matching_lines(
                    all_text,
                    ["cannot link object files with different floating-point ABI", "-flto=thin", "thinlto-cache", "lto.tmp"],
                    14,
                ),
            )
        )

    if (
        clean_str(target.get("architecture")) == "riscv64"
        and "arkcompiler/ets_runtime/libark_jsruntime.so" in plain_text
        and "cannot link object files with different floating-point ABI" in plain_text
        and "-flto=thin" in plain_text
        and "lto.tmp" in plain_text
    ):
        diagnostics.append(
            build_diagnostic(
                "ark_jsruntime_riscv64_explicit_thin_lto_compat",
                "source_build_compatibility",
                "Ark JS runtime still injects -flto=thin directly, bypassing the global riscv64 ThinLTO off-ramp and producing mixed floating-point ABI lto.tmp objects.",
                (
                    "Guard the arkcompiler/ets_runtime BUILD.gn explicit ThinLTO block with "
                    "current_cpu != \"riscv64\" for compile triage on this OpenHarmony 6.0 toolchain."
                ),
                [
                    str(log_path),
                    str(target_root / ARK_ETS_RUNTIME_BUILD_REL),
                ],
                matching_lines(
                    all_text,
                    [
                        "arkcompiler/ets_runtime/libark_jsruntime.so",
                        "-flto=thin",
                        "cannot link object files with different floating-point ABI",
                        "lto.tmp",
                    ],
                    18,
                ),
            )
        )

    if (
        clean_str(target.get("architecture")) == "riscv64"
        and "arkcompiler/ets_runtime/libark_jsruntime.so" in plain_text
        and "undefined symbol: LazyDeoptEntry" in plain_text
    ):
        diagnostics.append(
            build_diagnostic(
                "ark_jsruntime_riscv64_lazy_deopt_trampoline_source",
                "source_build_compatibility",
                "Ark JS runtime links runtime_stubs.o against LazyDeoptEntry, but the RISC-V raw_asm_stub.S trampoline source is absent from the 6.0 source list.",
                (
                    "Import the target-evidenced ecmascript/trampoline/riscv64/raw_asm_stub.S "
                    "and add the riscv64 ecma_source branch in arkcompiler/ets_runtime/BUILD.gn."
                ),
                [
                    str(log_path),
                    str(target_root / ARK_ETS_RUNTIME_BUILD_REL),
                    str(target_root / ARK_ETS_RUNTIME_RISCV64_TRAMPOLINE_REL),
                ],
                matching_lines(
                    all_text,
                    [
                        "arkcompiler/ets_runtime/libark_jsruntime.so",
                        "undefined symbol: LazyDeoptEntry",
                        "runtime_stubs.o",
                    ],
                    18,
                ),
            )
        )

    if (
        clean_str(target.get("architecture")) == "riscv64"
        and "third_party/skia/m133/src/opts/SkRasterPipeline_opts.h" in plain_text
        and "subscripted value is not an array, pointer, or vector" in plain_text
        and "SkOpts.o" in plain_text
    ):
        diagnostics.append(
            build_diagnostic(
                "skia_raster_pipeline_riscv64_scalar_sqrt_fallback",
                "source_build_compatibility",
                "SkRasterPipeline asin_() indexes fallback scalar values as if they were vectors on riscv64, causing SkOpts.o to fail compilation.",
                (
                    "Apply the target-evidenced SkRasterPipeline_opts.h split: keep indexed sqrt "
                    "for x86_64 and use scalar std::sqrt(1.0f - x) for non-x86 targets."
                ),
                [
                    str(log_path),
                    str(target_root / SKIA_RASTER_PIPELINE_OPTS_REL),
                ],
                matching_lines(
                    all_text,
                    [
                        "SkRasterPipeline_opts.h",
                        "subscripted value is not an array",
                        "SkOpts.o",
                    ],
                    18,
                ),
            )
        )

    if (
        clean_str(target.get("architecture")) == "riscv64"
        and "cannot link object files with different floating-point ABI" in plain_text
        and "query_syscap.o" in plain_text
        and "libsystemcapability" in plain_text
    ):
        diagnostics.append(
            build_diagnostic(
                "riscv64_generated_objcopy_elf_flags_missing",
                "source_build_compatibility",
                "gen_js_obj produced query_syscap.o as RISC-V ELF with flags 0x0, which cannot link with lp64d RISC-V objects in libsystemcapability.",
                (
                    "Keep syscap JSAPI selected; patch build/scripts/run_objcopy.py so riscv64 "
                    "binary-to-object resources are emitted with ELF flags 5 "
                    "(RVC | double-float ABI), then rerun the build."
                ),
                [
                    str(log_path),
                    str(workspace / "out" / product / "obj/developtools/syscap_codec/napi/query_syscap.o"),
                    str(workspace / RUN_OBJCOPY_REL),
                ],
                matching_lines(
                    all_text,
                    [
                        "libsystemcapability",
                        "query_syscap.o",
                        "cannot link object files with different floating-point ABI",
                    ],
                    16,
                ),
            )
        )

    if (
        clean_str(target.get("architecture")) == "riscv64"
        and "duplicate symbol: OsrEntryAfterCFrame" in plain_text
        and "osr_riscv64.o" in plain_text
        and "asm_support.o" in plain_text
    ):
        diagnostics.append(
            build_diagnostic(
                "ark_runtime_riscv64_osr_fallback_duplicate_symbols",
                "source_build_compatibility",
                "Ark runtime links both the riscv64 osr_riscv64.S OSR entries and asm_support.cpp fallback OSR symbols into libarkruntime.",
                (
                    "Apply the target-evidenced asm_support.cpp guard that excludes the C++ "
                    "UNREACHABLE OSR fallback when PANDA_TARGET_RISCV64 is defined."
                ),
                [
                    str(log_path),
                    str(target_root / ARK_RUNTIME_ASM_SUPPORT_CPP_REL),
                    str(target_root / "arkcompiler/runtime_core/static_core/runtime/arch/riscv64/osr_riscv64.S"),
                ],
                matching_lines(
                    all_text,
                    [
                        "duplicate symbol: OsrEntryAfterCFrame",
                        "asm_support.o",
                        "osr_riscv64.o",
                    ],
                    18,
                ),
            )
        )

    if (
        clean_str(target.get("architecture")) == "riscv64"
        and "arkcompiler/runtime_core/libarkruntime.so" in plain_text
        and (
            "undefined symbol: EtsAsyncEntryPoint" in plain_text
            or "undefined symbol: EtsNapiEntryPoint" in plain_text
            or "undefined symbol: JSRuntimeCallJSBridge" in plain_text
            or "undefined symbol: CallJSProxyBridge" in plain_text
        )
    ):
        diagnostics.append(
            build_diagnostic(
                "ark_ets_riscv64_bridge_sources_missing",
                "source_build_compatibility",
                "libarkruntime references ETS NAPI and JS interop bridge entrypoints, but the RISC-V bridge assembly sources are not selected in plugins/ets/subproject_sources.gn.",
                (
                    "Import the target-evidenced RISC-V ETS bridge assembly closure and add "
                    "the riscv64 subproject_sources.gn branches for call_bridge_riscv64.S, "
                    "ets_napi_entry_point_riscv64.S, ets_async_entry_point_riscv64.S, and "
                    "ets_proxy_entry_point_riscv64.S."
                ),
                [str(log_path), str(target_root / ARK_ETS_SUBPROJECT_SOURCES_REL)]
                + [str(target_root / rel_path) for rel_path in ARK_ETS_RISCV64_BRIDGE_SOURCE_RELS],
                matching_lines(
                    all_text,
                    [
                        "arkcompiler/runtime_core/libarkruntime.so",
                        "undefined symbol:",
                        "EtsAsyncEntryPoint",
                        "JSRuntimeCallJSBridge",
                        "CallJSProxyBridge",
                    ],
                    24,
                ),
            )
        )

    if (
        clean_str(target.get("architecture")) == "riscv64"
        and "ets_proxy_entry_point_riscv64.S" in plain_text
        and "proxy_entrypoint_riscv64.S" in plain_text
        and "operand must be a symbol" in plain_text
        and "2392(tp)" in plain_text
    ):
        diagnostics.append(
            build_diagnostic(
                "ark_ets_riscv64_proxy_entrypoint_large_thread_offsets",
                "source_build_compatibility",
                "ETS RISC-V proxy entrypoint includes target proxy_entrypoint_riscv64.S, whose direct THREAD_REG large-offset loads/stores exceed the RISC-V 12-bit immediate range.",
                (
                    "During target-source import, rewrite proxy_entrypoint_riscv64.S to use the "
                    "local ARK_LOAD_THREAD_* / ARK_STORE_THREAD_X helper macros for "
                    "MANAGED_THREAD_FRAME_OFFSET and MANAGED_THREAD_EXCEPTION_OFFSET."
                ),
                [
                    str(log_path),
                    str(target_root / "arkcompiler/runtime_core/static_core/runtime/bridge/arch/riscv64/proxy_entrypoint_riscv64.S"),
                ],
                matching_lines(
                    all_text,
                    [
                        "ets_proxy_entry_point_riscv64.S",
                        "proxy_entrypoint_riscv64.S",
                        "operand must be a symbol",
                        "2392(tp)",
                        "2400(tp)",
                    ],
                    18,
                ),
            )
        )

    if (
        clean_str(target.get("architecture")) == "riscv64"
        and "arkcompiler/runtime_core/libarkruntime.so" in plain_text
        and "undefined protected symbol: EtsProxyMethodInvoke" in plain_text
        and "ets_proxy_entry_point_riscv64.S" in plain_text
    ):
        diagnostics.append(
            build_diagnostic(
                "ark_ets_riscv64_proxy_method_invoke_source_missing",
                "source_build_compatibility",
                "The RISC-V ETS proxy assembly is now linked, but libarkruntime still lacks the C++ EtsProxyMethodInvoke implementation selected by the reference target.",
                (
                    "Import the target-evidenced plugins/ets/runtime/entrypoints/ets_proxy_entrypoints.cpp "
                    "source and add it to plugins/ets/subproject_sources.gn srcs_runtime."
                ),
                [
                    str(log_path),
                    str(target_root / "arkcompiler/runtime_core/static_core/plugins/ets/runtime/entrypoints/ets_proxy_entrypoints.cpp"),
                    str(target_root / ARK_ETS_SUBPROJECT_SOURCES_REL),
                ],
                matching_lines(
                    all_text,
                    [
                        "arkcompiler/runtime_core/libarkruntime.so",
                        "undefined protected symbol: EtsProxyMethodInvoke",
                        "ets_proxy_entry_point_riscv64.S",
                    ],
                    18,
                ),
            )
        )

    if (
        clean_str(target.get("architecture")) == "riscv64"
        and "ets_proxy_entrypoints.cpp" in plain_text
        and "plugins/ets/runtime/types/ets_reflect_method.h" in plain_text
        and "file not found" in plain_text
    ):
        diagnostics.append(
            build_diagnostic(
                "ark_ets_riscv64_proxy_method_reflect_api_gap",
                "source_build_compatibility",
                "The target-evidenced ETS proxy method implementation depends on the newer ETS reflection runtime API that is absent from this OpenHarmony 6.0 base tree.",
                (
                    "During compile triage, replace ets_proxy_entrypoints.cpp with a tracked "
                    "compile-only EtsProxyMethodInvoke stub and record the real ETS reflection "
                    "proxy implementation as dependency debt."
                ),
                [
                    str(log_path),
                    str(target_root / ARK_ETS_PROXY_ENTRYPOINTS_CPP_REL),
                    str(target_root / "arkcompiler/runtime_core/static_core/plugins/ets/runtime/types/ets_reflect_method.h"),
                ],
                matching_lines(
                    all_text,
                    [
                        "ets_proxy_entrypoints.cpp",
                        "ets_reflect_method.h",
                        "file not found",
                    ],
                    18,
                ),
            )
        )

    if (
        clean_str(target.get("architecture")) == "riscv64"
        and "rustc_wrapper.py" in plain_text
        and (
            "unrecognized argument in option '-mabi=lp64d'" in plain_text
            or "unrecognized command line option '--target=riscv64-linux-ohos'" in plain_text
            or 'rust_abi_target = "riscv64-unknown-linux-gnu"' in plain_text
        )
    ):
        diagnostics.append(
            build_diagnostic(
                "riscv64_rust_host_linker_misconfigured",
                "external_prebuilt_dependency",
                "Rust targets are being compiled or linked through the host x86 Rust toolchain/linker while RISC-V OHOS linker flags are present.",
                "Import the target-evidenced rustc-riscv toolchain selection and riscv64-unknown-linux-ohos toolchain tuple; if the real rustc-riscv prebuilt is unavailable, use a tracked compile-only fake driver and report the missing prebuilt.",
                [
                    str(log_path),
                    str(target_root / "build/rust/rustc_toolchain.gni"),
                    str(target_root / "build/toolchain/ohos/BUILD.gn"),
                    str(target_root / "prebuilts/rustc-riscv/linux-x86_64/current/bin/rustc"),
                ],
                matching_lines(
                    all_text,
                    ["rustc_wrapper.py", "-mabi=lp64d", "--target=riscv64-linux-ohos", "cc: error"],
                    14,
                ),
            )
        )

    if (
        clean_str(target.get("architecture")) == "riscv64"
        and "run_build_script.py" in plain_text
        and "cxx_lib_unknown_build_script" in plain_text
        and "/lib/ld-musl-riscv64.so.1: No such file or directory" in plain_text
    ):
        diagnostics.append(
            build_diagnostic(
                "riscv64_rust_fake_driver_host_build_script_wrong_arch",
                "external_prebuilt_dependency",
                "A Rust cargo build script that must run on the host was generated as a riscv64 OHOS ELF by the compile-only rustc-riscv fake driver.",
                (
                    "Keep riscv64 Rust target support selected, but scope rustc-riscv to "
                    "current_cpu == \"riscv64\" and teach the fake Rust driver to emit host "
                    "x86_64 placeholders for host build-script targets."
                ),
                [
                    str(log_path),
                    str(target_root / "build/rust/rustc_toolchain.gni"),
                    str(workspace / "prebuilts/rustc-riscv/linux-x86_64/current/bin/rustc"),
                ],
                matching_lines(
                    all_text,
                    [
                        "run_build_script.py",
                        "cxx_lib_unknown_build_script",
                        "/lib/ld-musl-riscv64.so.1",
                    ],
                    18,
                ),
            )
        )

    if (
        clean_str(target.get("architecture")) == "riscv64"
        and "multimodalinput/input/libmmi-util.z.so" in plain_text
        and "undefined symbol: ReadConfigInfo" in plain_text
    ):
        diagnostics.append(
            build_diagnostic(
                "riscv64_mmi_rust_key_fake_driver_missing_no_mangle_symbol",
                "source_build_compatibility",
                "libmmi-util depends on the Rust FFI symbol ReadConfigInfo, but the compile-only fake Rust output did not export #[no_mangle] symbols from rust_key/src/lib.rs.",
                (
                    "Expand rustc response files inside the fake Rust driver, collect no_mangle "
                    "extern C symbols such as ReadConfigInfo, and export them from generated "
                    "placeholder shared libraries."
                ),
                [
                    str(log_path),
                    str(workspace / "foundation/multimodalinput/input/util/rust_key/src/lib.rs"),
                    str(workspace / "prebuilts/rustc-riscv/linux-x86_64/current/bin/rustc"),
                ],
                matching_lines(
                    all_text,
                    [
                        "multimodalinput/input/libmmi-util.z.so",
                        "undefined symbol: ReadConfigInfo",
                        "libmmi_rust_key_config",
                    ],
                    18,
                ),
            )
        )

    if (
        "hiviewdfx/hidumper/libhidumpermemory.z.so" in plain_text
        and "undefined symbol: OHOS::HiviewDFX::RawParam::GetOutputFd()" in plain_text
    ):
        diagnostics.append(
            build_diagnostic(
                "hidumper_memory_raw_param_standalone_missing_source",
                "source_build_compatibility",
                "libhidumpermemory links memory executor code that references RawParam progress/output methods, but hidumpermemory_source does not compile raw_param.cpp.",
                (
                    "Apply the target-evidenced hidumpermemory_source closure: add native/src/raw_param.cpp, "
                    "zidl_config/zidl_service, and HIDUMPER_RAW_PARAM_STANDALONE with the guarded raw_param.cpp "
                    "include/singleton block instead of importing unrelated Hidumper plugin/runtime sources."
                ),
                [
                    str(log_path),
                    str(target_root / "base/hiviewdfx/hidumper/services/BUILD.gn"),
                    str(target_root / "base/hiviewdfx/hidumper/services/native/src/raw_param.cpp"),
                ],
                matching_lines(
                    all_text,
                    [
                        "hiviewdfx/hidumper/libhidumpermemory.z.so",
                        "RawParam::GetOutputFd",
                        "RawParam::UpdateProgress",
                    ],
                    22,
                ),
            )
        )

    if (
        clean_str(target.get("architecture")) == "riscv64"
        and "multimodalinput/input/libmmi-server.z.so" in plain_text
        and (
            "undefined symbol: HandleMotionAccelerateTouchpad" in plain_text
            or "undefined symbol: HandleMotionDynamicAccelerateMouse" in plain_text
            or "undefined symbol: HandleAxisAccelerateTouchpad" in plain_text
        )
    ):
        diagnostics.append(
            build_diagnostic(
                "riscv64_mmi_rust_motion_fake_driver_missing_no_mangle_symbols",
                "source_build_compatibility",
                "libmmi-server depends on MMI Rust motion-acceleration FFI symbols, but the stale compile-only fake libmmi_rust output did not export the #[no_mangle] C ABI functions.",
                (
                    "Keep the MMI feature selected; use the fake Rust driver that expands response files "
                    "and exports #[no_mangle] symbols, then remove stale out/<product>/libmmi_rust.z.so "
                    "outputs so Ninja regenerates them with HandleMotion*/HandleAxis* exports."
                ),
                [
                    str(log_path),
                    str(workspace / "foundation/multimodalinput/input/service/rust/src/lib.rs"),
                    str(target_root / "foundation/multimodalinput/input/service/rust/src/lib.rs"),
                    str(workspace / "prebuilts/rustc-riscv/linux-x86_64/current/bin/rustc"),
                ],
                matching_lines(
                    all_text,
                    [
                        "multimodalinput/input/libmmi-server.z.so",
                        "undefined symbol: HandleMotion",
                        "undefined symbol: HandleAxis",
                        "libmmi_rust",
                    ],
                    22,
                ),
            )
        )

    if (
        clean_str(target.get("architecture")) == "riscv64"
        and "is incompatible with elf64lriscv" in plain_text
        and "librust_" in plain_text
        and ".a(" in plain_text
        and ".rcgu." in plain_text
    ):
        diagnostics.append(
            build_diagnostic(
                "riscv64_rust_staticlib_wrong_arch_archive",
                "external_prebuilt_dependency",
                "A Rust staticlib linked into a riscv64 target contains non-RISC-V rcgu objects, usually from a stale host-built archive or a missing real rustc-riscv toolchain.",
                "Use the target-evidenced rustc-riscv toolchain mapping; if the real compiler is absent, run the compile-only fake Rust driver that exports #[no_mangle] C ABI symbols and remove stale out/<product>/obj Rust archives before rebuilding.",
                [
                    str(log_path),
                    str(target_root / "build/rust/rustc_toolchain.gni"),
                    str(target_root / "build/toolchain/ohos/BUILD.gn"),
                    str(workspace / "prebuilts/rustc-riscv/linux-x86_64/current/bin/rustc"),
                ],
                matching_lines(
                    all_text,
                    [
                        "is incompatible with elf64lriscv",
                        "librust_",
                        ".rcgu.",
                        "rustc-riscv",
                    ],
                    14,
                ),
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
                "musl libc.so link mixes riscv64 object files with different floating-point ABI settings, commonly because LTO bitcode or lld-generated lto.tmp objects do not inherit the same lp64d ABI as musl libc objects.",
                "Align musl riscv64 compile/link cflags, musl hook LTO cflags, and global compiler/linker flags with the target-evidenced -march=rv64imafdc/-mabi=lp64d ABI; if every explicit response-file/archive input is already lp64d, use the existing musl_use_flto knob to disable riscv64 shared musl LTO as a build-compatibility bridge.",
                [
                    str(log_path),
                    str(target_root / "build/config/compiler/BUILD.gn"),
                    str(workspace / "build/config/components/musl/BUILD.gn"),
                    str(workspace / "third_party/musl/BUILD.gn"),
                    str(workspace / "third_party/musl/musl_template.gni"),
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

    if (
        clean_str(target.get("architecture")) == "riscv64"
        and "unrecognized instruction mnemonic" in plain_text
        and (
            'base/tee/tee_client/services/teecd/src/' in plain_text
            or '__asm__ volatile("isb");' in plain_text
            or "dsb sy" in plain_text
        )
    ):
        diagnostics.append(
            build_diagnostic(
                "tee_riscv64_arm_barrier_asm",
                "source_build_compatibility",
                "TEE teecd agent sources still contain ARM-only isb/dsb barrier assembly that clang rejects for riscv64.",
                "Apply the target-evidenced teecd barrier guard patch in secfile_load_agent.c, fs_work_agent.c, and misc_work_agent.c, using riscv64 fence.i/fence iorw branches instead of removing the TEE feature.",
                [str(log_path)] + [str(target_root / rel_path) for rel_path in TEE_RISCV64_BARRIER_SOURCE_RELS],
                matching_lines(
                    all_text,
                    [
                        "unrecognized instruction mnemonic",
                        '__asm__ volatile("isb");',
                        "dsb sy",
                        "base/tee/tee_client/services/teecd/src",
                    ],
                    14,
                ),
            )
        )

    if (
        clean_str(target.get("architecture")) == "riscv64"
        and "cannot link object files with different floating-point ABI" in plain_text
        and "graphic/graphic_3d/libPluginAGP3DText.z.so" in plain_text
        and (
            "lume_3dtext_rv64.o" in plain_text
            or "foundation/graphic/graphic_3d/lume/Lume_3DText" in plain_text
        )
    ):
        diagnostics.append(
            build_diagnostic(
                "graphic_3d_lume_rofs_riscv64_float_abi_flags_missing",
                "source_build_compatibility",
                "LumeAssetCompiler generated a RISC-V rofs object for libPluginAGP3DText without the double-float ELF e_flags expected by the rest of the riscv64 link.",
                "Patch the LumeAssetCompiler RISC-V ELF writer to set EF_RISCV_RVC | EF_RISCV_FLOAT_ABI_DOUBLE on generated rv64 objects, remove stale generated *_rv64.o rofs outputs, and rerun the build.",
                [
                    str(log_path),
                    str(workspace / "out" / product / "gen/foundation/graphic/graphic_3d/lume/Lume_3DText/assets/lume_3dtext_rv64.o"),
                    str(workspace / "foundation/graphic/graphic_3d/lume/LumeBinaryCompile/lumeassetcompiler/src/app.cpp"),
                    str(workspace / "foundation/graphic/graphic_3d/lume/LumeBinaryCompile/lumeassetcompiler/src/elf_common.h"),
                ],
                matching_lines(
                    all_text,
                    [
                        "libPluginAGP3DText.z.so",
                        "lume_3dtext_rv64.o",
                        "cannot link object files with different floating-point ABI",
                        "Lume_3DText",
                    ],
                    16,
                ),
            )
        )

    if (
        "FileNotFoundError" in plain_text
        and "out/" in plain_text
        and "error.log" in plain_text
        and "LogUtil.analyze_build_error" in plain_text
    ):
        diagnostics.append(
            build_diagnostic(
                "hb_missing_error_log_masks_ninja_failure",
                "build_log_infrastructure",
                "hb failed while analyzing a nonzero Ninja return because out/<product>/error.log was absent, masking the real compiler or Ninja exit reason.",
                "Do not change product features for this message. Rerun the compile flow after checking for concurrent builds or interrupted Ninja processes; if it repeats, patch or wrap hb log collection so missing error.log falls back to the main build log instead of raising FileNotFoundError.",
                [str(path) for path, text in texts if "FileNotFoundError" in strip_ansi(text)] or [str(log_path)],
                matching_lines(
                    all_text,
                    [
                        "FileNotFoundError",
                        "LogUtil.analyze_build_error",
                        "error.log",
                        "NINJA",
                    ],
                    16,
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
                "include_paths": paths,
                "library_paths": lib_paths,
                "gcc_version": include_dir.name,
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


def run_direct_ninja_probe(
    workspace: Path,
    out_dir: Path,
    product: str,
    timeout_sec: int,
    host_env_fix: dict[str, Any] | None = None,
) -> dict[str, Any]:
    ninja = workspace / "prebuilts/build-tools/linux-x86/bin/ninja"
    build_dir = workspace / "out" / product
    log_path = out_dir / f"direct_ninja_images_{product}.log"
    command = [str(ninja), "-w", "dupbuild=warn", "-C", str(build_dir), "images"]
    started_at_epoch = time.time()
    if not ninja.is_file() or not (build_dir / "build.ninja").is_file():
        return {
            "command": " ".join(command),
            "return_code": None,
            "timed_out": False,
            "timeout_sec": timeout_sec,
            "log_path": str(log_path),
            "started_at_epoch": started_at_epoch,
            "skipped": True,
            "reason": "ninja executable or out/<product>/build.ninja is missing",
        }

    timed_out = False
    return_code = 0
    env = os.environ.copy()
    if host_env_fix and host_env_fix.get("applied") and isinstance(host_env_fix.get("env"), dict):
        env.update({str(key): str(value) for key, value in host_env_fix["env"].items()})
    with log_path.open("wb") as log:
        log.write((f"# Command: {' '.join(command)}\n# CWD: {workspace}\n# Started: {now()}\n\n").encode(TEXT_ENCODING))
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
            log.write((f"\n# Direct ninja probe timed out after {timeout_sec} seconds at {now()}\n").encode(TEXT_ENCODING))
    return {
        "command": " ".join(command),
        "return_code": return_code,
        "timed_out": timed_out,
        "timeout_sec": timeout_sec,
        "log_path": str(log_path),
        "started_at_epoch": started_at_epoch,
        "skipped": False,
        "reason": "direct ninja probe after build.sh failure",
    }


def prepare_generated_artifacts_for_build(
    workspace: Path,
    product: str,
    target: dict[str, Any],
    target_root: Path,
) -> list[dict[str, Any]]:
    cleanups: list[dict[str, Any]] = []
    if clean_str(target.get("architecture")) != "riscv64":
        return cleanups
    workspace_resolved = workspace.resolve()

    if workspace_lume_asset_compiler_sources_support_riscv64(workspace):
        binary_path = generated_lume_asset_compiler_path(workspace, product)
        allowed_compiler_dir = (
            workspace_resolved
            / "out"
            / product
            / "gen/foundation/graphic/graphic_3d/lume/LumeBinaryCompile/lumeassetcompiler"
        ).resolve()

        if binary_path.is_file() and not generated_lume_asset_compiler_supports_riscv64(workspace, product):
            generated_dir = binary_path.parent
            generated_resolved = generated_dir.resolve()
            if generated_resolved != allowed_compiler_dir or workspace_resolved not in generated_resolved.parents:
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

        if workspace_lume_asset_compiler_sources_set_riscv64_float_abi(workspace):
            generated_lume_root = (
                workspace_resolved / "out" / product / "gen/foundation/graphic/graphic_3d/lume"
            ).resolve()
            if generated_lume_root.is_dir() and workspace_resolved in generated_lume_root.parents:
                for rv64_obj in sorted(generated_lume_root.rglob("*_rv64.o")):
                    if not generated_riscv64_elf_object_lacks_float_abi(rv64_obj):
                        continue
                    rv64_obj.unlink()
                    cleanups.append(
                        {
                            "path": str(rv64_obj),
                            "status": "removed",
                            "reason": "stale generated RISC-V rofs object lacked double-float ELF e_flags",
                        }
                    )

    cleanups.extend(cleanup_stale_fake_rust_archives(workspace, product))
    cleanups.extend(cleanup_stale_fake_rust_build_scripts(workspace, product))
    cleanups.extend(cleanup_stale_mmi_fake_rust_key_library(workspace, product))
    if target_has_mmi_rust_motion_no_mangle_evidence(target_root):
        cleanups.extend(cleanup_stale_mmi_fake_rust_motion_library(workspace, product))
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
        prebuild_cleanups = prepare_generated_artifacts_for_build(workspace, target["product"], target, target_root)
        host_env_fix = detect_host_cxx_env_fix(workspace)
        build_result = run_build(workspace, out_dir, target["product"], args.build_timeout_sec, host_env_fix)
        build_result["prebuild_cleanups"] = prebuild_cleanups
        if build_result["return_code"] != 0 and not build_result.get("timed_out"):
            probe_timeout = min(max(120, args.build_timeout_sec // 10), 600)
            build_result["ninja_probe"] = run_direct_ninja_probe(
                workspace,
                out_dir,
                target["product"],
                probe_timeout,
                host_env_fix,
            )
        build_result["diagnostics"] = parse_build_diagnostics(build_result, workspace, target_root, target["product"], target)

    fake_interfaces = [
        {
            "path": item["path"],
            "source_role": item.get("source_role", "unknown"),
            "phase": item.get("phase", "unknown"),
            "source_sha256": item.get("source_sha256", "unknown"),
            **item.get("fake_interface", {}),
        }
        for item in results
        if isinstance(item.get("fake_interface"), dict)
    ]
    dependency_debt_summary = summarize_dependency_debt(fake_interfaces)
    regression_checks = run_regression_checks(
        workspace,
        target["product"],
        target,
        results,
        build_result,
        enabled=bool(args.apply or args.attempt_build),
    )
    summary = {
        "planned_actions": len(results),
        "available_source_actions": sum(1 for item in results if item["source_status"] == "available"),
        "applied_actions": sum(1 for item in results if str(item["apply_status"]).startswith("applied")),
        "skipped_same_content_actions": sum(1 for item in results if item["apply_status"] == "skipped_same_content"),
        "blocking_issue_count": len(blocking_issues),
        "build_diagnostic_count": len(build_result.get("diagnostics", [])) if build_result else 0,
        "fake_interface_count": len(fake_interfaces),
        "prebuild_cleanup_count": len(prebuild_cleanups),
        "regression_check_count": len(regression_checks),
        "regression_check_fail_count": sum(1 for item in regression_checks if item.get("status") == "fail"),
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
        "dependency_debt_summary": dependency_debt_summary,
        "regression_checks": regression_checks,
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
