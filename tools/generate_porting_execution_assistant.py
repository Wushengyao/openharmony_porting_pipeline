#!/usr/bin/env python3
"""Deterministic fallback for Stage 10 porting execution assistance.

The fallback is intentionally conservative: it writes a plan-only execution
package with bounded source-tree observations, meta-method guardrails, and
explicit uncertainty records. It does not edit source files, create patch
diffs, fetch dependencies, or claim boot/runtime/test status.
"""

from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path
from typing import Any

import yaml


STAGE = "10_porting_execution_assistant"

REQUIRED_FILES = [
    "target_profile.yaml",
    "source_tree_survey.yaml",
    "source_tree_survey.md",
    "gap_analysis.yaml",
    "gap_analysis.md",
    "porting_plan.yaml",
    "porting_plan.md",
    "patch_plan.yaml",
    "patch_plan.md",
    "build_acceptance.yaml",
    "build_acceptance.md",
    "external_dependency_followup.yaml",
    "external_dependency_followup.md",
    "uncertainty_ledger.yaml",
    "uncertainty_ledger.md",
]


def now() -> str:
    return datetime.now().astimezone().strftime("%Y-%m-%dT%H:%M:%S%z")


def rel(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except Exception:
        return path.as_posix()


def existing(root: Path, candidates: list[str]) -> list[str]:
    return [item for item in candidates if (root / item).exists()]


def bounded_glob(root: Path, pattern: str, limit: int = 12) -> list[str]:
    results: list[str] = []
    for path in sorted(root.glob(pattern)):
        if len(results) >= limit:
            break
        if path.exists():
            results.append(rel(path, root))
    return results


def read_jsonl_ids(path: Path, id_key: str) -> list[str]:
    ids: list[str] = []
    if not path.is_file():
        return ids
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            data = json.loads(line)
        except Exception:
            continue
        value = data.get(id_key)
        if isinstance(value, str) and value:
            ids.append(value)
    return ids


def read_target_seed(path: Path | None) -> dict[str, Any]:
    if not path or not path.is_file():
        return {}
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8", errors="ignore")) or {}
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def detect_version(root: Path) -> str:
    version_gni = root / "build/version.gni"
    if not version_gni.is_file():
        return "unknown"
    text = version_gni.read_text(encoding="utf-8", errors="ignore")
    api_version = "unknown"
    release_type = "unknown"
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("api_version"):
            api_version = line.split("=", 1)[-1].strip().strip('"')
        elif line.startswith("release_type"):
            release_type = line.split("=", 1)[-1].strip().strip('"')
    if api_version != "unknown" or release_type != "unknown":
        return f"api_version={api_version}, release_type={release_type}"
    return "unknown"


def detect_vendor_product(root: Path) -> dict[str, str]:
    for rel_path in bounded_glob(root, "vendor/*/*/config.json", limit=20):
        path = root / rel_path
        try:
            data = json.loads(path.read_text(encoding="utf-8", errors="ignore"))
        except Exception:
            continue
        if not isinstance(data, dict):
            continue
        product = str(data.get("product_name") or "unknown")
        board = str(data.get("board") or data.get("device_name") or "unknown")
        vendor = rel_path.split("/")[1] if "/" in rel_path else "unknown"
        cpu = str(data.get("target_cpu") or "unknown")
        return {
            "product": product,
            "board": board,
            "vendor": vendor,
            "architecture": cpu,
            "evidence": f"source_file:{rel_path}",
        }
    return {
        "product": "unknown",
        "board": "unknown",
        "vendor": "unknown",
        "architecture": "unknown",
        "evidence": "source_tree:vendor",
    }


def clean_str(value: Any, default: str = "unknown") -> str:
    if isinstance(value, str) and value.strip():
        return value.strip()
    if value is not None and not isinstance(value, (dict, list, tuple, set)):
        text = str(value).strip()
        if text:
            return text
    return default


def seed_ref(path: Path | None, workspace: Path) -> str:
    if path and path.exists():
        return f"source_file:{rel(path, workspace)}"
    return "user_requirement:run_porting_execution_assistant_with_meta_output_zip"


def target_visibility(root: Path, target: dict[str, str], seed: dict[str, Any]) -> dict[str, Any]:
    product = target.get("product", "unknown")
    board = target.get("board", "unknown")
    soc = target.get("soc", "unknown")
    vendor = target.get("vendor", "unknown")
    soc_vendor = clean_str(seed.get("soc_vendor"))

    product_checks = []
    if product != "unknown":
        product_checks.extend(
            [
                f"vendor/{vendor}/{product}/config.json",
                f"productdefine/common/products/{product}.json",
            ]
        )
        product_checks.extend(bounded_glob(root, f"vendor/*/{product}/config.json", limit=8))
    board_checks = []
    if board != "unknown":
        board_checks.extend(
            [
                f"device/board/{vendor}/{board}/config.gni",
                f"device/board/{vendor}/{board}/device.gni",
                f"device/board/{vendor}/{board}",
            ]
        )
        board_checks.extend(bounded_glob(root, f"device/board/*/{board}/config.gni", limit=8))
        board_checks.extend(bounded_glob(root, f"device/board/*/{board}/device.gni", limit=8))
    soc_checks = []
    if soc != "unknown":
        if soc_vendor != "unknown":
            soc_checks.extend(
                [
                    f"device/soc/{soc_vendor}/{soc}/soc.gni",
                    f"device/soc/{soc_vendor}/{soc}",
                ]
            )
        soc_checks.extend(bounded_glob(root, f"device/soc/*/{soc}/soc.gni", limit=8))
        soc_checks.extend(bounded_glob(root, f"device/soc/*/{soc}", limit=8))
    kernel_checks = []
    for name in [product, board, soc]:
        if name != "unknown":
            kernel_checks.extend(
                [
                    f"kernel/linux/{name}-kernel",
                    f"kernel/linux/{name}",
                ]
            )

    def split(paths: list[str]) -> tuple[list[str], list[str]]:
        unique = list(dict.fromkeys(paths))
        found = [item for item in unique if (root / item).exists()]
        missing = [item for item in unique if not (root / item).exists()]
        return found, missing

    product_found, product_missing = split(product_checks)
    board_found, board_missing = split(board_checks)
    soc_found, soc_missing = split(soc_checks)
    kernel_found, kernel_missing = split(kernel_checks)

    return {
        "product_found": product_found,
        "product_missing": product_missing,
        "board_found": board_found,
        "board_missing": board_missing,
        "soc_found": soc_found,
        "soc_missing": soc_missing,
        "kernel_found": kernel_found,
        "kernel_missing": kernel_missing,
        "product_visible": bool(product_found),
        "board_visible": bool(board_found),
        "soc_visible": bool(soc_found),
        "kernel_visible": bool(kernel_found),
    }


def dump_yaml(path: Path, data: dict[str, Any]) -> None:
    path.write_text(
        yaml.safe_dump(data, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )


def write_text(path: Path, text: str) -> None:
    path.write_text(text.rstrip() + "\n", encoding="utf-8")


def artifact_base(artifact_type: str) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "artifact_type": artifact_type,
        "generated_at": now(),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--artifact-root", required=True)
    parser.add_argument("--source-output", required=True)
    parser.add_argument("--meta-output", default="")
    parser.add_argument("--target-profile", default="")
    parser.add_argument("--build-log", default="")
    parser.add_argument("--stage-result", required=True)
    parser.add_argument("--execution-mode", default="plan-only")
    parser.add_argument("--patch-apply-mode", default="none")
    args = parser.parse_args()

    workspace = Path(args.workspace).resolve()
    out = Path(args.out).resolve()
    artifact_root = Path(args.artifact_root).resolve()
    source_output = Path(args.source_output).resolve()
    meta_output = Path(args.meta_output).resolve() if args.meta_output else None
    target_seed_path = Path(args.target_profile).resolve() if args.target_profile else None
    build_log_path = Path(args.build_log).resolve() if args.build_log else None
    stage_result = Path(args.stage_result).resolve()
    artifact_root.mkdir(parents=True, exist_ok=True)
    stage_result.parent.mkdir(parents=True, exist_ok=True)

    print(json.dumps({"event": "start", "stage": STAGE, "time": now()}))

    source_stage_files = existing(
        source_output,
        [
            "00_config/task_profile.yaml",
            "07_meta_inputs/scenario_card.yaml",
            "02_statistics/statistics_summary.json",
            "06_audit/final_audit_report.md",
        ],
    )
    build_files = existing(
        workspace,
        [
            "build.sh",
            "build/build_scripts/build.sh",
            "build/version.gni",
            "build/ohos_var.gni",
        ],
    )
    product_files = existing(
        workspace,
        [
            "productdefine/common/products/system_arm64_default.json",
            "productdefine/common/products/system_arm_default.json",
            "productdefine/common/products/ohos-sdk.json",
        ],
    )
    product_files.extend(bounded_glob(workspace, "vendor/*/*/config.json", limit=12))
    board_files = bounded_glob(workspace, "device/board/*/*/config.gni", limit=12)
    board_files.extend(bounded_glob(workspace, "device/board/*/*/device.gni", limit=12))
    soc_files = bounded_glob(workspace, "device/soc/*/*/soc.gni", limit=12)
    kernel_files = existing(workspace, ["kernel/linux", "kernel/liteos_a", "kernel/liteos_m"])
    prebuilt_paths = existing(workspace, ["prebuilts", "third_party", "vendor"])
    detected_product = detect_vendor_product(workspace)
    target_seed = read_target_seed(target_seed_path)
    version = detect_version(workspace)

    meta_methods: list[str] = []
    conditional_methods: list[str] = []
    if meta_output and meta_output.exists():
        meta_methods = read_jsonl_ids(meta_output / "02_patterns/meta_methods.jsonl", "method_id")
        conditional_methods = read_jsonl_ids(meta_output / "02_patterns/conditional_methods.jsonl", "method_id")
    validation_method = "META-UNIVERSAL_BY_DESIGN_VALIDATION_SEPARATION"
    evidence_method = "META-UNIVERSAL_BY_DESIGN_EVIDENCE_CLASS_SEPARATION"
    scope_method = "META-UNIVERSAL_BY_DESIGN_SCENARIO_SCOPE_AUTHORITY"
    binary_method = "META-CONDITIONAL-BINARY-PREBUILT-PROVENANCE"
    dirty_method = "META-CONDITIONAL-DIRTY-WORKSPACE-GOVERNANCE"
    hdf_method = "META-CONDITIONAL-HDF-DRIVER-MULTIREPO-CHAIN"
    riscv_method = "META-CONDITIONAL-RISCV-BUILD-RUNTIME-ROUTE"
    boot_method = "META-CONDITIONAL-BOOT-FIRMWARE-PROVENANCE"
    wifi_method = "META-CONDITIONAL-WIFI-SDIO-RUNTIME-CHAIN"
    media_method = "META-CONDITIONAL-MEDIA-CAMERA-HDF-CHAIN"

    user_ref = "user_requirement:run_porting_execution_assistant_with_meta_output_zip"
    workspace_ref = f"workspace:{workspace}"
    meta_ref = f"meta_method:{validation_method}"
    build_ref = "source_file:build/build_scripts/build.sh" if "build/build_scripts/build.sh" in build_files else "source_tree:build"
    product_ref = detected_product["evidence"]
    target_seed_ref = seed_ref(target_seed_path, workspace)

    target = {
        "product": "unknown",
        "board": "unknown",
        "soc": "unknown",
        "vendor": "unknown",
        "architecture": "unknown",
        "openharmony_version": version,
    }
    for key in ["product", "board", "soc", "vendor", "architecture", "openharmony_version"]:
        value = target_seed.get(key)
        if isinstance(value, str) and value.strip():
            target[key] = value.strip()
    target_supplied = any(value != "unknown" for value in target.values()) and bool(target_seed)
    visibility = target_visibility(workspace, target, target_seed) if target_supplied else {}

    target_profile = artifact_base("target_profile")
    target_profile.update(
        {
            "execution_mode": "plan-only",
            "target": target,
            "source_context": {
                "workspace_root": str(workspace),
                "source_output": str(source_output),
                "meta_output": str(meta_output) if meta_output else "unknown",
                "target_profile_seed": str(target_seed_path) if target_seed_path else "unknown",
                "build_log": str(build_log_path) if build_log_path else "unknown",
                "detected_source_product_candidate": detected_product,
                "target_source_visibility": visibility if visibility else "unknown",
            },
            "requirements": [
                {
                    "requirement_id": "REQ-001",
                    "description": "Generate a plan-only OpenHarmony porting execution assistant package from the current workspace and supplied cross-scenario meta output.",
                    "source": "user_requirement",
                    "evidence_refs": [user_ref, workspace_ref],
                },
                {
                    "requirement_id": "REQ-002",
                    "description": f"Use the supplied target profile seed as the target identity: product={target['product']}, board={target['board']}, soc={target['soc']}, vendor={target['vendor']}, architecture={target['architecture']}.",
                    "source": "user_requirement" if target_supplied else "unknown",
                    "evidence_refs": [target_seed_ref, f"meta_method:{scope_method}"],
                },
                {
                    "requirement_id": "REQ-003",
                    "description": "Keep execution assistance plan-only: no source edits, no patch files, no external dependency artifacts, and no boot/runtime/test status claims.",
                    "source": "meta_method",
                    "evidence_refs": [meta_ref, f"meta_method:{evidence_method}"],
                },
            ],
        }
    )

    target_product_paths = visibility.get("product_found", []) if visibility else []
    target_board_paths = visibility.get("board_found", []) if visibility else []
    target_soc_paths = visibility.get("soc_found", []) if visibility else []
    target_kernel_paths = visibility.get("kernel_found", []) if visibility else []
    target_product_missing = visibility.get("product_missing", []) if visibility else []
    target_board_missing = visibility.get("board_missing", []) if visibility else []
    target_soc_missing = visibility.get("soc_missing", []) if visibility else []
    target_kernel_missing = visibility.get("kernel_missing", []) if visibility else []

    survey_items = [
        {
            "survey_id": "SURVEY-001",
            "topic": "build_entrypoint",
            "status": "found" if build_files else "missing",
            "paths": build_files,
            "observation": "OpenHarmony build entry points are present; acceptance must call only existing build scripts and remain build-only.",
            "evidence_refs": [build_ref, workspace_ref],
        },
        {
            "survey_id": "SURVEY-002",
            "topic": "product_config",
            "status": "found" if target_product_paths else "ambiguous",
            "paths": (target_product_paths + product_files[:12])[:16],
            "expected_missing_paths": target_product_missing[:8],
            "observation": f"Target product `{target['product']}` is supplied by the target-profile seed; this workspace exposes reference product configs, but no matching `{target['vendor']}/{target['product']}` or productdefine config was found.",
            "evidence_refs": [target_seed_ref, product_ref, f"meta_method:{scope_method}"],
        },
        {
            "survey_id": "SURVEY-003",
            "topic": "device_board",
            "status": "found" if target_board_paths or target_soc_paths else "ambiguous",
            "paths": (target_board_paths + target_soc_paths + board_files[:8] + soc_files[:8])[:20],
            "expected_missing_paths": (target_board_missing + target_soc_missing)[:12],
            "observation": f"Target board `{target['board']}` and SoC `{target['soc']}` are supplied by seed, but matching board/SoC configuration is not visible in the current source tree survey.",
            "evidence_refs": [target_seed_ref, f"meta_method:{scope_method}", f"meta_method:{riscv_method}"],
        },
        {
            "survey_id": "SURVEY-004",
            "topic": "kernel",
            "status": "found" if target_kernel_paths else ("ambiguous" if kernel_files else "unknown"),
            "paths": (target_kernel_paths + kernel_files)[:12],
            "expected_missing_paths": target_kernel_missing[:8],
            "observation": f"Generic kernel directories are present, but no target-specific kernel path for `{target['product']}`/`{target['board']}`/`{target['soc']}` was found; build, boot, driver runtime, and board smoke logs remain unknown.",
            "evidence_refs": [target_seed_ref, workspace_ref, f"meta_method:{validation_method}", f"meta_method:{riscv_method}"],
        },
        {
            "survey_id": "SURVEY-005",
            "topic": "vendor_blob",
            "status": "ambiguous" if prebuilt_paths else "unknown",
            "paths": prebuilt_paths,
            "observation": f"Potential prebuilt, third-party, and vendor areas require provenance review for the `{target['product']}`/`{target['soc']}` port before any source patch can be promoted.",
            "evidence_refs": [target_seed_ref, workspace_ref, f"meta_method:{binary_method}"],
        },
        {
            "survey_id": "SURVEY-006",
            "topic": "signing_packaging",
            "status": "unknown",
            "paths": [],
            "observation": f"Signing and packaging requirements for `{target['product']}` images are not confirmed by the supplied inputs and must remain an external follow-up.",
            "evidence_refs": [target_seed_ref, f"meta_method:{binary_method}"],
        },
        {
            "survey_id": "SURVEY-007",
            "topic": "other",
            "status": "found" if target_supplied else "missing",
            "paths": [rel(target_seed_path, workspace)] if target_seed_path else [],
            "observation": f"Target identity is supplied by seed as `{target['product']}`/`{target['board']}`/`{target['soc']}`/`{target['vendor']}`/`{target['architecture']}`; source-tree visibility is a separate check.",
            "evidence_refs": [target_seed_ref, f"meta_method:{scope_method}"],
        },
    ]
    source_tree_survey = artifact_base("source_tree_survey")
    source_tree_survey["items"] = survey_items

    gaps = [
        {
            "gap_id": "GAP-001",
            "area": "product_config",
            "severity": "blocker",
            "description": f"Target identity is supplied by seed as `{target['product']}`/`{target['board']}`/`{target['soc']}`/`{target['vendor']}`/`{target['architecture']}`, but target product config is not visible in the current source tree.",
            "owner_hint": "source_patch",
            "evidence_refs": [target_seed_ref, workspace_ref, f"meta_method:{scope_method}", f"meta_method:{riscv_method}"],
            "uncertainty_refs": ["UNC-001"],
        },
        {
            "gap_id": "GAP-002",
            "area": "board_config",
            "severity": "blocker",
            "description": f"Target board/SoC configuration paths for `{target['board']}` and `{target['soc']}` are not visible under device/board or device/soc; reference HiHope/Rockchip/Hisilicon paths must not be treated as the target.",
            "owner_hint": "source_patch",
            "evidence_refs": [target_seed_ref, product_ref, f"meta_method:{scope_method}", f"meta_method:{riscv_method}"],
            "uncertainty_refs": ["UNC-002"],
        },
        {
            "gap_id": "GAP-003",
            "area": "kernel",
            "severity": "high",
            "description": f"Target kernel branch, DTS, defconfig, and TH1520/RVBook kernel binding are not visible in the current OpenHarmony source tree.",
            "owner_hint": "vendor_or_third_party",
            "evidence_refs": [target_seed_ref, workspace_ref, f"meta_method:{riscv_method}", f"meta_method:{boot_method}"],
            "uncertainty_refs": ["UNC-003"],
        },
        {
            "gap_id": "GAP-004",
            "area": "build",
            "severity": "high",
            "description": f"The RISC-V `{target['architecture']}` build/product route cannot be accepted until `{target['product']}` is product-visible; source-output absence limits evidence depth but is not the product-visibility blocker.",
            "owner_hint": "source_patch",
            "evidence_refs": [target_seed_ref, build_ref, f"meta_method:{riscv_method}", f"meta_method:{validation_method}"],
            "uncertainty_refs": ["UNC-004"],
        },
        {
            "gap_id": "GAP-005",
            "area": "bootloader",
            "severity": "high",
            "description": f"OpenSBI/U-Boot/bootloader, partition layout, and image packaging requirements for `{target['product']}`/`{target['soc']}` are not established.",
            "owner_hint": "vendor_or_third_party",
            "evidence_refs": [target_seed_ref, f"meta_method:{boot_method}", f"meta_method:{binary_method}"],
            "uncertainty_refs": ["UNC-005"],
        },
        {
            "gap_id": "GAP-006",
            "area": "binary_prebuilt",
            "severity": "medium",
            "description": f"Firmware, prebuilts, closed drivers, and signing/packaging tools for `{target['product']}` are not inventoried with path, hash, provenance, license, and regeneration status.",
            "owner_hint": "vendor_or_third_party",
            "evidence_refs": [target_seed_ref, workspace_ref, f"meta_method:{binary_method}"],
            "uncertainty_refs": ["UNC-006", "UNC-007"],
        },
        {
            "gap_id": "GAP-007",
            "area": "subsystem",
            "severity": "low",
            "description": "Compact single-scenario Stage 00-07 artifacts are absent, so evidence depth is limited to workspace survey, target seed, and meta-output methods.",
            "owner_hint": "unknown",
            "evidence_refs": [workspace_ref, f"meta_method:{evidence_method}"],
            "uncertainty_refs": ["UNC-008"],
        },
        {
            "gap_id": "GAP-008",
            "area": "hdf_driver",
            "severity": "medium",
            "description": "Feature-specific HDF, WiFi, audio, display, media, camera, and runtime service scopes remain unselected for the target and must wait for product/board/SoC visibility plus feature requirements.",
            "owner_hint": "user_decision",
            "evidence_refs": [target_seed_ref, f"meta_method:{hdf_method}", f"meta_method:{wifi_method}", f"meta_method:{media_method}"],
            "uncertainty_refs": ["UNC-009"],
        },
    ]
    gap_analysis = artifact_base("gap_analysis")
    gap_analysis["gaps"] = gaps

    phases = [
        {
            "phase_id": "PHASE-001",
            "title": "Verify Target Source Visibility",
            "objective": f"Treat the seed target `{target['product']}`/`{target['board']}`/`{target['soc']}`/`{target['vendor']}`/`{target['architecture']}` as confirmed by user input, then verify whether matching product, board, and SoC paths are visible in the current source tree.",
            "prerequisites": ["target profile seed supplied"],
            "tasks": [
                {
                    "task_id": "TASK-001",
                    "description": f"Check product visibility for `{target['product']}` under productdefine and vendor product configuration paths.",
                    "output": "L1 product visibility result",
                    "evidence_refs": [target_seed_ref, workspace_ref, f"meta_method:{scope_method}", f"meta_method:{riscv_method}"],
                },
                {
                    "task_id": "TASK-002",
                    "description": f"Check board and SoC visibility for `{target['board']}` and `{target['soc']}`; keep reference HiHope/Rockchip paths separate from the target.",
                    "output": "target board/SoC visibility result",
                    "evidence_refs": [target_seed_ref, product_ref, f"meta_method:{scope_method}"],
                },
            ],
            "acceptance": ["target identity is seed-confirmed", "source-tree visibility is reported separately"],
            "evidence_refs": [target_seed_ref, f"meta_method:{scope_method}"],
        },
        {
            "phase_id": "PHASE-002",
            "title": "Plan Target Skeleton",
            "objective": f"Prepare a manual-review patch plan for making `{target['product']}` visible before build acceptance.",
            "prerequisites": ["target source visibility gaps recorded"],
            "tasks": [
                {
                    "task_id": "TASK-003",
                    "description": f"Plan product and vendor config skeletons for `{target['product']}` and `{target['vendor']}` without generating patch diffs in P0.",
                    "output": "product/vendor skeleton patch plan",
                    "evidence_refs": [target_seed_ref, f"meta_method:{scope_method}", f"meta_method:{riscv_method}"],
                },
                {
                    "task_id": "TASK-004",
                    "description": f"Plan board and SoC skeletons for `{target['board']}` and `{target['soc']}`, including kernel and toolchain binding questions.",
                    "output": "board/SoC/kernel skeleton patch plan",
                    "evidence_refs": [target_seed_ref, f"meta_method:{riscv_method}", f"meta_method:{boot_method}"],
                },
            ],
            "acceptance": ["all target skeleton changes stay manual-review and plan-only"],
            "evidence_refs": [target_seed_ref, f"meta_method:{evidence_method}"],
        },
        {
            "phase_id": "PHASE-003",
            "title": "Select RISC-V Porting Route",
            "objective": "Use RISC-V build/runtime/product-route, boot/firmware provenance, binary/prebuilt, and dirty-workspace governance methods within their stated applicability.",
            "prerequisites": ["target identity confirmed by seed", "target visibility gaps recorded"],
            "tasks": [
                {
                    "task_id": "TASK-005",
                    "description": "Select RISC-V build/runtime/product-route methods first; defer HDF, WiFi, media, camera, audio, and display feature methods until product/board/SoC evidence and feature requirements exist.",
                    "output": "evidence-bound method selection",
                    "evidence_refs": [target_seed_ref, f"meta_method:{riscv_method}", f"meta_method:{boot_method}", f"meta_method:{binary_method}", f"meta_method:{dirty_method}"],
                }
            ],
            "acceptance": ["each selected method cites matching source evidence"],
            "evidence_refs": [f"meta_method:{validation_method}", f"meta_method:{evidence_method}"],
        },
        {
            "phase_id": "PHASE-004",
            "title": "Build-Only Acceptance",
            "objective": f"Keep build acceptance blocked until `{target['product']}` is visible to the build system; never substitute `rk3568` or another reference product as target acceptance.",
            "prerequisites": ["L1 product visible"],
            "tasks": [
                {
                    "task_id": "TASK-006",
                    "description": f"After product visibility passes, run only the target build command template for `{target['product']}` and capture logs as build-only evidence.",
                    "output": "build log and build-only acceptance record after product visibility",
                    "evidence_refs": [target_seed_ref, build_ref, f"meta_method:{validation_method}", f"meta_method:{riscv_method}"],
                }
            ],
            "acceptance": ["build result recorded separately from device bring-up status"],
            "evidence_refs": [target_seed_ref, build_ref, f"meta_method:{validation_method}"],
        },
    ]
    porting_plan = artifact_base("porting_plan")
    porting_plan.update(
        {
            "phases": phases,
            "case_selector": {
                "selected_cases": [],
                "selected_meta_methods": [
                    mid
                    for mid in [
                        validation_method,
                        evidence_method,
                        scope_method,
                        riscv_method,
                        boot_method,
                        binary_method,
                        dirty_method,
                    ]
                    if mid in meta_methods or mid in conditional_methods or mid.startswith("META-UNIVERSAL")
                ],
                "candidate_feature_methods_deferred": [hdf_method, wifi_method, media_method],
                "selection_note": "The target is RISC-V primary by seed, so the RISC-V build/runtime/product route is selected. Feature-specific HDF/WiFi/media methods are deferred until target product, board, SoC, and feature evidence are visible. No single-scenario cases were selected because source-output lacks Stage 04-07 case artifacts.",
            },
        }
    )

    patch_plan = artifact_base("patch_plan")
    patch_plan.update(
        {
            "default_apply_mode": "plan-only",
            "patches": [
                {
                    "patch_id": "PATCH-001",
                    "title": f"Make target product `{target['product']}` visible to the build system",
                    "target_paths": [
                        f"productdefine/common/products/{target['product']}.json",
                        f"vendor/{target['vendor']}/{target['product']}/config.json",
                        f"vendor/{target['vendor']}/{target['product']}/ohos.build",
                    ],
                    "risk_level": "medium",
                    "apply_mode": "manual_review",
                    "auto_generate": False,
                    "rationale": f"P0 may plan product visibility work for `{target['product']}`, but must not generate a diff until productdefine/vendor ownership and target source evidence are confirmed.",
                    "evidence_refs": [target_seed_ref, product_ref, f"meta_method:{scope_method}", f"meta_method:{riscv_method}"],
                    "blocked_by_external_dependency": False,
                    "proposed_paths": [
                        f"productdefine/common/products/{target['product']}.json",
                        f"vendor/{target['vendor']}/{target['product']}/config.json",
                        f"vendor/{target['vendor']}/{target['product']}/ohos.build",
                    ],
                },
                {
                    "patch_id": "PATCH-002",
                    "title": f"Plan `{target['board']}` board and `{target['soc']}` SoC skeleton",
                    "target_paths": [
                        f"device/board/{target['vendor']}/{target['board']}/config.gni",
                        f"device/board/{target['vendor']}/{target['board']}/device.gni",
                        f"device/soc/{clean_str(target_seed.get('soc_vendor'), target['vendor'])}/{target['soc']}/soc.gni",
                        f"kernel/linux/{target['board']}-kernel",
                    ],
                    "risk_level": "high",
                    "apply_mode": "manual_review",
                    "auto_generate": False,
                    "rationale": "Board, SoC, kernel, DTS, defconfig, and RISC-V toolchain routing cross multiple ownership boundaries and require target-specific evidence before a patch can be generated.",
                    "evidence_refs": [target_seed_ref, product_ref, f"meta_method:{riscv_method}", f"meta_method:{boot_method}"],
                    "blocked_by_external_dependency": False,
                    "proposed_paths": [
                        f"device/board/{target['vendor']}/{target['board']}/config.gni",
                        f"device/board/{target['vendor']}/{target['board']}/device.gni",
                        f"device/soc/{clean_str(target_seed.get('soc_vendor'), target['vendor'])}/{target['soc']}/soc.gni",
                    ],
                },
                {
                    "patch_id": "PATCH-003",
                    "title": f"External boot, firmware, prebuilt, and signing integration for `{target['product']}`",
                    "target_paths": prebuilt_paths,
                    "risk_level": "external_dependency",
                    "apply_mode": "none",
                    "auto_generate": False,
                    "rationale": "Binary and external dependency artifacts require provenance, licensing, hash, regeneration, signing, and board-validation decisions outside automatic patch generation.",
                    "evidence_refs": [target_seed_ref, workspace_ref, f"meta_method:{binary_method}", f"meta_method:{boot_method}"],
                    "blocked_by_external_dependency": True,
                },
            ],
        }
    )

    build_acceptance = artifact_base("build_acceptance")
    build_acceptance.update(
        {
            "scope": "build_only",
            "environment_setup_policy": "forbidden",
            "status": "blocked_by_product_config" if not target_product_paths else "ready_for_build_only_triage",
            "acceptance_level": "L1_product_visible_failed" if not target_product_paths else "L1_product_visible",
            "blocked_reason": "" if target_product_paths else f"Target product `{target['product']}` is supplied by seed but no matching product configuration is visible in the current source tree.",
            "commands": [
                {
                    "command_id": "CMD-001",
                    "command": f"./build.sh --product-name {target['product']} --ccache=false",
                    "description": f"Target build-only command template for `{target['product']}`; do not run until L1 product visibility passes. Reference products such as rk3568 must not be used as target acceptance.",
                    "uses_existing_script": True,
                    "environment_setup": False,
                    "runnable_now": bool(target_product_paths),
                    "blocked_by_product_config": not bool(target_product_paths),
                    "expected_output": "build log for compile-flow triage only after product visibility passes",
                    "evidence_refs": [target_seed_ref, build_ref, f"meta_method:{validation_method}", f"meta_method:{riscv_method}"],
                }
            ],
            "status_boundaries": {
                "build_status": "unknown",
                "boot_status": "unknown",
                "runtime_status": "unknown",
                "test_status": "unknown",
            },
        }
    )

    coverage = [{"category": item} for item in ["bsp", "bootloader", "firmware", "prebuilt", "closed_driver", "signing_packaging_tools"]]
    external_items = [
        {
            "dependency_id": "DEP-001",
            "category": "bsp",
            "why_needed": f"TH1520/RVBook board support package ownership, source branch, and baseline hardware assumptions are not established in the current source tree.",
            "next_action": f"Collect the `{target['vendor']}`/`{target['board']}` BSP source, ownership, license, and mapping to `{target['soc']}` before planning source patches.",
            "evidence_refs": [target_seed_ref, workspace_ref, f"meta_method:{riscv_method}", f"meta_method:{binary_method}"],
        },
        {
            "dependency_id": "DEP-002",
            "category": "bootloader",
            "why_needed": f"OpenSBI/U-Boot/bootloader requirements, partition flow, and board boot evidence for `{target['board']}` are not present in the inputs.",
            "next_action": "Collect OpenSBI, U-Boot, bootloader source or release notes, partition layout, and board boot logs before integration.",
            "evidence_refs": [target_seed_ref, workspace_ref, f"meta_method:{boot_method}", f"meta_method:{validation_method}"],
        },
        {
            "dependency_id": "DEP-003",
            "category": "firmware",
            "why_needed": f"Firmware payloads for `{target['soc']}` peripherals, including WiFi/Bluetooth/audio/display/camera when required, have no path, hash, architecture, or runtime-use evidence.",
            "next_action": "Record firmware path, hash, license, redistribution status, regeneration route, and device log evidence.",
            "evidence_refs": [target_seed_ref, workspace_ref, f"meta_method:{binary_method}"],
        },
        {
            "dependency_id": "DEP-004",
            "category": "prebuilt",
            "why_needed": f"RISC-V toolchain, SDK, kernel module, and board library prebuilts for `{target['architecture']}` cannot be inferred from generic directory presence.",
            "next_action": "Create a prebuilt inventory with path, hash, license, upstream/source route, and regeneration status.",
            "evidence_refs": [target_seed_ref, workspace_ref, f"meta_method:{riscv_method}", f"meta_method:{binary_method}"],
        },
        {
            "dependency_id": "DEP-005",
            "category": "closed_driver",
            "why_needed": f"Closed driver requirements and redistribution constraints for `{target['board']}` peripherals are not supplied.",
            "next_action": "Get vendor confirmation for driver package, interface contract, license, redistribution constraints, and validation logs.",
            "evidence_refs": [target_seed_ref, workspace_ref, f"meta_method:{binary_method}"],
        },
        {
            "dependency_id": "DEP-006",
            "category": "signing_packaging_tools",
            "why_needed": f"Image packaging, signing, partition, and release tooling for `{target['product']}` are outside the visible evidence.",
            "next_action": "Collect signing key policy, packaging scripts, partition/image layout, and release owner confirmation.",
            "evidence_refs": [target_seed_ref, f"meta_method:{binary_method}", f"meta_method:{boot_method}"],
        },
    ]
    external_dependency_followup = artifact_base("external_dependency_followup")
    external_dependency_followup.update({"coverage": coverage, "items": external_items})

    uncertainties = [
        ("UNC-001", "target_source_visibility", f"Target identity is supplied by seed, but `{target['product']}` product config is not visible in the current source tree.", "Add or point to productdefine/vendor product configuration for the target."),
        ("UNC-002", "board_soc_visibility", f"Target board `{target['board']}` and SoC `{target['soc']}` are not visible in the current source-tree survey.", "Add or point to device/board and device/soc configuration paths for the target."),
        ("UNC-003", "target_kernel_route", f"Kernel branch, DTS, defconfig, and target-specific kernel path for `{target['board']}`/`{target['soc']}` are unknown.", "Collect target kernel source, DTS, defconfig, and kernel build binding evidence."),
        ("UNC-004", "build_log", "No existing build log was supplied, and target product visibility has not passed.", "Capture a build-only log only after product visibility passes."),
        ("UNC-005", "boot_firmware_route", "OpenSBI, U-Boot, bootloader, partition layout, and image packaging route are unknown.", "Collect bootloader, firmware, partition, and packaging evidence before integration."),
        ("UNC-006", "binary_provenance", "Prebuilt and firmware provenance is unknown.", "Inventory binary assets with path, hash, source, license, and regeneration status."),
        ("UNC-007", "signing_packaging", "Signing and packaging requirements are unknown.", "Ask release owner for signing and packaging constraints."),
        ("UNC-008", "single_scenario_evidence", "source-output lacks task_profile, raw records, cases, and audit files; evidence depth is limited but the target seed is still valid.", "Run the evidence pipeline or provide compact Stage 00-07 outputs when deeper traceability is required."),
        ("UNC-009", "feature_scope", "Required HDF, WiFi, media, camera, display, audio, and runtime service feature scope is not selected.", "Confirm required target features before selecting feature-specific conditional methods."),
    ]
    uncertainty_ledger = artifact_base("uncertainty_ledger")
    uncertainty_ledger["items"] = [
        {
            "uncertainty_id": uid,
            "area": area,
            "unknown": unknown,
            "risk": "automatic source guidance would overstate evidence",
            "next_check": next_check,
            "evidence_refs": [f"unknown:{uid.lower()}", target_seed_ref if uid in {"UNC-001", "UNC-002", "UNC-003", "UNC-004", "UNC-005", "UNC-009"} else workspace_ref],
        }
        for uid, area, unknown, next_check in uncertainties
    ]

    artifacts: dict[str, dict[str, Any]] = {
        "target_profile.yaml": target_profile,
        "source_tree_survey.yaml": source_tree_survey,
        "gap_analysis.yaml": gap_analysis,
        "porting_plan.yaml": porting_plan,
        "patch_plan.yaml": patch_plan,
        "build_acceptance.yaml": build_acceptance,
        "external_dependency_followup.yaml": external_dependency_followup,
        "uncertainty_ledger.yaml": uncertainty_ledger,
    }
    for name, data in artifacts.items():
        dump_yaml(artifact_root / name, data)

    write_text(
        artifact_root / "source_tree_survey.md",
        "# Source Tree Survey\n\n"
        + "\n".join(f"- {item['survey_id']} `{item['topic']}`: {item['status']} - {item['observation']}" for item in survey_items),
    )
    write_text(
        artifact_root / "gap_analysis.md",
        "# Gap Analysis\n\n"
        + "\n".join(f"- {gap['gap_id']} `{gap['area']}` ({gap['severity']}): {gap['description']}" for gap in gaps),
    )
    write_text(
        artifact_root / "porting_plan.md",
        "# Porting Plan\n\n"
        + "\n".join(f"- {phase['phase_id']} {phase['title']}: {phase['objective']}" for phase in phases),
    )
    write_text(
        artifact_root / "patch_plan.md",
        "# Patch Plan\n\nNo patch diffs are generated in plan-only mode.\n\n"
        + "\n".join(f"- {patch['patch_id']} {patch['title']}: {patch['apply_mode']}, risk={patch['risk_level']}" for patch in patch_plan["patches"]),
    )
    write_text(
        artifact_root / "build_acceptance.md",
        "# Build Acceptance\n\n"
        f"- Status: `{build_acceptance['status']}`\n"
        f"- Acceptance level: `{build_acceptance['acceptance_level']}`\n"
        f"- Blocked reason: {build_acceptance['blocked_reason'] or 'none'}\n\n"
        "Scope is build-only. Device boot, runtime, and tests remain unknown without explicit logs.\n\n"
        + "\n".join(
            f"- {cmd['command_id']}: `{cmd['command']}`; runnable_now={str(cmd['runnable_now']).lower()}; blocked_by_product_config={str(cmd['blocked_by_product_config']).lower()}"
            for cmd in build_acceptance["commands"]
        ),
    )
    write_text(
        artifact_root / "external_dependency_followup.md",
        "# External Dependency Follow-Up\n\n"
        + "\n".join(f"- {item['dependency_id']} `{item['category']}`: {item['why_needed']}" for item in external_items),
    )
    write_text(
        artifact_root / "uncertainty_ledger.md",
        "# Uncertainty Ledger\n\n"
        + "\n".join(f"- {item['uncertainty_id']} `{item['area']}`: {item['unknown']}" for item in uncertainty_ledger["items"]),
    )

    output_files = [str(artifact_root / name) for name in REQUIRED_FILES]
    inputs_read = [str(workspace / path) for path in build_files + product_files[:4] + board_files[:4] + soc_files[:4]]
    if meta_output and meta_output.exists():
        inputs_read.extend(
            str(meta_output / path)
            for path in [
                "02_patterns/meta_methods.jsonl",
                "02_patterns/conditional_methods.jsonl",
                "meta_skill_pack/references/conditional_method_index.md",
                "meta_report.md",
            ]
            if (meta_output / path).exists()
        )
    if target_seed_path:
        inputs_read.append(str(target_seed_path))
    if build_log_path:
        inputs_read.append(str(build_log_path))

    non_blocking = []
    if not target_seed_path:
        non_blocking.append("PORTING_EXECUTION_TARGET_PROFILE_SEED is empty; target identity remains unknown.")
    elif not target_product_paths:
        non_blocking.append(f"Target profile seed is supplied, but target product `{target['product']}` is not visible in the current source tree.")
    if not source_stage_files:
        non_blocking.append("PORTING_EXECUTION_SOURCE_OUTPUT lacks compact Stage 00-07 artifacts; evidence depth is limited.")
    if not build_log_path:
        non_blocking.append("PORTING_EXECUTION_BUILD_LOG is empty; build triage remains unknown.")

    result = {
        "stage": STAGE,
        "status": "partial" if non_blocking else "passed",
        "summary": "Deterministic plan-only execution package generated; target profile seed was consumed and target source visibility/build acceptance were kept separate.",
        "execution_mode": args.execution_mode,
        "patch_apply_mode": args.patch_apply_mode,
        "artifact_root": str(artifact_root),
        "input_files_read": inputs_read,
        "output_files_written": output_files,
        "blocking_issues": [],
        "non_blocking_issues": non_blocking,
        "next_stage_inputs": output_files,
        "patch_plan_item_count": len(patch_plan["patches"]),
        "external_dependency_followup_count": len(external_items),
        "uncertainty_count": len(uncertainty_ledger["items"]),
    }
    stage_result.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"event": "complete", "stage": STAGE, "time": now(), "outputs": len(output_files)}))


if __name__ == "__main__":
    main()
