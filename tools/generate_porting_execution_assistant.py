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
import hashlib
import json
import os
from pathlib import Path
from typing import Any

import yaml


STAGE = "10_porting_execution_assistant"

REQUIRED_FILES = [
    "target_profile.yaml",
    "meta_knowledge_digest.yaml",
    "meta_knowledge_digest.md",
    "target_source_evidence.yaml",
    "target_source_evidence.md",
    "source_import_plan.yaml",
    "source_import_plan.md",
    "implementation_readiness.yaml",
    "implementation_readiness.md",
    "source_file_blueprint.yaml",
    "source_file_blueprint.md",
    "source_candidate_manifest.yaml",
    "source_candidate_manifest.md",
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
    "target_dependency_inventory.yaml",
    "target_dependency_inventory.md",
    "porting_completion_summary.md",
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


def read_jsonl_records(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    if not path.is_file():
        return records
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            data = json.loads(line)
        except Exception:
            continue
        if isinstance(data, dict):
            records.append(data)
    return records


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


def string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, (tuple, set)):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value).strip()
    return [text] if text else []


def unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(item for item in values if item))


def record_text(record: dict[str, Any]) -> str:
    return json.dumps(record, ensure_ascii=False, sort_keys=True).lower()


def case_evidence_ref(record: dict[str, Any]) -> str:
    ref = clean_str(record.get("evidence_ref"), "")
    if ref:
        return ref
    scenario_id = clean_str(record.get("scenario_id"), "unknown")
    case_id = clean_str(record.get("case_id"), "unknown")
    return f"case:{scenario_id}::{case_id}"


def case_repo_paths(record: dict[str, Any], limit: int = 8) -> list[str]:
    evidence = record.get("evidence")
    if not isinstance(evidence, dict):
        return []
    paths: list[str] = []
    for commit in evidence.get("commits") or []:
        if isinstance(commit, dict):
            path = clean_str(commit.get("repo_path"), "")
            if path:
                paths.append(path)
    for asset in evidence.get("binary_assets") or []:
        if isinstance(asset, dict):
            path = clean_str(asset.get("path") or asset.get("repo_path"), "")
            if path:
                paths.append(path)
    return unique(paths)[:limit]


def classify_binary_asset(path: str) -> str:
    lowered = path.lower()
    if any(token in lowered for token in ["u-boot", "uboot", "miniloader", "opensbi", "loader/"]):
        return "bootloader"
    if (
        any(token in lowered for token in ["firmware", "fw_", "light_", "/boot/"])
        or lowered.endswith((".bin", ".hcd"))
    ):
        return "firmware"
    if lowered.endswith(".ko"):
        return "closed_driver"
    if lowered.endswith(".so"):
        return "prebuilt"
    if "/image_conf/" in lowered or lowered.endswith((".img", ".cfg", ".crt")):
        return "signing_packaging_tools"
    return "prebuilt"


TEXT_SOURCE_SUFFIXES = {
    ".build",
    ".c",
    ".cfg",
    ".gni",
    ".gn",
    ".h",
    ".hcs",
    ".json",
    ".md",
    ".para",
    ".patch",
    ".sh",
    ".txt",
    ".xml",
}

DEPENDENCY_SUFFIXES = {".a", ".bin", ".crt", ".hcb", ".hcd", ".img", ".ko", ".so"}


def sha256_file(path: Path) -> str:
    try:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()
    except Exception:
        return "unknown"


def read_text_preview(path: Path, max_chars: int = 12000) -> str:
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return ""
    if len(text) <= max_chars:
        return text.rstrip()
    return text[:max_chars].rstrip() + "\n# ... truncated; see target_source_evidence for the full source path ..."


def infer_target_source_role(rel_path: str) -> str:
    lowered = rel_path.lower()
    if lowered.startswith("productdefine/common/products/"):
        return "productdefine_config"
    if lowered.startswith("vendor/"):
        if "/image_conf/" in lowered:
            return "image_packaging_config"
        if "/hdf_config/" in lowered:
            return "hdf_config"
        if "/bluetooth/" in lowered:
            return "bluetooth_firmware_or_driver"
        return "vendor_product_config"
    if lowered.startswith("device/board/"):
        if "/loader/" in lowered:
            return "bootloader_packaging"
        if "/kernel/" in lowered:
            return "kernel_or_driver_payload"
        if "/audio_drivers/" in lowered:
            return "audio_driver"
        return "board_config"
    if lowered.startswith("device/soc/"):
        return "soc_config"
    return "other_target_source"


def target_source_root_candidates(root: Path, target: dict[str, str], seed: dict[str, Any]) -> list[str]:
    product = target.get("product", "unknown")
    board = target.get("board", "unknown")
    vendor = target.get("vendor", "unknown")
    soc = target.get("soc", "unknown")
    soc_vendor = clean_str(seed.get("soc_vendor"), vendor)
    candidates = [
        f"vendor/{vendor}/{product}",
        f"device/board/{vendor}/{board}",
        f"device/soc/{soc_vendor}/{soc}",
        f"productdefine/common/products/{product}.json",
    ]
    return [item for item in unique(candidates) if item and item != "unknown" and (root / item).exists()]


def iter_relevant_target_files(root: Path, roots: list[str], limit: int = 160, per_root_limit: int = 80) -> list[str]:
    files: list[str] = []
    for rel_root in roots:
        start = root / rel_root
        root_count = 0
        if start.is_file():
            files.append(rel(start, root))
        elif start.is_dir():
            for dirpath, dirnames, filenames in os.walk(start):
                dirnames[:] = sorted(name for name in dirnames if name not in {".git", ".repo", "out"})
                for filename in sorted(filenames):
                    files.append(rel(Path(dirpath) / filename, root))
                    root_count += 1
                    if len(files) >= limit:
                        return unique(files)
                    if root_count >= per_root_limit:
                        break
                if root_count >= per_root_limit:
                    break
        if len(files) >= limit:
            break
    return unique(files)[:limit]


def is_text_source_candidate(path: str) -> bool:
    lowered = path.lower()
    suffix = Path(path).suffix.lower()
    return suffix in TEXT_SOURCE_SUFFIXES or lowered.endswith("ohos.build")


def is_dependency_asset_candidate(path: str) -> bool:
    lowered = path.lower()
    suffix = Path(path).suffix.lower()
    if suffix in DEPENDENCY_SUFFIXES:
        return True
    if "/loader/" in lowered and suffix in {".cfg", ".txt"}:
        return True
    if "/image_conf/" in lowered and suffix == ".txt":
        return True
    return False


def scan_target_source_root(
    root: Path | None,
    target: dict[str, str],
    seed: dict[str, Any],
) -> dict[str, Any]:
    artifact = artifact_base("target_source_evidence")
    artifact.update(
        {
            "target": target,
            "target_source_root": str(root) if root else "unknown",
            "scan_status": "not_supplied",
            "visibility": "unknown",
            "expected_path_count": 0,
            "found_path_count": 0,
            "binary_asset_count": 0,
            "items": [],
            "binary_assets": [],
            "coverage_note": "No target source root was supplied, so this artifact has no external source evidence.",
        }
    )
    if not root:
        return artifact
    if not root.exists() or not root.is_dir():
        artifact["scan_status"] = "missing"
        artifact["coverage_note"] = "The supplied target source root does not exist or is not a directory."
        return artifact

    product = target.get("product", "unknown")
    board = target.get("board", "unknown")
    vendor = target.get("vendor", "unknown")
    soc = target.get("soc", "unknown")
    soc_vendor = clean_str(seed.get("soc_vendor"), vendor)
    expected_paths = [
        ("productdefine_config", f"productdefine/common/products/{product}.json", "file"),
        ("vendor_product_config", f"vendor/{vendor}/{product}/config.json", "file"),
        ("vendor_build_manifest", f"vendor/{vendor}/{product}/ohos.build", "file"),
        ("vendor_product_gni", f"vendor/{vendor}/{product}/product.gni", "file"),
        ("vendor_product_dir", f"vendor/{vendor}/{product}", "directory"),
        ("board_config_gni", f"device/board/{vendor}/{board}/config.gni", "file"),
        ("board_device_gni", f"device/board/{vendor}/{board}/device.gni", "file"),
        ("board_build_manifest", f"device/board/{vendor}/{board}/ohos.build", "file"),
        ("board_dir", f"device/board/{vendor}/{board}", "directory"),
        ("board_kernel_defconfig", f"device/board/{vendor}/{board}/kernel/{board}_defconfig", "file"),
        ("board_kernel_build_script", f"device/board/{vendor}/{board}/kernel/build_kernel.sh", "file"),
        ("soc_config_gni", f"device/soc/{soc_vendor}/{soc}/soc.gni", "file"),
        ("soc_dir", f"device/soc/{soc_vendor}/{soc}", "directory"),
    ]
    visibility = target_visibility(root, target, seed)
    roots = target_source_root_candidates(root, target, seed)
    all_relevant_files = iter_relevant_target_files(root, roots, limit=180, per_root_limit=70)
    dependency_relevant_files = iter_relevant_target_files(root, roots, limit=1200, per_root_limit=500)
    sample_source_files = [item for item in all_relevant_files if is_text_source_candidate(item)][:60]
    dependency_files = [item for item in dependency_relevant_files if is_dependency_asset_candidate(item)][:80]

    items: list[dict[str, Any]] = []
    seen_item_paths: set[str] = set()
    for role, rel_path, expected_kind in expected_paths:
        if "unknown" in rel_path:
            continue
        full_path = root / rel_path
        status = "found" if full_path.exists() else "missing"
        record: dict[str, Any] = {
            "evidence_id": f"TSE-{len(items) + 1:03d}",
            "kind": f"expected_{expected_kind}",
            "role": role,
            "path": rel_path,
            "status": status,
            "evidence_refs": [f"source_file:{rel_path}"] if status == "found" and full_path.is_file() else [f"source_tree:{root}"],
        }
        if full_path.exists():
            record["absolute_path"] = str(full_path)
            if full_path.is_file():
                record["size_bytes"] = full_path.stat().st_size
                record["sha256"] = sha256_file(full_path)
            elif full_path.is_dir():
                record["direct_child_count"] = len(list(full_path.iterdir()))
        items.append(record)
        seen_item_paths.add(rel_path)

    for rel_path in sample_source_files:
        if rel_path in seen_item_paths:
            continue
        full_path = root / rel_path
        items.append(
            {
                "evidence_id": f"TSE-{len(items) + 1:03d}",
                "kind": "sample_source_file",
                "role": infer_target_source_role(rel_path),
                "path": rel_path,
                "status": "found",
                "absolute_path": str(full_path),
                "size_bytes": full_path.stat().st_size,
                "sha256": sha256_file(full_path),
                "evidence_refs": [f"source_file:{rel_path}", f"source_tree:{root}"],
            }
        )
        seen_item_paths.add(rel_path)
        if len(items) >= 80:
            break

    binary_assets: list[dict[str, Any]] = []
    for rel_path in dependency_files:
        full_path = root / rel_path
        if not full_path.is_file():
            continue
        binary_assets.append(
            {
                "asset_id": f"TSA-{len(binary_assets) + 1:03d}",
                "category": classify_binary_asset(rel_path),
                "path": rel_path,
                "absolute_path": str(full_path),
                "sha256": sha256_file(full_path),
                "size_bytes": full_path.stat().st_size,
                "relation": "target_source_dependency_candidate",
                "role": infer_target_source_role(rel_path),
                "risk": "Target source root evidence identifies this dependency candidate, but provenance, license, redistribution, regeneration, and board validation still require review.",
                "next_action": "Confirm ownership, license, source/regeneration route, runtime usage, and validation logs before integrating or declaring completion.",
                "evidence_refs": [f"source_file:{rel_path}", f"source_tree:{root}"],
            }
        )

    found_count = sum(1 for _, rel_path, _ in expected_paths if "unknown" not in rel_path and (root / rel_path).exists())
    artifact.update(
        {
            "scan_status": "loaded",
            "visibility": visibility,
            "expected_path_count": len([item for item in expected_paths if "unknown" not in item[1]]),
            "found_path_count": found_count,
            "binary_asset_count": len(binary_assets),
            "items": items,
            "binary_assets": binary_assets,
            "coverage_note": "The scan is bounded to target-relevant product, board, and SoC paths. It records evidence only and does not copy files into the current workspace.",
        }
    )
    return artifact


def infer_import_class(path: str, role: str) -> str:
    lowered = path.lower()
    if role in {"productdefine_config", "vendor_product_config", "vendor_product_gni"}:
        return "product_config"
    if role in {"vendor_build_manifest", "board_build_manifest"} or lowered.endswith("ohos.build"):
        return "build_manifest"
    if role in {"board_config_gni", "board_device_gni", "board_config"}:
        return "board_config"
    if role in {"soc_config_gni", "soc_config"}:
        return "soc_config"
    if "kernel" in role or "/kernel/" in lowered:
        return "kernel_build_config"
    if role == "hdf_config" or "/hdf_config/" in lowered:
        return "hdf_config"
    if role == "audio_driver" or "/audio_drivers/" in lowered:
        return "driver_source"
    if "/bluetooth/" in lowered and lowered.endswith((".c", ".h", ".gn")):
        return "driver_source"
    if lowered.endswith((".json", ".xml", ".para", ".gni", ".gn", ".cfg", ".txt")):
        return "product_runtime_config"
    return "other_source_file"


def source_import_exclusion_reason(path: str, role: str) -> str:
    lowered = path.lower()
    if is_dependency_asset_candidate(path):
        return "dependency_asset_candidate"
    if "/loader/" in lowered:
        return "bootloader_or_partition_packaging_dependency"
    if "/kernel/boot/" in lowered or "/kernel/ko/" in lowered:
        return "kernel_binary_or_module_dependency"
    if "/hardware/firmware/" in lowered or "/hardware/g2d/" in lowered or "/hardware/gpu/" in lowered:
        return "firmware_or_prebuilt_dependency"
    if "/image_conf/" in lowered:
        return "image_packaging_dependency"
    if lowered.endswith(".patch"):
        return "patch_artifact_requires_separate_diff_review"
    if role in {"bootloader_packaging", "image_packaging_config"}:
        return "external_packaging_or_boot_dependency"
    return ""


def current_workspace_file_status(workspace: Path, target_path: str, source_sha: str) -> dict[str, str]:
    path = workspace / target_path
    if not path.exists():
        return {"status": "missing", "sha256": "unknown"}
    if path.is_dir():
        return {"status": "present_directory", "sha256": "unknown"}
    if not path.is_file():
        return {"status": "present_non_file", "sha256": "unknown"}
    current_sha = sha256_file(path)
    if current_sha != "unknown" and source_sha != "unknown" and current_sha == source_sha:
        status = "present_same_hash"
    else:
        status = "present_different_or_unverified"
    return {"status": status, "sha256": current_sha}


def build_source_import_plan(
    workspace: Path,
    target_source_root: Path | None,
    target_source_evidence: dict[str, Any],
    target: dict[str, str],
    target_seed_ref: str,
    target_source_ref: str,
    scope_method: str,
    riscv_method: str,
    binary_method: str,
) -> dict[str, Any]:
    plan = artifact_base("source_import_plan")
    scan_status = clean_str(target_source_evidence.get("scan_status"), "unknown")
    source_items = target_source_evidence.get("items")
    if not isinstance(source_items, list):
        source_items = []
    binary_assets = target_source_evidence.get("binary_assets")
    if not isinstance(binary_assets, list):
        binary_assets = []
    binary_paths = {
        clean_str(asset.get("path"), "")
        for asset in binary_assets
        if isinstance(asset, dict) and clean_str(asset.get("path"), "")
    }

    import_items: list[dict[str, Any]] = []
    excluded_items: list[dict[str, Any]] = []
    seen_import_paths: set[str] = set()

    for item in source_items:
        if not isinstance(item, dict):
            continue
        path = clean_str(item.get("path"), "")
        if not path or path in seen_import_paths:
            continue
        role = clean_str(item.get("role"), "unknown")
        status = clean_str(item.get("status"), "unknown")
        kind = clean_str(item.get("kind"), "unknown")
        evidence_refs = unique(string_list(item.get("evidence_refs")) + [target_seed_ref, target_source_ref])
        if kind == "expected_directory":
            continue
        if status == "missing":
            current = current_workspace_file_status(workspace, path, "unknown")
            import_items.append(
                {
                    "import_id": f"IMP-{len(import_items) + 1:03d}",
                    "import_class": infer_import_class(path, role),
                    "source_role": role,
                    "source_path": "unknown",
                    "target_path": path,
                    "target_workspace_path": str(workspace / path),
                    "source_status": "missing_in_target_source_root",
                    "current_workspace_status": current["status"],
                    "source_sha256": "unknown",
                    "current_sha256": current["sha256"],
                    "import_decision": "cannot_import_missing_target_source",
                    "write_policy": "do_not_write_to_workspace",
                    "apply_gate": "Supply target-source evidence or a reviewed product definition before this path can enter an import queue.",
                    "next_action": "Create or locate the missing target source file from authoritative product evidence.",
                    "evidence_refs": evidence_refs,
                }
            )
            seen_import_paths.add(path)
            continue

        exclusion_reason = source_import_exclusion_reason(path, role)
        if path in binary_paths or exclusion_reason:
            excluded_items.append(
                {
                    "excluded_id": f"EXCL-{len(excluded_items) + 1:03d}",
                    "path": path,
                    "category": classify_binary_asset(path) if path in binary_paths or is_dependency_asset_candidate(path) else "external_dependency",
                    "reason": exclusion_reason or "listed_as_target_source_dependency_asset",
                    "routed_to": "target_dependency_inventory",
                    "evidence_refs": unique(evidence_refs + [f"meta_method:{binary_method}"]),
                }
            )
            seen_import_paths.add(path)
            continue

        if status != "found" or not is_text_source_candidate(path):
            continue

        source_sha = clean_str(item.get("sha256"), "unknown")
        current = current_workspace_file_status(workspace, path, source_sha)
        if current["status"] == "missing":
            decision = "manual_import_candidate"
            next_action = "Review source ownership and version compatibility, then import through a controlled patch or copy step."
        elif current["status"] == "present_same_hash":
            decision = "already_present_same_hash"
            next_action = "No source import needed for this file; keep it as evidence."
        else:
            decision = "compare_before_import"
            next_action = "Diff current workspace file against target source evidence before deciding whether to replace, merge, or skip."

        import_items.append(
            {
                "import_id": f"IMP-{len(import_items) + 1:03d}",
                "import_class": infer_import_class(path, role),
                "source_role": role,
                "source_path": path,
                "target_path": path,
                "target_workspace_path": str(workspace / path),
                "source_status": "found_in_target_source_root",
                "current_workspace_status": current["status"],
                "source_sha256": source_sha,
                "current_sha256": current["sha256"],
                "import_decision": decision,
                "write_policy": "do_not_write_to_workspace",
                "apply_gate": "Manual review must confirm OpenHarmony version compatibility, ownership, file role, and absence of binary payload before any workspace write.",
                "next_action": next_action,
                "evidence_refs": unique(evidence_refs + [f"meta_method:{scope_method}", f"meta_method:{riscv_method}"]),
            }
        )
        seen_import_paths.add(path)

    for asset in binary_assets:
        if not isinstance(asset, dict):
            continue
        path = clean_str(asset.get("path"), "")
        if not path or path in seen_import_paths:
            continue
        excluded_items.append(
            {
                "excluded_id": f"EXCL-{len(excluded_items) + 1:03d}",
                "path": path,
                "category": clean_str(asset.get("category"), classify_binary_asset(path)),
                "reason": "target_source_dependency_asset",
                "routed_to": "target_dependency_inventory",
                "evidence_refs": unique(string_list(asset.get("evidence_refs")) + [target_source_ref, f"meta_method:{binary_method}"]),
            }
        )
        seen_import_paths.add(path)

    decision_counts: dict[str, int] = {}
    for item in import_items:
        decision = clean_str(item.get("import_decision"), "unknown")
        decision_counts[decision] = decision_counts.get(decision, 0) + 1

    plan.update(
        {
            "target": target,
            "target_source_root": str(target_source_root) if target_source_root else "unknown",
            "scan_status": scan_status,
            "default_write_policy": "do_not_write_to_workspace",
            "import_policy": "manual_review_only",
            "item_count": len(import_items),
            "excluded_dependency_count": len(excluded_items),
            "decision_counts": decision_counts,
            "items": import_items,
            "excluded_items": excluded_items,
            "coverage_note": "This import plan converts read-only target-source evidence into a review queue. It does not copy files, generate patch hunks, or include binary/firmware/prebuilt payloads as source imports.",
        }
    )
    return plan


def case_binary_assets(record: dict[str, Any], limit: int = 20) -> list[dict[str, str]]:
    evidence = record.get("evidence")
    if not isinstance(evidence, dict):
        return []
    assets: list[dict[str, str]] = []
    for asset in evidence.get("binary_assets") or []:
        if not isinstance(asset, dict):
            continue
        path = clean_str(asset.get("path"), "")
        if not path:
            continue
        assets.append(
            {
                "path": path,
                "category": classify_binary_asset(path),
                "relation": clean_str(asset.get("relation"), "unknown"),
                "sha256": clean_str(asset.get("sha256"), "unknown"),
            }
        )
        if len(assets) >= limit:
            break
    return assets


def load_meta_knowledge(meta_output: Path | None, target: dict[str, str], seed: dict[str, Any]) -> dict[str, Any]:
    digest = artifact_base("meta_knowledge_digest")
    scenario_types = string_list(seed.get("scenario_type"))
    target_terms = unique(
        [
            target.get("product", ""),
            target.get("board", ""),
            target.get("soc", ""),
            target.get("vendor", ""),
            target.get("architecture", ""),
            clean_str(seed.get("soc_vendor"), ""),
            "riscv" if "riscv" in target.get("architecture", "").lower() else "",
        ]
    )
    target_terms = [term.lower() for term in target_terms if term and term != "unknown"]
    identity_priority_terms = [
        term
        for term in [
            clean_str(target.get("product"), ""),
            clean_str(target.get("board"), ""),
            clean_str(target.get("soc"), ""),
            clean_str(target.get("vendor"), ""),
            clean_str(seed.get("soc_vendor"), ""),
        ]
        if term and term != "unknown"
    ]
    identity_priority_terms = [term.lower() for term in unique(identity_priority_terms)]
    preferred_method_ids = {
        "META-UNIVERSAL_BY_DESIGN_VALIDATION_SEPARATION",
        "META-UNIVERSAL_BY_DESIGN_EVIDENCE_CLASS_SEPARATION",
        "META-UNIVERSAL_BY_DESIGN_SCENARIO_SCOPE_AUTHORITY",
        "META-CONDITIONAL-RISCV-BUILD-RUNTIME-ROUTE",
        "META-CONDITIONAL-BOOT-FIRMWARE-PROVENANCE",
        "META-CONDITIONAL-BINARY-PREBUILT-PROVENANCE",
        "META-CONDITIONAL-DIRTY-WORKSPACE-GOVERNANCE",
    }
    deferred_method_ids = {
        "META-CONDITIONAL-HDF-DRIVER-MULTIREPO-CHAIN",
        "META-CONDITIONAL-WIFI-SDIO-RUNTIME-CHAIN",
        "META-CONDITIONAL-MEDIA-CAMERA-HDF-CHAIN",
    }
    digest.update(
        {
            "meta_output": str(meta_output) if meta_output else "unknown",
            "target_terms": target_terms,
            "target_scenario_types": scenario_types,
            "selected_methods": [],
            "deferred_methods": [],
            "selected_cases": [],
            "action_bias": [],
            "meta_status": "missing",
        }
    )
    if not meta_output or not meta_output.exists():
        return digest

    meta_methods = read_jsonl_records(meta_output / "02_patterns/meta_methods.jsonl")
    conditional_methods = read_jsonl_records(meta_output / "02_patterns/conditional_methods.jsonl")
    cases = read_jsonl_records(meta_output / "01_normalized_cases/cases.jsonl")
    digest["meta_status"] = "loaded"

    selected_methods: list[dict[str, Any]] = []
    deferred_methods: list[dict[str, Any]] = []
    seen_selected_method_ids: set[str] = set()
    seen_deferred_method_ids: set[str] = set()
    for record in meta_methods + conditional_methods:
        method_id = clean_str(record.get("method_id"), "")
        if not method_id:
            continue
        applicability = string_list(record.get("applicability"))
        method_text = record_text(record)
        scenario_match = bool(set(applicability) & set(scenario_types))
        target_match = any(term in method_text for term in target_terms)
        selected = method_id in preferred_method_ids or method_id.startswith("META-UNIVERSAL_BY_DESIGN") or scenario_match or target_match
        slim = {
            "method_id": method_id,
            "title": clean_str(record.get("title"), method_id),
            "promotion_level": clean_str(record.get("promotion_level")),
            "applicability": applicability,
            "evidence_strength": clean_str(record.get("evidence_strength")),
            "statement": clean_str(record.get("statement"), ""),
            "quality_gates": string_list(record.get("quality_gates"))[:5],
            "risks": string_list(record.get("risks"))[:5],
            "supporting_cases": string_list(record.get("supporting_cases"))[:8],
            "selection_reason": "preferred_target_route" if method_id in preferred_method_ids else ("scenario_or_target_match" if selected else "deferred_feature_scope"),
            "evidence_refs": [f"meta_method:{method_id}"],
        }
        if method_id in deferred_method_ids:
            if method_id not in seen_deferred_method_ids:
                deferred_methods.append(slim)
                seen_deferred_method_ids.add(method_id)
        elif selected:
            if method_id not in seen_selected_method_ids:
                selected_methods.append(slim)
                seen_selected_method_ids.add(method_id)

    scored_cases: list[tuple[int, dict[str, Any]]] = []
    for record in cases:
        text = record_text(record)
        identity_text = " ".join(
            str(record.get(key) or "")
            for key in ["case_id", "title", "scenario_id", "source_case_path"]
        ).lower()
        case_scenario_types = string_list(record.get("scenario_type"))
        non_applicability = string_list(record.get("non_applicability"))
        score = 0
        if set(case_scenario_types) & set(scenario_types):
            score += 5
        for term in identity_priority_terms:
            if term and term in identity_text:
                score += 8
        for term in target_terms:
            if term and term in text:
                score += 2
        if "riscv" in text and any("riscv" in item for item in scenario_types + target_terms):
            score += 2
        if "rvbook" in text:
            score += 2
        if set(non_applicability) & set(scenario_types):
            score -= 6
        if score <= 0:
            continue
        scored_cases.append((score, record))
    scored_cases.sort(key=lambda item: (-item[0], clean_str(item[1].get("case_id"))))

    selected_cases: list[dict[str, Any]] = []
    seen_cases: set[str] = set()
    for score, record in scored_cases:
        case_id = clean_str(record.get("case_id"), "")
        if not case_id or case_id in seen_cases:
            continue
        seen_cases.add(case_id)
        selected_cases.append(
            {
                "case_id": case_id,
                "title": clean_str(record.get("title"), case_id),
                "scenario_id": clean_str(record.get("scenario_id")),
                "scenario_type": string_list(record.get("scenario_type")),
                "subsystem": string_list(record.get("subsystem")),
                "porting_phase": string_list(record.get("porting_phase")),
                "problem_type": string_list(record.get("problem_type")),
                "reuse_level": clean_str(record.get("reuse_level")),
                "evidence_strength": clean_str(record.get("evidence_strength")),
                "rule": clean_str(record.get("rule"), ""),
                "repo_paths": case_repo_paths(record),
                "binary_assets": case_binary_assets(record),
                "source_case_path": clean_str(record.get("source_case_path"), ""),
                "score": score,
                "evidence_refs": [case_evidence_ref(record)],
            }
        )
        if len(selected_cases) >= 10:
            break

    selected_refs = [ref for item in selected_methods + selected_cases for ref in item.get("evidence_refs", [])]
    digest["selected_methods"] = selected_methods[:10]
    digest["deferred_methods"] = deferred_methods[:8]
    digest["selected_cases"] = selected_cases
    digest["action_bias"] = [
        {
            "action_id": "META-ACTION-001",
            "area": "product_board_binding",
            "recommendation": "Prioritize product/vendor, board, and SoC binding before feature-specific HDF or runtime service work.",
            "evidence_refs": unique(selected_refs + ["meta_method:META-UNIVERSAL_BY_DESIGN_SCENARIO_SCOPE_AUTHORITY"])[:8],
        },
        {
            "action_id": "META-ACTION-002",
            "area": "riscv_build_runtime",
            "recommendation": "Treat build target routing, Rust/NDK pathing, musl runtime behavior, and RISC-V architecture flags as a connected route.",
            "evidence_refs": unique(selected_refs + ["meta_method:META-CONDITIONAL-RISCV-BUILD-RUNTIME-ROUTE"])[:8],
        },
        {
            "action_id": "META-ACTION-003",
            "area": "external_dependency_governance",
            "recommendation": "Inventory BSP, bootloader, firmware, prebuilts, closed drivers, and signing or packaging tools before promoting binary-dependent work as source implementation.",
            "evidence_refs": unique(selected_refs + ["meta_method:META-CONDITIONAL-BINARY-PREBUILT-PROVENANCE"])[:8],
        },
    ]
    return digest


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
    parser.add_argument("--target-source-root", default="")
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
    target_source_root = Path(args.target_source_root).resolve() if args.target_source_root else None
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
    target_source_ref = f"source_tree:{target_source_root}" if target_source_root else "source_tree:target_source_root_not_supplied"

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
    target_source_evidence = scan_target_source_root(target_source_root, target, target_seed)
    target_source_visibility = (
        target_source_evidence.get("visibility")
        if isinstance(target_source_evidence.get("visibility"), dict)
        else {}
    )
    target_source_items = target_source_evidence.get("items", []) if isinstance(target_source_evidence.get("items"), list) else []
    target_source_binary_assets = (
        target_source_evidence.get("binary_assets", [])
        if isinstance(target_source_evidence.get("binary_assets"), list)
        else []
    )
    target_source_loaded = target_source_evidence.get("scan_status") == "loaded"
    target_source_file_refs = {
        clean_str(item.get("path"), ""): f"source_file:{clean_str(item.get('path'), '')}"
        for item in target_source_items
        if isinstance(item, dict)
        and item.get("status") == "found"
        and clean_str(item.get("path"), "")
        and str(item.get("kind") or "").endswith("file")
    }
    meta_knowledge_digest = load_meta_knowledge(meta_output, target, target_seed)
    selected_method_ids = [item["method_id"] for item in meta_knowledge_digest.get("selected_methods", [])]
    selected_case_ids = [item["case_id"] for item in meta_knowledge_digest.get("selected_cases", [])]
    selected_case_refs = [
        ref
        for item in meta_knowledge_digest.get("selected_cases", [])
        for ref in item.get("evidence_refs", [])
    ]
    product_case_refs = [
        ref
        for item in meta_knowledge_digest.get("selected_cases", [])
        if any("product" in value or "board" in value or "soc" in value for value in item.get("subsystem", []) + item.get("porting_phase", []))
        for ref in item.get("evidence_refs", [])
    ]
    riscv_case_refs = [
        ref
        for item in meta_knowledge_digest.get("selected_cases", [])
        if any("riscv" in value for value in item.get("subsystem", []) + item.get("problem_type", []) + item.get("scenario_type", []))
        for ref in item.get("evidence_refs", [])
    ]
    source_import_plan = build_source_import_plan(
        workspace,
        target_source_root,
        target_source_evidence,
        target,
        target_seed_ref,
        target_source_ref,
        scope_method,
        riscv_method,
        binary_method,
    )

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
                "target_source_root": str(target_source_root) if target_source_root else "unknown",
                "build_log": str(build_log_path) if build_log_path else "unknown",
                "detected_source_product_candidate": detected_product,
                "target_source_visibility": visibility if visibility else "unknown",
                "external_target_source_evidence": {
                    "status": target_source_evidence.get("scan_status", "unknown"),
                    "root": str(target_source_root) if target_source_root else "unknown",
                    "expected_path_count": target_source_evidence.get("expected_path_count", 0),
                    "found_path_count": target_source_evidence.get("found_path_count", 0),
                    "binary_asset_count": target_source_evidence.get("binary_asset_count", 0),
                },
                "source_import_plan": {
                    "status": source_import_plan.get("scan_status", "unknown"),
                    "item_count": source_import_plan.get("item_count", 0),
                    "excluded_dependency_count": source_import_plan.get("excluded_dependency_count", 0),
                    "import_policy": source_import_plan.get("import_policy", "unknown"),
                },
                "meta_knowledge_digest": {
                    "status": meta_knowledge_digest.get("meta_status", "unknown"),
                    "selected_method_count": len(meta_knowledge_digest.get("selected_methods", [])),
                    "selected_case_count": len(meta_knowledge_digest.get("selected_cases", [])),
                },
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
                {
                    "requirement_id": "REQ-004",
                    "description": "Use cross-scenario meta methods and matching cases as execution guidance, while keeping selected cases conditional and evidence-bound.",
                    "source": "meta_output" if meta_knowledge_digest.get("meta_status") == "loaded" else "unknown",
                    "evidence_refs": (selected_case_refs[:3] or [f"meta_method:{scope_method}", target_seed_ref]),
                },
                {
                    "requirement_id": "REQ-005",
                    "description": "If a target reference source tree is supplied, use it as read-only evidence for product, board, SoC, kernel, boot, firmware, prebuilt, and packaging dependency discovery; do not copy or apply files automatically.",
                    "source": "source_tree" if target_source_loaded else "unknown",
                    "evidence_refs": unique([target_source_ref, target_seed_ref, f"meta_method:{evidence_method}", f"meta_method:{binary_method}"]),
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
    external_product_paths = target_source_visibility.get("product_found", []) if target_source_visibility else []
    external_board_paths = target_source_visibility.get("board_found", []) if target_source_visibility else []
    external_soc_paths = target_source_visibility.get("soc_found", []) if target_source_visibility else []
    external_kernel_paths = [
        clean_str(item.get("path"), "")
        for item in target_source_items
        if isinstance(item, dict)
        and item.get("status") == "found"
        and "kernel" in clean_str(item.get("role"), "")
    ][:12]
    external_found_paths = unique(external_product_paths + external_board_paths + external_soc_paths + external_kernel_paths)

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
        {
            "survey_id": "SURVEY-008",
            "topic": "other",
            "status": "found" if meta_knowledge_digest.get("meta_status") == "loaded" else "unknown",
            "paths": [
                str(meta_output / rel_path)
                for rel_path in [
                    "02_patterns/meta_methods.jsonl",
                    "02_patterns/conditional_methods.jsonl",
                    "01_normalized_cases/cases.jsonl",
                ]
                if meta_output and (meta_output / rel_path).exists()
            ],
            "observation": f"Meta selector loaded {len(selected_method_ids)} method(s) and {len(selected_case_ids)} target-relevant case(s) for `{target['product']}`/`{target['soc']}` execution planning.",
            "evidence_refs": (selected_case_refs[:3] or [f"meta_method:{scope_method}", target_seed_ref]),
        },
        {
            "survey_id": "SURVEY-009",
            "topic": "target_reference_source",
            "status": "found" if target_source_loaded else ("missing" if target_source_root else "unknown"),
            "paths": external_found_paths[:20],
            "observation": (
                f"Read-only target reference source scan status is `{target_source_evidence.get('scan_status')}`; "
                f"it found {target_source_evidence.get('found_path_count', 0)} of {target_source_evidence.get('expected_path_count', 0)} expected target paths "
                f"and {target_source_evidence.get('binary_asset_count', 0)} dependency candidate(s). These files are evidence only and have not been copied into the current workspace."
            ),
            "evidence_refs": unique([target_source_ref, target_seed_ref, f"meta_method:{evidence_method}", f"meta_method:{binary_method}"]),
        },
    ]
    source_tree_survey = artifact_base("source_tree_survey")
    source_tree_survey["items"] = survey_items

    gaps = [
        {
            "gap_id": "GAP-001",
            "area": "product_config",
            "severity": "blocker",
            "description": f"Target identity is supplied by seed as `{target['product']}`/`{target['board']}`/`{target['soc']}`/`{target['vendor']}`/`{target['architecture']}`. Current workspace product config is not visible; external target source evidence found {len(external_product_paths)} product path(s) that require controlled import/review.",
            "owner_hint": "source_patch",
            "evidence_refs": unique([target_seed_ref, workspace_ref, target_source_ref, f"meta_method:{scope_method}", f"meta_method:{riscv_method}"] + product_case_refs[:2]),
            "uncertainty_refs": ["UNC-001"],
        },
        {
            "gap_id": "GAP-002",
            "area": "board_config",
            "severity": "blocker",
            "description": f"Target board/SoC configuration paths for `{target['board']}` and `{target['soc']}` are not visible in the current workspace; external target source evidence found {len(external_board_paths)} board path(s) and {len(external_soc_paths)} SoC path(s) that require controlled import/review.",
            "owner_hint": "source_patch",
            "evidence_refs": unique([target_seed_ref, product_ref, target_source_ref, f"meta_method:{scope_method}", f"meta_method:{riscv_method}"] + product_case_refs[:2]),
            "uncertainty_refs": ["UNC-002"],
        },
        {
            "gap_id": "GAP-003",
            "area": "kernel",
            "severity": "high",
            "description": f"Target kernel branch, DTS, defconfig, and TH1520/RVBook kernel binding are not visible in the current workspace; external target source evidence found {len(external_kernel_paths)} kernel-related path(s), but provenance and build ownership still need review.",
            "owner_hint": "vendor_or_third_party",
            "evidence_refs": unique([target_seed_ref, workspace_ref, target_source_ref, f"meta_method:{riscv_method}", f"meta_method:{boot_method}"] + riscv_case_refs[:2]),
            "uncertainty_refs": ["UNC-003"],
        },
        {
            "gap_id": "GAP-004",
            "area": "build",
            "severity": "high",
            "description": f"The RISC-V `{target['architecture']}` build/product route cannot be accepted until `{target['product']}` is product-visible; source-output absence limits evidence depth but is not the product-visibility blocker.",
            "owner_hint": "source_patch",
            "evidence_refs": unique([target_seed_ref, build_ref, f"meta_method:{riscv_method}", f"meta_method:{validation_method}"] + riscv_case_refs[:2]),
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
            "description": f"Firmware, prebuilts, closed drivers, and signing/packaging tools for `{target['product']}` have {len(target_source_binary_assets)} target-source candidate(s) with path/hash, but provenance, license, redistribution, regeneration, and validation status remain open.",
            "owner_hint": "vendor_or_third_party",
            "evidence_refs": [target_seed_ref, workspace_ref, target_source_ref, f"meta_method:{binary_method}"],
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
                "selected_cases": selected_case_ids,
                "selected_meta_methods": selected_method_ids
                or [
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
                "selection_note": f"The target is RISC-V primary by seed, so the RISC-V build/runtime/product route is selected. Meta digest selected {len(selected_case_ids)} target-relevant case(s). Feature-specific HDF/WiFi/media methods are deferred until target product, board, SoC, and feature evidence are visible.",
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
                    "rationale": f"P0 may plan product visibility work for `{target['product']}`, but must not generate a diff until productdefine/vendor ownership and target source evidence are confirmed. The selected meta cases make this a binding-layer task, not a standalone product file guess.",
                    "evidence_refs": unique([target_seed_ref, product_ref, f"meta_method:{scope_method}", f"meta_method:{riscv_method}"] + product_case_refs[:3]),
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
                    "evidence_refs": unique([target_seed_ref, product_ref, f"meta_method:{riscv_method}", f"meta_method:{boot_method}"] + product_case_refs[:2] + riscv_case_refs[:2]),
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
                    "evidence_refs": unique([target_seed_ref, workspace_ref, f"meta_method:{binary_method}", f"meta_method:{boot_method}"] + selected_case_refs[:2]),
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
            "evidence_refs": unique([target_seed_ref, workspace_ref, f"meta_method:{riscv_method}", f"meta_method:{binary_method}"] + product_case_refs[:2]),
        },
        {
            "dependency_id": "DEP-002",
            "category": "bootloader",
            "why_needed": f"OpenSBI/U-Boot/bootloader requirements, partition flow, and board boot evidence for `{target['board']}` are not present in the inputs.",
            "next_action": "Collect OpenSBI, U-Boot, bootloader source or release notes, partition layout, and board boot logs before integration.",
            "evidence_refs": unique([target_seed_ref, workspace_ref, f"meta_method:{boot_method}", f"meta_method:{validation_method}"] + selected_case_refs[:2]),
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
            "evidence_refs": unique([target_seed_ref, workspace_ref, f"meta_method:{riscv_method}", f"meta_method:{binary_method}"] + riscv_case_refs[:2]),
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
    external_dependency_followup.update(
        {
            "target_dependency_summary": {
                "product": target["product"],
                "board": target["board"],
                "soc": target["soc"],
                "soc_vendor": clean_str(target_seed.get("soc_vendor")),
                "board_vendor": target["vendor"],
                "architecture": target["architecture"],
                "summary": "Vendor/BSP and binary-dependent work is reportable now, but implementation remains blocked until target product/board/SoC source visibility and provenance evidence exist.",
                "evidence_refs": unique([target_seed_ref, f"meta_method:{binary_method}", f"meta_method:{boot_method}"] + selected_case_refs[:4]),
            },
            "coverage": coverage,
            "items": external_items,
        }
    )

    inventory_items: list[dict[str, Any]] = []
    seen_assets: set[str] = set()
    for case in meta_knowledge_digest.get("selected_cases", []):
        case_id = clean_str(case.get("case_id"), "unknown")
        case_title = clean_str(case.get("title"), case_id)
        case_refs = string_list(case.get("evidence_refs"))
        for asset in case.get("binary_assets", []):
            if not isinstance(asset, dict):
                continue
            path = clean_str(asset.get("path"), "")
            if not path or path in seen_assets:
                continue
            seen_assets.add(path)
            category = clean_str(asset.get("category"), classify_binary_asset(path))
            inventory_items.append(
                {
                    "asset_id": f"ASSET-{len(inventory_items) + 1:03d}",
                    "category": category,
                    "path": path,
                    "sha256": clean_str(asset.get("sha256"), "unknown"),
                    "relation": clean_str(asset.get("relation"), "unknown"),
                    "source_case_id": case_id,
                    "source_case_title": case_title,
                    "target_relevance": "target_case_match" if "rvbook" in case_id.lower() or "rvbook" in path.lower() else "conditional_case_match",
                    "risk": "binary provenance, license, redistribution, and regeneration route must be confirmed before implementation completion.",
                    "next_action": "Confirm ownership, license, source/regeneration route, runtime usage, and board validation logs for this asset.",
                    "evidence_refs": unique(case_refs + [f"meta_method:{binary_method}", f"meta_method:{boot_method}"]),
                }
            )
    for asset in target_source_binary_assets:
        if not isinstance(asset, dict):
            continue
        path = clean_str(asset.get("path"), "")
        if not path or path in seen_assets or f"target_source:{path}" in seen_assets:
            continue
        seen_assets.add(f"target_source:{path}")
        inventory_items.append(
            {
                "asset_id": f"ASSET-{len(inventory_items) + 1:03d}",
                "category": clean_str(asset.get("category"), classify_binary_asset(path)),
                "path": path,
                "sha256": clean_str(asset.get("sha256"), "unknown"),
                "relation": clean_str(asset.get("relation"), "target_source_dependency_candidate"),
                "source_case_id": "target_source_root",
                "source_case_title": "Read-only target source root evidence",
                "target_relevance": "target_source_match",
                "risk": clean_str(asset.get("risk"), "binary provenance, license, redistribution, and regeneration route must be confirmed before implementation completion."),
                "next_action": clean_str(asset.get("next_action"), "Confirm ownership, license, source/regeneration route, runtime usage, and board validation logs for this asset."),
                "evidence_refs": unique(string_list(asset.get("evidence_refs")) + [target_source_ref, f"meta_method:{binary_method}", f"meta_method:{boot_method}"]),
            }
        )
    target_dependency_inventory = artifact_base("target_dependency_inventory")
    target_dependency_inventory.update(
        {
            "target": target,
            "inventory_source": "selected_meta_cases_and_target_source_root" if target_source_loaded else "selected_meta_cases",
            "asset_count": len(inventory_items),
            "items": inventory_items,
            "coverage_note": "This inventory combines selected meta-case assets with read-only target-source dependency candidates when supplied. It does not prove assets are present in or redistributable from the current workspace.",
        }
    )

    implementation_items = [
        {
            "item_id": "IMPL-001",
            "area": "product_config",
            "implementation_class": "source_compile_file",
            "target_paths": [
                f"productdefine/common/products/{target['product']}.json",
                f"vendor/{target['vendor']}/{target['product']}/config.json",
                f"vendor/{target['vendor']}/{target['product']}/ohos.build",
            ],
            "current_status": "missing_in_workspace" if not target_product_paths else "visible_in_workspace",
            "execution_decision": "plan_ready_not_applied" if not target_product_paths else "ready_for_build_triage",
            "why_not_completed": "" if target_product_paths else f"The target product is seed-confirmed but not visible in the current workspace; external target source evidence has {len(external_product_paths)} product path(s) that still need controlled import/review.",
            "next_action": "Review target source product/vendor configuration, then import or generate controlled workspace changes before build-only triage.",
            "evidence_refs": unique([target_seed_ref, product_ref, target_source_ref, f"meta_method:{scope_method}", f"meta_method:{riscv_method}"] + product_case_refs[:3]),
        },
        {
            "item_id": "IMPL-002",
            "area": "board_soc_config",
            "implementation_class": "source_compile_file",
            "target_paths": [
                f"device/board/{target['vendor']}/{target['board']}/config.gni",
                f"device/board/{target['vendor']}/{target['board']}/device.gni",
                f"device/soc/{clean_str(target_seed.get('soc_vendor'), target['vendor'])}/{target['soc']}/soc.gni",
            ],
            "current_status": "missing_in_workspace" if not (target_board_paths or target_soc_paths) else "partially_visible",
            "execution_decision": "manual_review_required",
            "why_not_completed": f"Board, SoC, DTS, defconfig, and kernel binding are not visible in the current workspace; target source evidence has {len(external_board_paths)} board path(s), {len(external_soc_paths)} SoC path(s), and {len(external_kernel_paths)} kernel-related path(s) for review.",
            "next_action": "Review RVBook/TH1520 board and SoC source configuration, then split safe compile-file imports from kernel/BSP payloads.",
            "evidence_refs": unique([target_seed_ref, target_source_ref, f"meta_method:{scope_method}", f"meta_method:{riscv_method}", f"meta_method:{boot_method}"] + product_case_refs[:3]),
        },
        {
            "item_id": "IMPL-003",
            "area": "riscv_build_runtime",
            "implementation_class": "source_compile_file",
            "target_paths": ["build", "third_party/musl"],
            "current_status": "meta_case_identified",
            "execution_decision": "requires_diff_or_source_review",
            "why_not_completed": "Meta cases identify the connected RISC-V build/Rust/NDK/musl route, but the meta package does not include source diffs that can be safely applied to this workspace.",
            "next_action": "Compare target RVBook source diffs or compact raw records against this workspace before generating implementation patches.",
            "evidence_refs": unique([target_seed_ref, f"meta_method:{riscv_method}"] + riscv_case_refs[:4]),
        },
        {
            "item_id": "IMPL-004",
            "area": "feature_driver_runtime",
            "implementation_class": "source_compile_file",
            "target_paths": ["drivers", "drivers/peripheral", "device/board", "device/soc", "vendor"],
            "current_status": "deferred_until_base_binding",
            "execution_decision": "defer_feature_specific_source_work",
            "why_not_completed": "Display/GPU/G2D, HDF audio, USB camera, and WiFi cases are target-relevant, but feature work must wait until product/board/SoC and kernel routes are visible.",
            "next_action": "After base binding is visible, select required target features and promote each feature chain with driver, board, product, binary, and validation evidence.",
            "evidence_refs": unique([target_seed_ref, f"meta_method:{hdf_method}", f"meta_method:{wifi_method}", f"meta_method:{media_method}"] + selected_case_refs[:5]),
        },
        {
            "item_id": "IMPL-005",
            "area": "vendor_binary_dependency",
            "implementation_class": "external_binary_dependency",
            "target_paths": ["prebuilts", "vendor", "device/board", "kernel"],
            "current_status": "report_only",
            "execution_decision": "do_not_generate_binary_artifacts",
            "why_not_completed": f"BSP, bootloader, firmware, prebuilts, closed drivers, and signing/packaging tools require provenance, license, source/regeneration, and board validation evidence; {len(target_source_binary_assets)} target-source candidate(s) were inventoried for follow-up.",
            "next_action": "Complete external dependency inventory before any binary-dependent integration is marked implementation-complete.",
            "evidence_refs": unique([target_seed_ref, target_source_ref, f"meta_method:{binary_method}", f"meta_method:{boot_method}"] + selected_case_refs[:4]),
        },
    ]
    implementation_readiness = artifact_base("implementation_readiness")
    implementation_readiness.update(
        {
            "target": target,
            "overall_status": "blocked_before_source_implementation" if not target_product_paths else "ready_for_build_only_triage",
            "completion_claim": "not_complete",
            "items": implementation_items,
        }
    )

    source_blueprints = [
        {
            "blueprint_id": "SRC-BP-001",
            "target_path": f"productdefine/common/products/{target['product']}.json",
            "owning_area": "product_config",
            "file_kind": "productdefine_json",
            "generation_mode": "blueprint_only",
            "content_strategy": "Create a productdefine entry for the seed product that binds product_name, board, device_company, target_cpu, type, version, inheritance, and minimal subsystem selection.",
            "reference_paths": [path for path in ["productdefine/common/products/system_arm64_default.json"] if (workspace / path).exists()],
            "required_fields": ["product_name", "device_company", "target_cpu", "board", "type", "version", "inherit", "subsystems"],
            "target_values": {
                "product_name": target["product"],
                "device_company": target["vendor"],
                "target_cpu": target["architecture"],
                "board": target["board"],
                "type": "standard",
                "version": "3.0",
            },
            "apply_gate": "Only generate or apply after confirming product inheritance and subsystem set from target source evidence.",
            "evidence_refs": unique([target_seed_ref, product_ref, f"meta_method:{scope_method}", f"meta_method:{riscv_method}"] + product_case_refs[:3]),
        },
        {
            "blueprint_id": "SRC-BP-002",
            "target_path": f"vendor/{target['vendor']}/{target['product']}/config.json",
            "owning_area": "product_config",
            "file_kind": "vendor_product_config_json",
            "generation_mode": "blueprint_only",
            "content_strategy": "Create the vendor product config that maps product_name to device_build_path and board while preserving OpenHarmony product schema fields.",
            "reference_paths": [path for path in ["vendor/hihope/2in1_core_system/config.json"] if (workspace / path).exists()],
            "required_fields": ["product_name", "device_company", "device_build_path", "target_cpu", "type", "version", "board", "inherit", "subsystems"],
            "target_values": {
                "product_name": target["product"],
                "device_company": clean_str(target_seed.get("soc_vendor"), target["vendor"]),
                "device_build_path": f"device/board/{target['vendor']}/{target['board']}",
                "target_cpu": target["architecture"],
                "board": target["board"],
            },
            "apply_gate": "Only generate or apply after confirming device_company semantics for ISCAS versus T-Head ownership and target subsystem requirements.",
            "evidence_refs": unique([target_seed_ref, product_ref, f"meta_method:{scope_method}"] + product_case_refs[:3]),
        },
        {
            "blueprint_id": "SRC-BP-003",
            "target_path": f"vendor/{target['vendor']}/{target['product']}/ohos.build",
            "owning_area": "product_config",
            "file_kind": "vendor_build_manifest",
            "generation_mode": "blueprint_only",
            "content_strategy": "Create a vendor build manifest only after selecting target components; keep feature-specific HDF, WiFi, camera, display, and audio components outside the base skeleton until selected.",
            "reference_paths": bounded_glob(workspace, "vendor/*/*/ohos.build", limit=4),
            "required_fields": ["subsystem", "parts"],
            "target_values": {
                "product_company": target["vendor"],
                "product_name": target["product"],
            },
            "apply_gate": "Only generate or apply after the minimal component set is selected from target source evidence.",
            "evidence_refs": unique([target_seed_ref, f"meta_method:{evidence_method}", f"meta_method:{riscv_method}"] + product_case_refs[:2]),
        },
        {
            "blueprint_id": "SRC-BP-004",
            "target_path": f"device/board/{target['vendor']}/{target['board']}/config.gni",
            "owning_area": "board_soc_config",
            "file_kind": "board_config_gni",
            "generation_mode": "blueprint_only",
            "content_strategy": "Create board architecture/toolchain declarations for the target board; avoid guessing CPU microarchitecture, FPU, or toolchain knobs beyond seed-level RISC-V64 identity.",
            "reference_paths": [path for path in ["device/board/hihope/rk3568/config.gni"] if (workspace / path).exists()],
            "required_fields": ["board_arch", "board_cpu", "board_toolchain_type"],
            "target_values": {
                "board_arch": "riscv64",
                "board_cpu": "unknown",
                "board_toolchain_type": "clang",
            },
            "apply_gate": "Only generate or apply after confirming TH1520 CPU/toolchain values and kernel build assumptions.",
            "evidence_refs": unique([target_seed_ref, f"meta_method:{riscv_method}", f"meta_method:{boot_method}"] + product_case_refs[:2]),
        },
        {
            "blueprint_id": "SRC-BP-005",
            "target_path": f"device/board/{target['vendor']}/{target['board']}/device.gni",
            "owning_area": "board_soc_config",
            "file_kind": "board_device_gni",
            "generation_mode": "blueprint_only",
            "content_strategy": "Create board-to-SoC imports and base feature switches after the SoC config path is confirmed.",
            "reference_paths": [path for path in ["device/board/hihope/rk3568/device.gni"] if (workspace / path).exists()],
            "required_fields": ["soc_company", "soc_name", "product_config_path"],
            "target_values": {
                "soc_company": clean_str(target_seed.get("soc_vendor"), target["vendor"]),
                "soc_name": target["soc"],
                "product_config_path": f"//vendor/{target['vendor']}/{target['product']}",
            },
            "apply_gate": "Only generate or apply after confirming device/soc import path and feature switches for RVBook.",
            "evidence_refs": unique([target_seed_ref, f"meta_method:{scope_method}", f"meta_method:{riscv_method}"] + product_case_refs[:3]),
        },
        {
            "blueprint_id": "SRC-BP-006",
            "target_path": f"device/soc/{clean_str(target_seed.get('soc_vendor'), target['vendor'])}/{target['soc']}/soc.gni",
            "owning_area": "board_soc_config",
            "file_kind": "soc_config_gni",
            "generation_mode": "blueprint_only",
            "content_strategy": "Create SoC-level paths and HAL feature variables only from confirmed TH1520 BSP evidence; do not infer display, camera, audio, or USB implementation paths from unrelated boards.",
            "reference_paths": [path for path in ["device/soc/rockchip/rk3566/soc.gni"] if (workspace / path).exists()],
            "required_fields": ["soc_name", "soc_company", "hal_paths_or_feature_switches"],
            "target_values": {
                "soc_company": clean_str(target_seed.get("soc_vendor"), target["vendor"]),
                "soc_name": target["soc"],
            },
            "apply_gate": "Only generate or apply after TH1520 SoC HAL/source paths and binary dependencies are inventoried.",
            "evidence_refs": unique([target_seed_ref, f"meta_method:{riscv_method}", f"meta_method:{binary_method}"] + selected_case_refs[:4]),
        },
        {
            "blueprint_id": "SRC-BP-007",
            "target_path": "build and third_party/musl RISC-V route",
            "owning_area": "riscv_build_runtime",
            "file_kind": "cross_repo_source_route",
            "generation_mode": "blueprint_only",
            "content_strategy": "Use meta cases to compare build target selection, Rust sysroot/toolchain routing, NDK library paths, musl namespace generation, and libc low-level RISC-V support before source edits.",
            "reference_paths": ["build", "third_party/musl"],
            "required_fields": ["diff_source", "affected_repos", "build_log_after_product_visible"],
            "target_values": {
                "architecture": target["architecture"],
                "product": target["product"],
            },
            "apply_gate": "Only generate or apply after raw diffs or source evidence for the RVBook RISC-V route are available.",
            "evidence_refs": unique([target_seed_ref, f"meta_method:{riscv_method}"] + riscv_case_refs[:4]),
        },
    ]
    source_file_blueprint = artifact_base("source_file_blueprint")
    source_file_blueprint.update(
        {
            "target": target,
            "default_generation_mode": "blueprint_only",
            "apply_policy": "do_not_apply_without_target_source_evidence",
            "blueprints": source_blueprints,
        }
    )
    product_json_preview = {
        "product_name": target["product"],
        "device_company": target["vendor"],
        "target_cpu": target["architecture"],
        "board": target["board"],
        "type": "standard",
        "version": "3.0",
        "enable_ramdisk": True,
        "build_selinux": True,
        "inherit": ["productdefine/common/inherit/rich.json"],
        "subsystems": [],
    }
    vendor_config_preview = {
        "product_name": target["product"],
        "device_company": clean_str(target_seed.get("soc_vendor"), target["vendor"]),
        "device_build_path": f"device/board/{target['vendor']}/{target['board']}",
        "target_cpu": target["architecture"],
        "type": "standard",
        "version": "3.0",
        "board": target["board"],
        "enable_ramdisk": True,
        "build_selinux": True,
        "inherit": ["productdefine/common/inherit/rich.json"],
        "subsystems": [],
    }

    def target_source_file_exists(rel_path: str) -> bool:
        return bool(target_source_root and (target_source_root / rel_path).is_file())

    def target_source_preview_or(rel_path: str, fallback: str) -> str:
        if target_source_file_exists(rel_path):
            preview = read_text_preview(target_source_root / rel_path)
            if preview:
                return preview
        return fallback

    def candidate_readiness(rel_path: str) -> str:
        return "target_source_available_review_only" if target_source_file_exists(rel_path) else "preview_only_not_apply_ready"

    def candidate_refs(rel_path: str, refs: list[str]) -> list[str]:
        source_ref = target_source_file_refs.get(rel_path)
        return unique(([source_ref] if source_ref else []) + refs)

    product_define_path = f"productdefine/common/products/{target['product']}.json"
    vendor_config_path = f"vendor/{target['vendor']}/{target['product']}/config.json"
    vendor_ohos_build_path = f"vendor/{target['vendor']}/{target['product']}/ohos.build"
    board_config_path = f"device/board/{target['vendor']}/{target['board']}/config.gni"
    board_device_path = f"device/board/{target['vendor']}/{target['board']}/device.gni"
    soc_config_path = f"device/soc/{clean_str(target_seed.get('soc_vendor'), target['vendor'])}/{target['soc']}/soc.gni"

    candidate_files = [
        {
            "candidate_id": "SRC-CAND-001",
            "target_path": product_define_path,
            "source_blueprint_ref": "SRC-BP-001",
            "content_format": "json",
            "readiness": candidate_readiness(product_define_path),
            "write_policy": "do_not_write_to_workspace",
            "content_preview": target_source_preview_or(product_define_path, json.dumps(product_json_preview, ensure_ascii=False, indent=2)),
            "open_questions": ["Confirm product inheritance profile.", "Confirm minimal subsystem/component set."],
            "apply_gate": "Target product inheritance and subsystem list must be confirmed by target source evidence.",
            "evidence_refs": candidate_refs(product_define_path, [target_seed_ref, target_source_ref, f"meta_method:{scope_method}", f"meta_method:{riscv_method}"] + product_case_refs[:3]),
        },
        {
            "candidate_id": "SRC-CAND-002",
            "target_path": vendor_config_path,
            "source_blueprint_ref": "SRC-BP-002",
            "content_format": "json",
            "readiness": candidate_readiness(vendor_config_path),
            "write_policy": "do_not_write_to_workspace",
            "content_preview": target_source_preview_or(vendor_config_path, json.dumps(vendor_config_preview, ensure_ascii=False, indent=2)),
            "open_questions": ["Confirm whether device_company should be the SoC vendor `thead` or board/vendor owner `iscas`.", "Confirm target product components."],
            "apply_gate": "Device-company ownership and target component set must be confirmed.",
            "evidence_refs": candidate_refs(vendor_config_path, [target_seed_ref, product_ref, target_source_ref, f"meta_method:{scope_method}"] + product_case_refs[:3]),
        },
        {
            "candidate_id": "SRC-CAND-003",
            "target_path": vendor_ohos_build_path,
            "source_blueprint_ref": "SRC-BP-003",
            "content_format": "json",
            "readiness": candidate_readiness(vendor_ohos_build_path),
            "write_policy": "do_not_write_to_workspace",
            "content_preview": target_source_preview_or(vendor_ohos_build_path, json.dumps(
                {
                    "subsystem": f"{target['vendor']}_products",
                    "parts": {f"{target['product']}_products": {"module_list": []}},
                },
                ensure_ascii=False,
                indent=2,
            )),
            "open_questions": ["Confirm actual subsystem and part naming convention.", "Confirm module_list contents."],
            "apply_gate": "Minimal product parts and module list must be selected from target source evidence.",
            "evidence_refs": candidate_refs(vendor_ohos_build_path, [target_seed_ref, target_source_ref, f"meta_method:{evidence_method}", f"meta_method:{riscv_method}"] + product_case_refs[:2]),
        },
        {
            "candidate_id": "SRC-CAND-004",
            "target_path": board_config_path,
            "source_blueprint_ref": "SRC-BP-004",
            "content_format": "gn",
            "readiness": candidate_readiness(board_config_path),
            "write_policy": "do_not_write_to_workspace",
            "content_preview": target_source_preview_or(board_config_path, '\n'.join([
                'board_arch = "riscv64"',
                'board_cpu = "unknown"',
                'board_toolchain_type = "clang"',
                '',
            ])),
            "open_questions": ["Confirm TH1520 CPU string.", "Confirm board toolchain and board FPU settings."],
            "apply_gate": "TH1520 CPU/toolchain values must be confirmed; unknown fields must be resolved before apply.",
            "evidence_refs": candidate_refs(board_config_path, [target_seed_ref, target_source_ref, f"meta_method:{riscv_method}", f"meta_method:{boot_method}"] + product_case_refs[:2]),
        },
        {
            "candidate_id": "SRC-CAND-005",
            "target_path": board_device_path,
            "source_blueprint_ref": "SRC-BP-005",
            "content_format": "gn",
            "readiness": candidate_readiness(board_device_path),
            "write_policy": "do_not_write_to_workspace",
            "content_preview": target_source_preview_or(board_device_path, '\n'.join([
                f'soc_company = "{clean_str(target_seed.get("soc_vendor"), target["vendor"])}"',
                f'soc_name = "{target["soc"]}"',
                '',
                'import("//device/soc/${soc_company}/${soc_name}/soc.gni")',
                'import("//build/ohos.gni")',
                '',
                'if (!defined(defines)) {',
                '  defines = []',
                '}',
                '',
                'product_config_path = "//vendor/${product_company}/${product_name}"',
                '',
            ])),
            "open_questions": ["Confirm target SoC import path exists.", "Confirm base feature switches for boot graphics, codec, camera, display, USB, and WiFi."],
            "apply_gate": "device/soc import and base feature flags must be confirmed.",
            "evidence_refs": candidate_refs(board_device_path, [target_seed_ref, target_source_ref, f"meta_method:{scope_method}", f"meta_method:{riscv_method}"] + product_case_refs[:3]),
        },
        {
            "candidate_id": "SRC-CAND-006",
            "target_path": soc_config_path,
            "source_blueprint_ref": "SRC-BP-006",
            "content_format": "gn",
            "readiness": candidate_readiness(soc_config_path),
            "write_policy": "do_not_write_to_workspace",
            "content_preview": target_source_preview_or(soc_config_path, '\n'.join([
                f'soc_company = "{clean_str(target_seed.get("soc_vendor"), target["vendor"])}"',
                f'soc_name = "{target["soc"]}"',
                '',
                '# HAL paths and feature switches must come from TH1520 BSP evidence.',
                '',
            ])),
            "open_questions": ["Confirm TH1520 HAL paths.", "Confirm display/GPU/G2D, camera, audio, USB, and WiFi dependencies."],
            "apply_gate": "TH1520 SoC HAL/source paths and binary dependency inventory must be confirmed.",
            "evidence_refs": candidate_refs(soc_config_path, [target_seed_ref, target_source_ref, f"meta_method:{riscv_method}", f"meta_method:{binary_method}"] + selected_case_refs[:4]),
        },
    ]
    source_candidate_manifest = artifact_base("source_candidate_manifest")
    source_candidate_manifest.update(
        {
            "target": target,
            "default_write_policy": "do_not_write_to_workspace",
            "candidate_count": len(candidate_files),
            "candidates": candidate_files,
            "scope_note": "Concrete candidate content is for review only. It is not a patch and is not apply-ready while source evidence remains incomplete.",
        }
    )

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
        "meta_knowledge_digest.yaml": meta_knowledge_digest,
        "target_source_evidence.yaml": target_source_evidence,
        "source_import_plan.yaml": source_import_plan,
        "implementation_readiness.yaml": implementation_readiness,
        "source_file_blueprint.yaml": source_file_blueprint,
        "source_candidate_manifest.yaml": source_candidate_manifest,
        "source_tree_survey.yaml": source_tree_survey,
        "gap_analysis.yaml": gap_analysis,
        "porting_plan.yaml": porting_plan,
        "patch_plan.yaml": patch_plan,
        "build_acceptance.yaml": build_acceptance,
        "external_dependency_followup.yaml": external_dependency_followup,
        "target_dependency_inventory.yaml": target_dependency_inventory,
        "uncertainty_ledger.yaml": uncertainty_ledger,
    }
    for name, data in artifacts.items():
        dump_yaml(artifact_root / name, data)

    write_text(
        artifact_root / "meta_knowledge_digest.md",
        "# Meta Knowledge Digest\n\n"
        f"- Status: `{meta_knowledge_digest.get('meta_status', 'unknown')}`\n"
        f"- Selected methods: {len(meta_knowledge_digest.get('selected_methods', []))}\n"
        f"- Selected cases: {len(meta_knowledge_digest.get('selected_cases', []))}\n\n"
        "## Methods\n\n"
        + "\n".join(
            f"- {item['method_id']}: {item['title']}"
            for item in meta_knowledge_digest.get("selected_methods", [])
        )
        + "\n\n## Cases\n\n"
        + "\n".join(
            f"- {item['case_id']}: {item['title']} ({', '.join(item.get('repo_paths', [])[:4]) or 'no repo path'})"
            for item in meta_knowledge_digest.get("selected_cases", [])
        )
        + "\n\n## Action Bias\n\n"
        + "\n".join(
            f"- {item['action_id']} `{item['area']}`: {item['recommendation']}"
            for item in meta_knowledge_digest.get("action_bias", [])
        ),
    )
    write_text(
        artifact_root / "target_source_evidence.md",
        "# Target Source Evidence\n\n"
        f"- Status: `{target_source_evidence.get('scan_status', 'unknown')}`\n"
        f"- Root: `{target_source_evidence.get('target_source_root', 'unknown')}`\n"
        f"- Expected target paths found: {target_source_evidence.get('found_path_count', 0)} / {target_source_evidence.get('expected_path_count', 0)}\n"
        f"- Dependency candidates: {target_source_evidence.get('binary_asset_count', 0)}\n"
        f"- Coverage: {target_source_evidence.get('coverage_note', '')}\n\n"
        "## Source Paths\n\n"
        + "\n".join(
            f"- {item['evidence_id']} `{item['status']}` `{item['path']}` role={item['role']}"
            for item in target_source_items[:40]
            if isinstance(item, dict)
        )
        + "\n\n## Dependency Candidates\n\n"
        + "\n".join(
            f"- {asset['asset_id']} `{asset['category']}` `{asset['path']}` sha256={asset['sha256']}"
            for asset in target_source_binary_assets[:40]
            if isinstance(asset, dict)
        ),
    )
    write_text(
        artifact_root / "source_import_plan.md",
        "# Source Import Plan\n\n"
        f"- Policy: `{source_import_plan['import_policy']}` / `{source_import_plan['default_write_policy']}`\n"
        f"- Import queue items: {source_import_plan['item_count']}\n"
        f"- Excluded dependency items: {source_import_plan['excluded_dependency_count']}\n"
        f"- Decisions: {source_import_plan['decision_counts']}\n"
        f"- Coverage: {source_import_plan['coverage_note']}\n\n"
        "## Import Queue\n\n"
        + "\n".join(
            f"- {item['import_id']} `{item['import_class']}` `{item['target_path']}`: {item['import_decision']} current={item['current_workspace_status']}"
            for item in source_import_plan.get("items", [])[:60]
            if isinstance(item, dict)
        )
        + "\n\n## Excluded Dependencies\n\n"
        + "\n".join(
            f"- {item['excluded_id']} `{item['category']}` `{item['path']}`: {item['reason']} -> {item['routed_to']}"
            for item in source_import_plan.get("excluded_items", [])[:40]
            if isinstance(item, dict)
        ),
    )
    write_text(
        artifact_root / "implementation_readiness.md",
        "# Implementation Readiness\n\n"
        f"- Overall status: `{implementation_readiness['overall_status']}`\n"
        f"- Completion claim: `{implementation_readiness['completion_claim']}`\n\n"
        + "\n".join(
            f"- {item['item_id']} `{item['area']}`: {item['execution_decision']} - {item['why_not_completed'] or 'ready for the next build-only step'}"
            for item in implementation_items
        ),
    )
    write_text(
        artifact_root / "source_file_blueprint.md",
        "# Source File Blueprint\n\n"
        f"- Default generation mode: `{source_file_blueprint['default_generation_mode']}`\n"
        f"- Apply policy: `{source_file_blueprint['apply_policy']}`\n\n"
        + "\n".join(
            f"- {item['blueprint_id']} `{item['target_path']}` ({item['file_kind']}): {item['content_strategy']} Gate: {item['apply_gate']}"
            for item in source_blueprints
        ),
    )
    write_text(
        artifact_root / "source_candidate_manifest.md",
        "# Source Candidate Manifest\n\n"
        f"- Default write policy: `{source_candidate_manifest['default_write_policy']}`\n"
        f"- Candidate files: {source_candidate_manifest['candidate_count']}\n"
        f"- Scope: {source_candidate_manifest['scope_note']}\n\n"
        + "\n\n".join(
            "## "
            + item["candidate_id"]
            + f" `{item['target_path']}`\n\n"
            + f"- Readiness: `{item['readiness']}`\n"
            + f"- Apply gate: {item['apply_gate']}\n\n"
            + f"```{item['content_format']}\n{item['content_preview']}\n```"
            for item in candidate_files
        ),
    )
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
        f"- Target: `{target['product']}` / `{target['board']}` / `{target['soc']}` / `{target['vendor']}` / `{target['architecture']}`\n"
        f"- Vendor dependency summary: {external_dependency_followup['target_dependency_summary']['summary']}\n\n"
        + "\n".join(f"- {item['dependency_id']} `{item['category']}`: {item['why_needed']}" for item in external_items),
    )
    write_text(
        artifact_root / "target_dependency_inventory.md",
        "# Target Dependency Inventory\n\n"
        f"- Source: `{target_dependency_inventory['inventory_source']}`\n"
        f"- Candidate assets: {target_dependency_inventory['asset_count']}\n\n"
        + "\n".join(
            f"- {item['asset_id']} `{item['category']}` `{item['path']}` sha256={item['sha256']} source={item['source_case_id']}"
            for item in inventory_items
        ),
    )
    write_text(
        artifact_root / "porting_completion_summary.md",
        "# Porting Completion Summary\n\n"
        f"- Target: `{target['product']}` / `{target['board']}` / `{target['soc']}` / `{target['vendor']}` / `{target['architecture']}`\n"
        f"- Meta knowledge: {len(selected_method_ids)} selected method(s), {len(selected_case_ids)} selected case(s)\n"
        f"- Target source evidence: `{target_source_evidence.get('scan_status', 'unknown')}`, found {target_source_evidence.get('found_path_count', 0)} / {target_source_evidence.get('expected_path_count', 0)} expected path(s), {target_source_evidence.get('binary_asset_count', 0)} dependency candidate(s)\n"
        f"- Source import plan: {source_import_plan['item_count']} queue item(s), {source_import_plan['excluded_dependency_count']} excluded dependency item(s), policy `{source_import_plan['default_write_policy']}`\n"
        f"- Source blueprints: {len(source_blueprints)} blueprint(s), generation mode `{source_file_blueprint['default_generation_mode']}`\n"
        f"- Source candidate files: {len(candidate_files)}, write policy `{source_candidate_manifest['default_write_policy']}`\n"
        f"- Candidate binary/vendor assets: {len(inventory_items)} from selected meta cases and target source evidence\n"
        f"- Source implementation status: `{implementation_readiness['overall_status']}`\n"
        f"- Build acceptance: `{build_acceptance['status']}` / `{build_acceptance['acceptance_level']}`\n"
        "- Boot/runtime/device/test status: `unknown`\n\n"
        "## Implementable Source And Compile Files\n\n"
        + "\n".join(
            f"- {item['item_id']} `{item['area']}`: {item['execution_decision']}; paths={', '.join(item['target_paths'][:4])}"
            for item in implementation_items
            if item["implementation_class"] == "source_compile_file"
        )
        + "\n\n## Source Blueprints\n\n"
        + "\n".join(
            f"- {item['blueprint_id']} `{item['target_path']}`: {item['generation_mode']}; gate={item['apply_gate']}"
            for item in source_blueprints
        )
        + "\n\n## Source Candidate Files\n\n"
        + "\n".join(
            f"- {item['candidate_id']} `{item['target_path']}`: {item['readiness']}; gate={item['apply_gate']}"
            for item in candidate_files
        )
        + "\n\n## Source Import Queue\n\n"
        + "\n".join(
            f"- {item['import_id']} `{item['import_class']}` `{item['target_path']}`: {item['import_decision']}; current={item['current_workspace_status']}"
            for item in source_import_plan.get("items", [])[:30]
            if isinstance(item, dict)
        )
        + "\n\n## Vendor And Binary Dependencies\n\n"
        + "\n".join(f"- {item['dependency_id']} `{item['category']}`: {item['next_action']}" for item in external_items)
        + "\n\n## Candidate Assets From Meta Evidence\n\n"
        + "\n".join(
            f"- {item['asset_id']} `{item['category']}` `{item['path']}` from {item['source_case_id']}"
            for item in inventory_items[:20]
        )
        + "\n\n## Current Completion Judgment\n\n"
        "The port is not implementation-complete in this workspace. The next reliable move is to make the target product/board/SoC visible from source evidence, then run build-only triage for the seed product.",
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
                "01_normalized_cases/cases.jsonl",
                "03_methodology/architecture_porting_runbook.md",
                "03_methodology/board_soc_porting_runbook.md",
                "03_methodology/binary_prebuilt_governance.md",
                "meta_skill_pack/references/conditional_method_index.md",
                "meta_report.md",
            ]
            if (meta_output / path).exists()
        )
    if target_seed_path:
        inputs_read.append(str(target_seed_path))
    if target_source_root and target_source_root.exists():
        inputs_read.append(str(target_source_root))
        inputs_read.extend(
            str(target_source_root / clean_str(item.get("path"), ""))
            for item in target_source_items[:40]
            if isinstance(item, dict)
            and item.get("status") == "found"
            and clean_str(item.get("path"), "")
        )
    if build_log_path:
        inputs_read.append(str(build_log_path))

    non_blocking = []
    if not target_seed_path:
        non_blocking.append("PORTING_EXECUTION_TARGET_PROFILE_SEED is empty; target identity remains unknown.")
    elif not target_product_paths:
        if target_source_loaded:
            non_blocking.append(f"Target profile seed is supplied and target source root was scanned, but target product `{target['product']}` is still not visible in the current workspace.")
        else:
            non_blocking.append(f"Target profile seed is supplied, but target product `{target['product']}` is not visible in the current source tree.")
    if target_source_root and not target_source_loaded:
        non_blocking.append("PORTING_EXECUTION_TARGET_SOURCE_ROOT was supplied but could not be loaded.")
    if not source_stage_files:
        non_blocking.append("PORTING_EXECUTION_SOURCE_OUTPUT lacks compact Stage 00-07 artifacts; evidence depth is limited.")
    if not build_log_path:
        non_blocking.append("PORTING_EXECUTION_BUILD_LOG is empty; build triage remains unknown.")

    result = {
        "stage": STAGE,
        "status": "partial" if non_blocking else "passed",
        "summary": f"Deterministic plan-only execution package generated; target seed and meta knowledge were consumed, with {len(selected_method_ids)} selected method(s), {len(selected_case_ids)} selected case(s), {len(source_blueprints)} source blueprint(s), {len(candidate_files)} candidate source file preview(s), {source_import_plan['item_count']} source import queue item(s), {len(inventory_items)} candidate dependency asset(s), and target-source scan status {target_source_evidence.get('scan_status', 'unknown')} ({target_source_evidence.get('found_path_count', 0)}/{target_source_evidence.get('expected_path_count', 0)} expected path(s)). Target source visibility/build acceptance remain separate.",
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
