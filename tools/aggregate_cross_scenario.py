#!/usr/bin/env python3
"""Aggregate multiple 07_meta_inputs directories into a cross-scenario meta KB.

This script is deliberately conservative:
- it accepts only normalized Stage-08 inputs;
- it never promotes a formal universal method from fewer than three scenarios;
- it preserves scenario-specific evidence instead of flattening differences;
- it writes machine-readable pattern/case/method JSONL files for auditability.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml


REQUIRED_META_INPUT_FILES = [
    "scenario_card.yaml",
    "normalized_cases.jsonl",
    "pattern_candidates.jsonl",
    "anti_patterns.jsonl",
    "method_fragments.jsonl",
    "validation_status.yaml",
    "meta_input_audit.md",
]

FORMAL_UNIVERSAL_MIN_SCENARIOS = 3

EVIDENCE_TYPES = {
    "commit_file_diff",
    "commit_file",
    "dirty_or_binary_only",
    "log_verified",
    "unknown",
}
EVIDENCE_STRENGTHS = {
    "high",
    "medium_high",
    "medium",
    "medium_low",
    "low",
    "unknown",
}
EVIDENCE_TYPE_ALIASES = {
    "commit_file_diff": "commit_file_diff",
    "commit_and_file": "commit_file",
    "commit_file": "commit_file",
    "dirty_or_binary_only": "dirty_or_binary_only",
    "log_verified": "log_verified",
    "unknown": "unknown",
}
SCENARIO_TYPE_ALIASES = {
    "board_soc_arm_primary_auxiliary_core": ["board_soc_arm_primary", "heterogeneous_aux_core"],
    "arm_primary_auxiliary_core": ["board_soc_arm_primary", "heterogeneous_aux_core"],
    "arm_primary_aux_core": ["board_soc_arm_primary", "heterogeneous_aux_core"],
}
DEFAULT_GUARDRAIL_METHOD_IDS = {
    "MF-EVIDENCE-FIRST-001": "Evidence-Class Separation",
    "MF-SCOPE-AUTHORITY-001": "Scenario Scope Authority",
    "MF-VALIDATION-SEPARATION-001": "Validation Separation",
}
PROMOTION_LEVELS = [
    "universal_by_design",
    "universal_from_evidence",
    "universal_candidate",
    "conditional",
    "scenario_specific",
    "risk_only",
    "anti_pattern",
]

CONDITIONAL_METHOD_SPECS = [
    {
        "method_id": "META-CONDITIONAL-HDF-DRIVER-MULTIREPO-CHAIN",
        "title": "HDF Driver Multi-Repo Enablement Chain",
        "keywords": ["hdf", "audio", "alsa", "codec", "hcs", "hcb"],
        "match_mode": "hdf_driver",
        "exclude_keywords": ["camera", "media", "v4l2", "usb camera", "usb_camera"],
        "statement": "HDF driver enablement is conditional reusable knowledge only when driver implementation, board or SoC binding, vendor/HCS/HCB or policy configuration, generated assets, and validation status are reviewed as one chain.",
        "applicability": ["hdf_driver_porting", "hdf_audio", "board_vendor_driver_stack"],
        "non_applicability": ["camera/media HDF chains that require V4L2 or USB-host handling", "single codec patch without board/vendor config", "generated HCB or binary archive used as source proof"],
        "quality_gates": [
            "At least one source-level driver or HAL path is present.",
            "At least one board/vendor/product configuration path is present.",
            "Generated HDF assets and binary archives remain provenance or runtime-risk evidence.",
        ],
    },
    {
        "method_id": "META-CONDITIONAL-MEDIA-CAMERA-HDF-CHAIN",
        "title": "Media/Camera HDF And V4L2 Enablement Chain",
        "keywords": ["camera", "media", "v4l2", "usb camera", "usb_camera"],
        "statement": "Camera/media HDF enablement is conditional reusable knowledge when HDF camera capability, V4L2 or USB-host plumbing, board/product configuration, and runtime validation requirements are traced together.",
        "applicability": ["media_camera_hdf", "usb_camera", "v4l2_driver_stack"],
        "non_applicability": ["audio-only HDF chains", "single media codec config without driver or board binding", "camera feature claims without runtime validation evidence"],
        "quality_gates": [
            "Separate camera/media capability configuration from audio HDF policy.",
            "Require driver, bus or host controller, and board/product wiring before reuse.",
            "Keep runtime validation unknown unless camera device enumeration or capture logs exist.",
        ],
    },
    {
        "method_id": "META-CONDITIONAL-WIFI-SDIO-RUNTIME-CHAIN",
        "title": "WiFi/SDIO/Wireless Runtime Chain",
        "keywords": ["wifi", "sdio", "wireless", "bluetooth", "rfkill", "wlan"],
        "statement": "Wireless bring-up cases are conditionally reusable when kernel driver options, SDIO or bus timing, board power/DTS binding, user-space service assumptions, product components, and runtime validation are tracked together.",
        "applicability": ["wifi_sdio", "wireless_runtime", "driver_enablement"],
        "non_applicability": ["binary-only module delivery", "single DTS or Kconfig change presented as full wireless enablement"],
        "quality_gates": [
            "Separate source driver fixes from delivered modules and firmware.",
            "Keep runtime services and product components linked to board driver evidence.",
            "Record suspend/resume and power-management assumptions as validation requirements.",
        ],
    },
    {
        "method_id": "META-CONDITIONAL-RISCV-BUILD-RUNTIME-ROUTE",
        "title": "RISC-V Build, Runtime, Toolchain, And Product Route",
        "keywords": ["riscv", "risc-v", "toolchain", "musl", "sdk", "runtime", "product", "board", "vendor"],
        "required_scenario_type": "riscv_primary_distribution",
        "match_mode": "riscv_route",
        "statement": "RISC-V-primary distribution work is conditionally reusable when product identity, board/vendor binding, build variables, SDK/toolchain routes, musl/runtime namespace, and package/image rules are reviewed as one architecture route.",
        "applicability": ["riscv_primary_distribution", "build_system_integration", "product_board_binding"],
        "non_applicability": ["ARM-primary board ports", "auxiliary RISC-V firmware inside a non-RISC-V primary runtime"],
        "quality_gates": [
            "Require productdefine or product route evidence plus board/vendor evidence.",
            "Require build/toolchain/runtime evidence before calling a fix architecture-level.",
            "Treat whitelist-only or board-only accommodations as conditional board knowledge.",
        ],
    },
    {
        "method_id": "META-CONDITIONAL-BOOT-FIRMWARE-PROVENANCE",
        "title": "Boot, Firmware, Partition, And Provenance Chain",
        "keywords": ["boot", "firmware", "provenance", "partition", "uboot", "u-boot", "spl", "reboot"],
        "match_mode": "boot_scope",
        "statement": "Boot and firmware knowledge is conditionally reusable when editable boot configuration, partition/updater policy, firmware payloads, signing or regeneration path, and board-specific boot-stage assumptions are separated.",
        "applicability": ["boot_firmware", "partitioning", "firmware_provenance"],
        "non_applicability": ["binary boot asset treated as source fix", "initial import used as provenance proof"],
        "quality_gates": [
            "Distinguish text configuration from firmware payloads.",
            "Record hash, provenance, license, and regeneration or signing status for binaries.",
            "Keep validation unknown unless boot logs or board test records prove success.",
        ],
    },
    {
        "method_id": "META-CONDITIONAL-BINARY-PREBUILT-PROVENANCE",
        "title": "Binary, Prebuilt, Generated Asset, And Firmware Provenance",
        "keywords": ["binary", "prebuilt", "firmware", "generated", "provenance", ".ko", ".bin", ".o", ".a", "hcb", ".so"],
        "match_mode": "binary_provenance",
        "statement": "Binary, prebuilt, generated-asset, and firmware records are conditionally reusable as provenance evidence, not as source fixes, until source origin, license, regeneration path, architecture, and validation status are documented.",
        "applicability": ["binary_prebuilt_provenance", "firmware_governance", "generated_asset_governance"],
        "non_applicability": ["dirty workspace workflow governance", "committed source fix proof", "formal universal source-porting method"],
        "quality_gates": [
            "Record path, hash, architecture, possible usage, and redistribution risk.",
            "Link generated assets back to their generator or mark provenance unknown.",
            "Keep validation unknown unless boot or runtime logs prove the asset is used successfully.",
        ],
    },
    {
        "method_id": "META-CONDITIONAL-DIRTY-WORKSPACE-GOVERNANCE",
        "title": "Dirty Workspace And Local Patch Governance",
        "keywords": ["dirty", "workspace", "workaround", "local", "generated"],
        "match_mode": "dirty_workspace",
        "statement": "Dirty workspace and local patch records are conditionally reusable only as workflow governance until they are converted into clean commits, linked to evidence_refs, and revalidated against build, boot, or runtime expectations.",
        "applicability": ["dirty_workspace_governance", "local_patch_governance", "risk_governance"],
        "non_applicability": ["binary provenance without local workspace changes", "clean committed source history", "formal universal source-porting method"],
        "quality_gates": [
            "Keep dirty files separate from committed history.",
            "Classify each dirty record as experiment, generated output, workaround, missing commit, or risk.",
            "Require a clean patch or commit before promoting dirty evidence into reusable source guidance.",
        ],
    },
]


def fail(message: str) -> None:
    print(f"[BLOCKED] {message}", file=sys.stderr)
    raise SystemExit(1)


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def read_yaml(path: Path) -> dict[str, Any]:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8", errors="ignore")) or {}
    except Exception as exc:
        fail(f"YAML parse failed: {path}: {exc}")
    return data if isinstance(data, dict) else {}


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not path.exists():
        return rows
    with path.open(encoding="utf-8", errors="ignore") as f:
        for lineno, line in enumerate(f, start=1):
            if not line.strip():
                continue
            try:
                obj = json.loads(line)
            except Exception as exc:
                fail(f"JSONL parse failed: {path}:{lineno}: {exc}")
            if isinstance(obj, dict):
                rows.append(obj)
            else:
                fail(f"JSONL row must be object: {path}:{lineno}")
    return rows


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )


def dump_yaml(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")


def listify(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()]
    if value is None:
        return []
    text = str(value).strip()
    return [text] if text else []


def unique_list(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        text = str(value).strip()
        if text and text not in seen:
            seen.add(text)
            result.append(text)
    return result


def slugify(value: str) -> str:
    value = str(value).lower()
    value = re.sub(r"[^a-z0-9]+", "_", value)
    return re.sub(r"_+", "_", value).strip("_") or "unknown"


def canonical_evidence_type(value: Any) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    return EVIDENCE_TYPE_ALIASES.get(text)


def infer_evidence_type(case: dict[str, Any]) -> str:
    for key in ["evidence_type", "evidence_level"]:
        canonical = canonical_evidence_type(case.get(key))
        if canonical:
            return canonical
    evidence = case.get("evidence") or {}
    validation = case.get("validation") or {}
    if isinstance(validation, dict) and validation.get("test_logs"):
        return "log_verified"
    if isinstance(evidence, dict):
        if evidence.get("diffs"):
            return "commit_file_diff"
        if evidence.get("commits") or evidence.get("files"):
            return "commit_file"
        if evidence.get("dirty_files") or evidence.get("binary_assets"):
            return "dirty_or_binary_only"
    return "unknown"


def normalize_evidence_fields(case: dict[str, Any]) -> None:
    raw_level = str(case.get("evidence_level") or "").strip()
    evidence_type = infer_evidence_type(case)
    case["evidence_type"] = evidence_type
    # Keep evidence_level for backward compatibility, but make it the same
    # canonical type so it no longer mixes type and strength vocabularies.
    case["evidence_level"] = evidence_type

    strength = str(case.get("evidence_strength") or "").strip()
    if strength not in EVIDENCE_STRENGTHS:
        for candidate in [str(case.get("confidence") or "").strip(), raw_level]:
            if candidate in EVIDENCE_STRENGTHS:
                strength = candidate
                break
        else:
            strength = "unknown"
    case["evidence_strength"] = strength


def normalize_scenario_types(case: dict[str, Any], card: dict[str, Any]) -> None:
    allowed = listify(card.get("scenario_type"))
    allowed_set = set(allowed)
    raw = listify(case.get("scenario_type"))
    normalized: list[str] = []
    scenario_shape = listify(case.get("scenario_shape"))

    for label in raw:
        if label in allowed_set:
            normalized.append(label)
            continue
        mapped = [item for item in SCENARIO_TYPE_ALIASES.get(label, []) if item in allowed_set]
        lower = label.lower()
        if not mapped and "aux" in lower and "heterogeneous_aux_core" in allowed_set:
            mapped.append("heterogeneous_aux_core")
        if not mapped and "arm" in lower and "board_soc_arm_primary" in allowed_set:
            mapped.append("board_soc_arm_primary")
        if not mapped and "riscv" in lower and "primary" in lower and "riscv_primary_distribution" in allowed_set:
            mapped.append("riscv_primary_distribution")
        if mapped:
            normalized.extend(mapped)
            scenario_shape.append(label)
        else:
            normalized.append(label)

    if not raw and allowed:
        normalized = allowed
    case["scenario_type"] = unique_list(normalized)
    if scenario_shape:
        case["scenario_shape"] = unique_list(scenario_shape)


def text_blob(*values: Any) -> str:
    parts: list[str] = []
    for value in values:
        if value is None:
            continue
        if isinstance(value, (dict, list, tuple)):
            parts.append(json.dumps(value, ensure_ascii=False, sort_keys=True))
        else:
            parts.append(str(value))
    return "\n".join(parts).lower()


def safe_relative(path: Path, root: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve()))
    except Exception:
        return path_label(path, str(path))


def path_label(path: Path | str | None, fallback: str) -> str:
    if not path:
        return fallback
    name = Path(str(path)).name
    return name if name and name != "." else fallback


def infer_kernel(card: dict[str, Any], cases: list[dict[str, Any]]) -> str:
    explicit = str(card.get("kernel") or "").strip()
    if explicit and explicit.lower() != "unknown":
        return explicit
    text = text_blob(card, cases)
    kernels: list[str] = []
    for pattern, label in [
        (r"linux[-_ ]?5[._-]?10", "linux-5.10"),
        (r"kernel[_/-]?5[._-]?10", "linux-5.10"),
        (r"linux[-_ ]?6[._-]?6", "linux-6.6"),
        (r"kernel[_/-]?6[._-]?6", "linux-6.6"),
    ]:
        if re.search(pattern, text) and label not in kernels:
            kernels.append(label)
    if len(kernels) == 1:
        return kernels[0]
    if len(kernels) > 1:
        return "mixed: " + ", ".join(kernels)
    if "linux" in text:
        return "linux"
    return "unknown"


def infer_system_type(card: dict[str, Any], cases: list[dict[str, Any]]) -> str:
    explicit = str(card.get("system_type") or "").strip()
    if explicit and explicit.lower() != "unknown":
        return explicit
    text = text_blob(card, cases)
    if re.search(r"\briscv[_-]?rich\b|\brich\b", text):
        return "standard_or_rich"
    if re.search(r"\bstandard\b", text):
        return "standard"
    if re.search(r"(^|[^a-z0-9])small([^a-z0-9]|$)|_small_defconfig|small_defconfig", text):
        return "small"
    if re.search(r"(^|[^a-z0-9])mini([^a-z0-9]|$)", text):
        return "mini"
    return "unknown"


def global_method_fragment_id(fragment: dict[str, Any]) -> str:
    scenario_id = str(fragment.get("scenario_id") or "unknown")
    method_id = str(fragment.get("method_fragment_id") or "MF-UNKNOWN")
    return f"{scenario_id}::{method_id}"


def evidence_ref_for_case(case: dict[str, Any] | None, case_id: Any) -> str:
    if case:
        return str(case.get("evidence_ref") or f"case:{case.get('scenario_id')}::{case.get('case_id')}")
    return f"case:unknown::{case_id}"


def reset_dir(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)


def resolve_meta_dir(path: Path) -> Path:
    candidates = [
        path / "07_meta_inputs",
        path,
    ]
    for candidate in candidates:
        if (candidate / "scenario_card.yaml").exists():
            missing = [name for name in REQUIRED_META_INPUT_FILES if not (candidate / name).exists()]
            if missing:
                fail(f"{candidate} is missing required meta inputs {missing}. Re-run Stage 08 meta_input_exporter.")
            return candidate
    fail(f"{path} does not contain 07_meta_inputs/scenario_card.yaml. Run Stage 08 meta_input_exporter first; old Markdown-only outputs are not accepted.")


def find_inputs(input_dirs: list[str], input_root: str | None) -> list[Path]:
    paths = [Path(item).resolve() for item in input_dirs]
    if input_root:
        root = Path(input_root).resolve()
        if not root.exists():
            fail(f"--input-root does not exist: {root}")
        paths.extend(sorted(parent.parent for parent in root.glob("*/porting_knowledge_output/07_meta_inputs/scenario_card.yaml")))
    if not paths:
        fail("No --input or --input-root provided.")
    meta_dirs: list[Path] = []
    seen: set[Path] = set()
    for path in paths:
        meta = resolve_meta_dir(path)
        if meta not in seen:
            seen.add(meta)
            meta_dirs.append(meta)
    return meta_dirs


def markdown_table(headers: list[str], rows: list[list[Any]]) -> str:
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join(["---"] * len(headers)) + " |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(str(cell).replace("\n", " ") for cell in row) + " |")
    return "\n".join(lines)


def load_scenarios(meta_dirs: list[Path]) -> list[dict[str, Any]]:
    scenarios: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for meta in meta_dirs:
        card = read_yaml(meta / "scenario_card.yaml")
        scenario_id = str(card.get("scenario_id") or "")
        if not scenario_id:
            fail(f"scenario_card.yaml missing scenario_id: {meta}")
        if scenario_id in seen_ids:
            fail(f"Duplicate scenario_id across inputs: {scenario_id}")
        seen_ids.add(scenario_id)
        cases = read_jsonl(meta / "normalized_cases.jsonl")
        patterns = read_jsonl(meta / "pattern_candidates.jsonl")
        anti_patterns = read_jsonl(meta / "anti_patterns.jsonl")
        fragments = read_jsonl(meta / "method_fragments.jsonl")
        for case in cases:
            normalize_scenario_types(case, card)
            normalize_evidence_fields(case)
        for row in [*cases, *patterns, *anti_patterns, *fragments]:
            if row.get("scenario_id") != scenario_id:
                fail(f"{meta}: row scenario_id={row.get('scenario_id')} does not match scenario_card scenario_id={scenario_id}")
        scenarios.append(
            {
                "meta_dir": meta,
                "card": card,
                "validation": read_yaml(meta / "validation_status.yaml"),
                "cases": cases,
                "patterns": patterns,
                "anti_patterns": anti_patterns,
                "method_fragments": fragments,
            }
        )
    return scenarios


def scenario_summary(item: dict[str, Any], workspace_root: Path, redact_local_paths: bool = False) -> dict[str, Any]:
    card = item["card"]
    meta_dir = item["meta_dir"]
    source_output_dir = card.get("source_output_dir")
    source_output_label = str(card.get("source_output_label") or card.get("scenario_id") or path_label(source_output_dir, "unknown"))
    summary = {
        "scenario_id": card.get("scenario_id"),
        "source_meta_dir_label": str(card.get("source_meta_dir_label") or f"{source_output_label}/07_meta_inputs"),
        "source_meta_dir_relative": safe_relative(meta_dir, workspace_root),
        "source_output_label": source_output_label,
        "source_output_dir_relative": str(card.get("source_output_dir_relative") or safe_relative(Path(str(source_output_dir)), workspace_root) if source_output_dir else "unknown"),
        "project_name": card.get("project_name", "unknown"),
        "scenario_type": card.get("scenario_type", []),
        "runtime_arch": card.get("runtime_arch", "unknown"),
        "runtime_core": card.get("runtime_core", "unknown"),
        "soc_vendor": card.get("soc_vendor", "unknown"),
        "soc": card.get("soc", "unknown"),
        "board": card.get("board", "unknown"),
        "kernel": infer_kernel(card, item["cases"]),
        "system_type": infer_system_type(card, item["cases"]),
        "primary_focus": card.get("primary_focus", []),
        "validation_status": card.get("validation_status", {}),
        "statistics": card.get("statistics", {}),
        "quality": card.get("quality", {}),
    }
    if not redact_local_paths:
        summary["source_meta_dir"] = str(meta_dir)
        summary["source_output_dir"] = source_output_dir
    return {
        key: value for key, value in summary.items() if value is not None
    }


def write_registry(out: Path, scenarios: list[dict[str, Any]], redact_local_paths: bool = False) -> None:
    workspace_root = Path.cwd()
    summaries = [scenario_summary(item, workspace_root, redact_local_paths) for item in scenarios]
    registry = {
        "schema_version": 1,
        "generated_at": now_iso(),
        "scenario_count": len(summaries),
        "scenarios": summaries,
    }
    dump_yaml(out / "00_scenario_registry/scenario_registry.yaml", registry)
    rows = []
    for item in summaries:
        rows.append(
            [
                item["scenario_id"],
                ", ".join(listify(item.get("scenario_type"))),
                item.get("runtime_arch", "unknown"),
                item.get("runtime_core", "unknown"),
                item.get("soc_vendor", "unknown"),
                item.get("soc", "unknown"),
                item.get("board", "unknown"),
                item.get("system_type", "unknown"),
                ", ".join(listify(item.get("primary_focus"))) or "unknown",
            ]
        )
    (out / "00_scenario_registry/scenario_comparison_matrix.md").write_text(
        "\n".join(
            [
                "# Scenario Comparison Matrix",
                "",
                markdown_table(
                    ["scenario_id", "scenario_type", "runtime_arch", "runtime_core", "soc_vendor", "soc", "board", "system_type", "focus"],
                    rows,
                ),
                "",
            ]
        ),
        encoding="utf-8",
    )


def case_bucket_values(case: dict[str, Any], key: str) -> list[str]:
    values = listify(case.get(key))
    return values or ["unknown"]


def write_case_indexes(out: Path, cases: list[dict[str, Any]]) -> None:
    write_jsonl(out / "01_normalized_cases/cases.jsonl", cases)
    for bucket_name, key in [
        ("cases_by_phase", "porting_phase"),
        ("cases_by_subsystem", "subsystem"),
        ("cases_by_reuse_level", "reuse_level"),
    ]:
        bucket_dir = out / "01_normalized_cases" / bucket_name
        bucket_dir.mkdir(parents=True, exist_ok=True)
        buckets: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for case in cases:
            for value in case_bucket_values(case, key):
                buckets[slugify(str(value))].append(case)
        for value, rows in sorted(buckets.items()):
            write_jsonl(bucket_dir / f"{value}.jsonl", rows)


def dedupe_pattern_ids(patterns: list[dict[str, Any]], fragments: list[dict[str, Any]]) -> None:
    seen: set[str] = set()
    remap: dict[tuple[str, str], str] = {}
    for pattern in patterns:
        old_id = str(pattern.get("pattern_id") or "PATTERN-UNKNOWN")
        scenario_id = str(pattern.get("scenario_id") or "unknown")
        new_id = old_id
        if new_id in seen:
            new_id = f"{old_id}-{slugify(scenario_id).upper()}"
            suffix = 2
            while new_id in seen:
                new_id = f"{old_id}-{slugify(scenario_id).upper()}-{suffix}"
                suffix += 1
            pattern["pattern_id"] = new_id
        seen.add(new_id)
        remap[(scenario_id, old_id)] = new_id
    if not remap:
        return
    for fragment in fragments:
        scenario_id = str(fragment.get("scenario_id") or "unknown")
        source_patterns = []
        changed = False
        for pattern_id in fragment.get("source_patterns") or []:
            mapped = remap.get((scenario_id, str(pattern_id)), str(pattern_id))
            source_patterns.append(mapped)
            changed = changed or mapped != pattern_id
        if changed:
            fragment["source_patterns"] = source_patterns


def annotate_global_records(cases: list[dict[str, Any]], fragments: list[dict[str, Any]]) -> None:
    for case in cases:
        scenario_id = str(case.get("scenario_id") or "unknown")
        case_id = str(case.get("case_id") or "CASE-UNKNOWN")
        case.setdefault("evidence_ref", f"case:{scenario_id}::{case_id}")
    for fragment in fragments:
        fragment["global_method_fragment_id"] = global_method_fragment_id(fragment)


def normalize_pattern_evidence(patterns: list[dict[str, Any]], cases: list[dict[str, Any]]) -> None:
    cases_by_id = {str(case.get("case_id")): case for case in cases}
    for pattern in patterns:
        for evidence in pattern.get("supporting_evidence") or []:
            if not isinstance(evidence, dict):
                continue
            case = cases_by_id.get(str(evidence.get("case_id") or ""))
            if case:
                evidence["evidence_type"] = case.get("evidence_type", "unknown")
                evidence["evidence_level"] = case.get("evidence_level", "unknown")
                evidence["evidence_strength"] = case.get("evidence_strength", "unknown")
                continue
            canonical = canonical_evidence_type(evidence.get("evidence_level"))
            if canonical:
                evidence["evidence_type"] = canonical
                evidence["evidence_level"] = canonical


def write_machine_readable_patterns(out: Path, patterns: list[dict[str, Any]], fragments: list[dict[str, Any]], anti_patterns: list[dict[str, Any]]) -> None:
    write_jsonl(out / "02_patterns/pattern_candidates.jsonl", patterns)
    write_jsonl(out / "02_patterns/method_fragments.jsonl", fragments)
    write_jsonl(out / "02_patterns/anti_patterns.jsonl", anti_patterns)


def fragments_by_statement(fragments: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for fragment in fragments:
        statement = str(fragment.get("statement") or "").strip()
        if not statement:
            continue
        groups[statement].append(fragment)
    return groups


def scenario_values_by_id(scenarios: list[dict[str, Any]], scenario_ids: list[str], field: str) -> set[str]:
    cards = {str(item["card"].get("scenario_id")): item["card"] for item in scenarios}
    values: set[str] = set()
    for scenario_id in scenario_ids:
        values.update(listify(cards.get(scenario_id, {}).get(field)))
    return {value for value in values if value and value != "unknown"}


def method_title(statement: str, fragments: list[dict[str, Any]]) -> str:
    method_id = str(fragments[0].get("method_fragment_id") or "")
    if method_id in DEFAULT_GUARDRAIL_METHOD_IDS:
        return DEFAULT_GUARDRAIL_METHOD_IDS[method_id]
    first_sentence = statement.split(".", 1)[0].strip()
    return first_sentence[:80] or "Untitled Method"


def case_search_text(case: dict[str, Any]) -> str:
    evidence = case.get("evidence") if isinstance(case.get("evidence"), dict) else {}
    binary_assets = evidence.get("binary_assets") if isinstance(evidence.get("binary_assets"), list) else []
    dirty_files = evidence.get("dirty_files") if isinstance(evidence.get("dirty_files"), list) else []
    binary_paths = [asset.get("path") for asset in binary_assets if isinstance(asset, dict)]
    dirty_paths = [item.get("file_path") for item in dirty_files if isinstance(item, dict)]
    return text_blob(
        case.get("case_id"),
        case.get("title"),
        case.get("porting_phase"),
        case.get("subsystem"),
        case.get("problem_type"),
        case.get("evidence_type"),
        case.get("evidence_level"),
        case.get("reuse_level"),
        case.get("rule"),
        binary_paths,
        dirty_paths,
    )


def case_scope_text(case: dict[str, Any]) -> str:
    return text_blob(
        case.get("case_id"),
        case.get("title"),
        case.get("porting_phase"),
        case.get("subsystem"),
        case.get("problem_type"),
    )


def case_matches_conditional_spec(case: dict[str, Any], spec: dict[str, Any]) -> bool:
    mode = str(spec.get("match_mode") or "")
    text = case_search_text(case)
    if any(str(keyword).lower() in text for keyword in spec.get("exclude_keywords", [])):
        return False
    if mode == "hdf_driver":
        scope = case_scope_text(case)
        return any(token in scope for token in ["hdf", "hcs", "hcb"])
    if mode == "riscv_route":
        scope = text_blob(case.get("case_id"), case.get("porting_phase"), case.get("subsystem"), case.get("problem_type"))
        route_tokens = [
            "build",
            "toolchain",
            "musl",
            "sdk",
            "product",
            "vendor_product",
            "product_board",
            "board_soc",
            "board_vendor",
            "riscv64",
            "riscv_build",
        ]
        return any(token in scope for token in route_tokens)
    if mode == "boot_scope":
        scope = case_scope_text(case)
        return any(token in scope for token in ["boot", "firmware", "provenance", "partition", "reboot"])
    if mode == "binary_provenance":
        evidence = case.get("evidence") if isinstance(case.get("evidence"), dict) else {}
        has_binary_assets = bool(evidence.get("binary_assets"))
        return has_binary_assets or any(str(keyword).lower() in text for keyword in spec.get("keywords", []))
    if mode == "dirty_workspace":
        evidence = case.get("evidence") if isinstance(case.get("evidence"), dict) else {}
        has_dirty_files = bool(evidence.get("dirty_files"))
        scope = text_blob(case.get("case_id"), case.get("title"), case.get("porting_phase"), case.get("subsystem"), case.get("problem_type"), case.get("reuse_level"), case.get("rule"))
        return has_dirty_files or any(str(keyword).lower() in scope for keyword in spec.get("keywords", []))
    return any(str(keyword).lower() in text for keyword in spec.get("keywords", []))


def build_universal_meta_methods(scenarios: list[dict[str, Any]], fragments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    used_ids: set[str] = set()
    for statement, rows in sorted(fragments_by_statement(fragments).items()):
        scenario_ids = sorted({str(row.get("scenario_id") or "unknown") for row in rows})
        if len(scenario_ids) < FORMAL_UNIVERSAL_MIN_SCENARIOS:
            continue

        source_cases = sorted({str(case_id) for row in rows for case_id in row.get("source_case_ids") or []})
        source_patterns = sorted({str(pattern_id) for row in rows for pattern_id in row.get("source_patterns") or []})
        method_ids = {str(row.get("method_fragment_id") or "") for row in rows}
        by_design = not source_cases and not source_patterns and method_ids <= set(DEFAULT_GUARDRAIL_METHOD_IDS)
        scenario_types = scenario_values_by_id(scenarios, scenario_ids, "scenario_type")
        soc_vendors = scenario_values_by_id(scenarios, scenario_ids, "soc_vendor")

        if by_design:
            promotion_level = "universal_by_design"
            evidence_strength = "pipeline_guardrail"
        elif len(source_cases) + len(source_patterns) >= 2 and (len(scenario_types) >= 2 or len(soc_vendors) >= 2):
            promotion_level = "universal_from_evidence"
            evidence_strength = "high"
        else:
            promotion_level = "universal_candidate"
            evidence_strength = "medium"

        base_id = "META-" + slugify(f"{promotion_level}-{method_title(statement, rows)}").upper()
        method_id = base_id
        suffix = 2
        while method_id in used_ids:
            method_id = f"{base_id}-{suffix}"
            suffix += 1
        used_ids.add(method_id)

        records.append(
            {
                "method_id": method_id,
                "title": method_title(statement, rows),
                "promotion_level": promotion_level,
                "supporting_patterns": source_patterns,
                "supporting_cases": source_cases,
                "scenario_ids": scenario_ids,
                "applicability": sorted(scenario_types) or ["cross_scenario_governance"],
                "non_applicability": ["source-derived universal"] if by_design else [],
                "evidence_strength": evidence_strength,
                "statement": statement,
                "risks": sorted({risk for row in rows for risk in listify(row.get("failure_modes"))}),
                "supporting_method_fragments": [global_method_fragment_id(row) for row in rows],
            }
        )
    return records


def build_conditional_methods(scenarios: list[dict[str, Any]], cases: list[dict[str, Any]], patterns: list[dict[str, Any]]) -> list[dict[str, Any]]:
    scenario_type_by_id = {str(item["card"].get("scenario_id")): set(listify(item["card"].get("scenario_type"))) for item in scenarios}
    pattern_ids_by_case_id: dict[str, set[str]] = defaultdict(set)
    for pattern in patterns:
        pattern_id = str(pattern.get("pattern_id") or "")
        if not pattern_id:
            continue
        for case_id in pattern.get("source_case_ids") or []:
            pattern_ids_by_case_id[str(case_id)].add(pattern_id)

    records: list[dict[str, Any]] = []
    for spec in CONDITIONAL_METHOD_SPECS:
        selected: list[dict[str, Any]] = []
        required_type = str(spec.get("required_scenario_type") or "")
        for case in cases:
            scenario_id = str(case.get("scenario_id") or "")
            if required_type and required_type not in scenario_type_by_id.get(scenario_id, set()):
                continue
            if case_matches_conditional_spec(case, spec):
                selected.append(case)
        scenario_ids = sorted({str(case.get("scenario_id") or "unknown") for case in selected})
        if len(selected) < 2 or len(scenario_ids) < 2:
            continue
        supporting_cases = sorted({str(case.get("case_id")) for case in selected if case.get("case_id")})
        supporting_patterns = sorted({pattern_id for case_id in supporting_cases for pattern_id in pattern_ids_by_case_id.get(case_id, set())})
        evidence_types = sorted({str(case.get("evidence_type") or case.get("evidence_level") or "unknown") for case in selected})
        records.append(
            {
                "method_id": spec["method_id"],
                "title": spec["title"],
                "promotion_level": "conditional",
                "derivation": "conditional_from_evidence",
                "supporting_patterns": supporting_patterns,
                "supporting_cases": supporting_cases,
                "scenario_ids": scenario_ids,
                "applicability": list(spec.get("applicability", [])),
                "non_applicability": list(spec.get("non_applicability", [])),
                "evidence_strength": "high" if len(scenario_ids) >= 3 else "medium_high",
                "evidence_types": evidence_types,
                "statement": spec["statement"],
                "quality_gates": list(spec.get("quality_gates", [])),
                "risks": [
                    "over-generalizing vendor-specific behavior",
                    "promoting dirty or binary records as source proof",
                    "claiming validation from commit/file evidence alone",
                ],
            }
        )
    return records


def build_meta_methods(scenarios: list[dict[str, Any]], fragments: list[dict[str, Any]], cases: list[dict[str, Any]], patterns: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    universal_methods = build_universal_meta_methods(scenarios, fragments)
    conditional_methods = build_conditional_methods(scenarios, cases, patterns)
    return universal_methods + conditional_methods, conditional_methods


def write_universal_methods(out: Path, scenarios: list[dict[str, Any]], fragments: list[dict[str, Any]], cases: list[dict[str, Any]], patterns: list[dict[str, Any]]) -> list[dict[str, Any]]:
    meta_methods, conditional_methods = build_meta_methods(scenarios, fragments, cases, patterns)
    write_jsonl(out / "02_patterns/meta_methods.jsonl", meta_methods)
    write_jsonl(out / "02_patterns/conditional_methods.jsonl", conditional_methods)
    lines = [
        "# Universal Methods",
        "",
        f"Promotion rule: formal reusable methods require at least {FORMAL_UNIVERSAL_MIN_SCENARIOS} distinct scenario_id values and must declare one of these promotion levels: `{', '.join(PROMOTION_LEVELS)}`.",
        "",
        "`universal_by_design` means a pipeline guardrail, not a case-derived source fix. `universal_from_evidence` requires source cases or patterns plus cross-scenario diversity.",
        "",
    ]
    by_design = [record for record in meta_methods if record["promotion_level"] == "universal_by_design"]
    from_evidence = [record for record in meta_methods if record["promotion_level"] == "universal_from_evidence"]
    candidates = [record for record in meta_methods if record["promotion_level"] == "universal_candidate"]
    if by_design:
        lines.extend(["## Universal By Design / Pipeline Guardrails", ""])
        for record in by_design:
            lines.extend(
                [
                    f"### universal_by_design: {record['title']}",
                    "",
                    f"- Method: {record['statement']}",
                    f"- Support: {', '.join(record['scenario_ids'])}.",
                    f"- Traceability: {', '.join(record['supporting_method_fragments'])}.",
                    "- Source cases/patterns: none; this is a pipeline guardrail.",
                    "- Constraint: Do not present this as a case-derived OpenHarmony source fix.",
                    "",
                ]
            )
    if from_evidence:
        lines.extend(["## Universal From Evidence", ""])
        for record in from_evidence:
            lines.extend(
                [
                    f"### universal_from_evidence: {record['title']}",
                    "",
                    f"- Method: {record['statement']}",
                    f"- Support: {', '.join(record['scenario_ids'])}.",
                    f"- source_case_ids: {', '.join(record['supporting_cases']) or 'none'}",
                    f"- source_patterns: {', '.join(record['supporting_patterns']) or 'none'}",
                    f"- Applicability: {', '.join(record['applicability'])}.",
                    "",
                ]
            )
    else:
        lines.extend(
            [
                "## Universal From Evidence",
                "",
                "No `universal_from_evidence` methods were promoted. Shared case-derived rules remain conditional or universal_candidate until they have sufficient source case/pattern traceability and scenario diversity.",
                "",
            ]
        )
    if not by_design and not from_evidence:
        lines.extend(
            [
                "## No Formal Universal Methods Promoted",
                "",
                f"Input scenario count is {len(scenarios)}. Evidence is insufficient for formal universal promotion; keep these as universal_candidate until at least {FORMAL_UNIVERSAL_MIN_SCENARIOS} scenarios support them.",
                "",
            ]
        )
    lines.extend(["## Universal Candidates Not Promoted", ""])
    if candidates:
        for record in candidates:
            lines.append(f"- `{record['method_id']}`: {record['statement']} Support: {', '.join(record['scenario_ids'])}.")
    else:
        lines.append("- No additional `universal_candidate` methods met the cross-scenario support threshold.")
    (out / "02_patterns/universal_methods.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return conditional_methods


def write_conditional_patterns(out: Path, patterns: list[dict[str, Any]], cases: list[dict[str, Any]], conditional_methods: list[dict[str, Any]] | None = None) -> None:
    cases_by_id = {case.get("case_id"): case for case in cases}
    groups = {
        "ARM-primary board/SoC": [],
        "RISC-V-primary distribution": [],
        "heterogeneous_aux_core": [],
        "HDF / driver chains": [],
        "Binary / prebuilt governance": [],
        "Dirty workspace governance": [],
        "Other conditional patterns": [],
    }
    for pattern in patterns:
        source_cases = [cases_by_id.get(case_id) for case_id in pattern.get("source_case_ids") or []]
        text = " ".join(
            [
                str(pattern.get("hypothesis") or ""),
                " ".join(" ".join(listify(case.get("scenario_type"))) for case in source_cases if case),
                " ".join(" ".join(listify(case.get("subsystem"))) for case in source_cases if case),
                " ".join(" ".join(listify(case.get("problem_type"))) for case in source_cases if case),
            ]
        ).lower()
        target = "Other conditional patterns"
        if "board_soc_arm_primary" in text or "arm_primary" in text:
            target = "ARM-primary board/SoC"
        if "riscv_primary" in text:
            target = "RISC-V-primary distribution"
        if "heterogeneous_aux_core" in text or "auxiliary" in text:
            target = "heterogeneous_aux_core"
        if any(token in text for token in ["hdf", "audio", "driver"]):
            target = "HDF / driver chains"
        if any(token in text for token in ["binary", "prebuilt", "firmware"]):
            target = "Binary / prebuilt governance"
        if "dirty" in text:
            target = "Dirty workspace governance"
        groups[target].append(pattern)

    lines = [
        "# Conditional Patterns",
        "",
        "Conditional patterns keep applicability and non-applicability explicit; they are not formal universal methods.",
        "",
        "## Cross-Scenario Conditional Methods",
        "",
    ]
    if conditional_methods:
        for method in conditional_methods:
            lines.extend(
                [
                    f"### {method.get('method_id')}: {method.get('title')}",
                    "",
                    f"- promotion_level: `{method.get('promotion_level')}`",
                    f"- derivation: `{method.get('derivation', 'conditional_from_evidence')}`",
                    f"- Statement: {method.get('statement')}",
                    f"- Scenario support: {', '.join(listify(method.get('scenario_ids')))}",
                    f"- Supporting cases: {', '.join(listify(method.get('supporting_cases')))}",
                    f"- Supporting patterns: {', '.join(listify(method.get('supporting_patterns'))) or 'none'}",
                    f"- Applicability: {', '.join(listify(method.get('applicability')))}",
                    f"- Non-applicability: {', '.join(listify(method.get('non_applicability')))}",
                    "- Quality gates:",
                ]
            )
            for gate in listify(method.get("quality_gates")):
                lines.append(f"  - {gate}")
            lines.append("")
    else:
        lines.extend(["- No cross-scenario conditional methods were generated.", ""])
    for title, rows in groups.items():
        lines.extend([f"## {title}", ""])
        if rows:
            for pattern in rows:
                lines.append(f"- `{pattern.get('pattern_id')}`: {pattern.get('hypothesis')} Evidence: {pattern.get('evidence_strength', 'unknown')}; confirmation_required={pattern.get('needs_cross_scenario_confirmation')}.")
        else:
            lines.append("- No candidate in current inputs.")
        lines.append("")
    (out / "02_patterns/conditional_patterns.md").write_text("\n".join(lines), encoding="utf-8")


def write_scenario_specific(out: Path, cases: list[dict[str, Any]]) -> None:
    inventory_lines = [
        "# Case Inventory By Scenario",
        "",
        "All normalized cases are listed here as concrete scenario records. This is an inventory, not a promotion decision.",
        "",
    ]
    for scenario_id in sorted({str(case.get("scenario_id")) for case in cases}):
        inventory_lines.extend([f"## {scenario_id}", ""])
        for case in [row for row in cases if str(row.get("scenario_id")) == scenario_id]:
            inventory_lines.append(
                f"- `{case.get('case_id')}`: {case.get('title')} reuse_level={case.get('reuse_level')}; evidence_type={case.get('evidence_type', case.get('evidence_level', 'unknown'))}."
            )
        inventory_lines.append("")
    (out / "02_patterns/case_inventory_by_scenario.md").write_text("\n".join(inventory_lines).rstrip() + "\n", encoding="utf-8")

    lines = [
        "# Scenario-Specific Knowledge",
        "",
        "Only cases whose normalized `reuse_level` is exactly `scenario_specific` are listed here. Conditional, risk_only, and workaround records remain in the case inventory and their own pattern views.",
        "",
    ]
    selected = [case for case in cases if case.get("reuse_level") == "scenario_specific"]
    for case in selected:
        lines.append(f"- `{case.get('scenario_id')}` / `{case.get('case_id')}`: {case.get('title')}.")
    if not selected:
        lines.append("- No normalized cases currently use `reuse_level=scenario_specific`.")
    (out / "02_patterns/scenario_specific_knowledge.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_anti_patterns(out: Path, anti_patterns: list[dict[str, Any]]) -> None:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in anti_patterns:
        grouped[str(item.get("anti_pattern_id") or "unknown")].append(item)
    lines = [
        "# Anti-Patterns",
        "",
        "Anti-patterns may be supported by one scenario when the risk and prevention rule are explicit.",
        "",
    ]
    for anti_id, rows in sorted(grouped.items()):
        sample = rows[0]
        scenario_ids = sorted({str(row.get("scenario_id")) for row in rows})
        lines.extend(
            [
                f"## {anti_id}",
                "",
                f"- Risk: {sample.get('risk', 'unknown')}",
                f"- Description: {sample.get('description', 'unknown')}",
                f"- Prevention: {sample.get('prevention', 'unknown')}",
                f"- Scenario support: {', '.join(scenario_ids)}",
                "",
            ]
        )
    (out / "02_patterns/anti_patterns.md").write_text("\n".join(lines), encoding="utf-8")


def write_additional_pattern_views(out: Path, cases: list[dict[str, Any]], patterns: list[dict[str, Any]]) -> None:
    arch_lines = ["# Architecture-Specific Patterns", ""]
    vendor_lines = ["# SoC/Vendor-Specific Patterns", ""]
    workaround_lines = ["# Workaround Patterns", ""]
    for case in cases:
        scenario_type = ", ".join(listify(case.get("scenario_type")))
        arch_lines.append(f"- `{case.get('case_id')}` scenario_type={scenario_type}; phase={', '.join(listify(case.get('porting_phase')))}; rule={case.get('rule')}")
        applicability = ", ".join(listify(case.get("applicability"))) or "unknown"
        vendor_lines.append(f"- `{case.get('scenario_id')}` / `{case.get('case_id')}` applicability={applicability}; subsystem={', '.join(listify(case.get('subsystem')))}.")
        if case.get("reuse_level") == "workaround" or "workaround" in " ".join(listify(case.get("problem_type"))).lower():
            workaround_lines.append(f"- `{case.get('case_id')}`: {case.get('title')} Keep as workaround, not best practice.")
    if len(workaround_lines) == 2:
        workaround_lines.append("- No explicit workaround cases in current normalized inputs.")
    (out / "02_patterns/architecture_specific_patterns.md").write_text("\n".join(arch_lines) + "\n", encoding="utf-8")
    (out / "02_patterns/soc_vendor_specific_patterns.md").write_text("\n".join(vendor_lines) + "\n", encoding="utf-8")
    (out / "02_patterns/workaround_patterns.md").write_text("\n".join(workaround_lines) + "\n", encoding="utf-8")


def runbook_doc(title: str, applicability: str, inputs: list[str], outputs: list[str], steps: list[str], evidence: list[str], selector: list[str], failures: list[str], gates: list[str], example: str, anti_example: str) -> list[str]:
    lines = [
        f"# {title}",
        "",
        "## Applicability",
        "",
        applicability,
        "",
        "## Inputs",
        "",
    ]
    lines.extend(f"- {item}" for item in inputs)
    lines.extend(["", "## Outputs", ""])
    lines.extend(f"- {item}" for item in outputs)
    lines.extend(["", "## Workflow", ""])
    lines.extend(f"{idx}. {item}" for idx, item in enumerate(steps, start=1))
    lines.extend(["", "## Evidence Requirements", ""])
    lines.extend(f"- {item}" for item in evidence)
    lines.extend(["", "## Case Selector", ""])
    lines.extend(f"- {item}" for item in selector)
    lines.extend(["", "## Failure Handling", ""])
    lines.extend(f"- {item}" for item in failures)
    lines.extend(["", "## Quality Gates", ""])
    lines.extend(f"- {item}" for item in gates)
    lines.extend(
        [
            "",
            "## Example",
            "",
            example,
            "",
            "## Anti-Example",
            "",
            anti_example,
        ]
    )
    return lines


def write_methodology(out: Path, scenario_count: int, cases: list[dict[str, Any]]) -> None:
    phases = Counter(phase for case in cases for phase in listify(case.get("porting_phase")))
    subsystems = Counter(sub for case in cases for sub in listify(case.get("subsystem")))
    methodology = [
        "# OpenHarmony Porting General Method",
        "",
        f"Evidence base: {scenario_count} scenario(s), {len(cases)} normalized case(s).",
        "",
        "1. Freeze scenario scope from task_profile.yaml before interpreting commits.",
        "2. Separate initial import, post-import commits, dirty workspace records, and binary/prebuilt assets.",
        "3. Build cases only from evidence-bound commit/file/diff records, then attach dirty/binary records as risk when they match.",
        "4. Promote rules conservatively: single-scenario outputs stay conditional, scenario_specific, or universal_candidate.",
        "5. Keep validation separate from evidence extraction; build/boot/runtime/test passed requires logs.",
        "",
        "## Dominant Phases",
        "",
    ]
    methodology.extend(f"- {key}: {value}" for key, value in phases.most_common())
    methodology.extend(["", "## Dominant Subsystems", ""])
    methodology.extend(f"- {key}: {value}" for key, value in subsystems.most_common())
    (out / "03_methodology/openharmony_porting_general_method.md").write_text("\n".join(methodology) + "\n", encoding="utf-8")

    runbooks = {
        "board_soc_porting_runbook.md": runbook_doc(
            "Board/SoC Porting Runbook",
            "Use this runbook for board product enablement, SoC BSP binding, vendor product configuration, kernel/DTS alignment, and board-specific HDF or driver chains.",
            ["scenario_registry.yaml", "cases.jsonl filtered by product_board_binding or board/vendor subsystem", "pattern_candidates.jsonl for source case linkage"],
            ["A scoped board/SoC binding checklist", "A list of source-backed cases and risk-only records", "Non-applicability notes for other architecture shapes"],
            [
                "Freeze scenario_id, scenario_type, board, SoC, vendor, runtime architecture, kernel, and system_type.",
                "Select product, board, vendor, and SoC cases before selecting subsystem cases.",
                "Trace BUILD.gn, productdefine, config.gni, config.json, DTS, HDF/HCS/HCB, and vendor policy files as one binding graph.",
                "Attach dirty workspace and binary/prebuilt records as risks unless they are converted to clean commits or documented generated outputs.",
                "Keep validation status separate from source evidence and record any missing build, boot, runtime, or test logs.",
            ],
            ["At least one product or vendor config path for a product binding claim.", "At least one board or SoC path for board/SoC binding.", "Evidence_ref links for every reusable case."],
            ["scenario_type contains board_soc_arm_primary", "subsystem contains product_board_soc or product_board_vendor_binding", "problem_type contains product_config_alignment or board_soc_binding"],
            ["If product and board paths disagree, keep the case conditional and document the conflict.", "If only binaries or generated files exist, classify as provenance or runtime risk.", "If validation logs are missing, keep validation unknown."],
            ["No registry-external scenario_type labels.", "No single repo is treated as the whole board port.", "No auxiliary-core evidence is promoted as primary runtime architecture."],
            "A T113-like board case should connect vendor config, board BUILD.gn, SoC defconfig or DTS, and subsystem HDF/audio/WiFi evidence before being used as reusable board guidance.",
            "A single driver import or bootloader directory is not enough to claim a reusable board/SoC porting method.",
        ),
        "architecture_porting_runbook.md": runbook_doc(
            "Architecture Porting Runbook",
            "Use this runbook when a case touches ARM-primary versus RISC-V-primary scope, architecture toolchains, runtime routes, SDK/NDK paths, musl namespaces, or auxiliary RISC-V firmware.",
            ["scenario_registry.yaml", "cases.jsonl filtered by scenario_type and architecture-related subsystems", "meta_methods.jsonl for universal_by_design and conditional architecture methods"],
            ["Architecture scope decision", "Architecture route checklist", "Auxiliary-core non-promotion notes"],
            [
                "Read scenario_type from the registry and treat it as scope authority.",
                "For RISC-V-primary work, require product route, build variables, toolchain/SDK paths, libc or musl runtime paths, and package/image rules.",
                "For ARM-primary work, keep RISC-V coprocessor, DSP, ARISC, or firmware evidence in heterogeneous_aux_core scope.",
                "Review third_party and prebuilts evidence for architecture-specific imports, whitelists, and runtime assumptions.",
                "Document whether the rule is conditional, universal_candidate, or risk_only; do not use bare universal.",
            ],
            ["Registry scenario_type and runtime_arch.", "Source paths proving build/runtime changes.", "Evidence_strength and validation status kept separate."],
            ["scenario_type contains riscv_primary_distribution", "subsystem contains riscv_build_toolchain_runtime or build_riscv", "rule mentions SDK, toolchain, musl, runtime, or product route"],
            ["If ARM and RISC-V labels conflict, stop promotion and emit a scope conflict.", "If a change only touches a whitelist, classify as board-specific accommodation.", "If prebuilt toolchains are imported, require provenance governance."],
            ["RISC-V-primary support spans build, runtime, product, and board/vendor evidence.", "Auxiliary firmware never proves RISC-V-primary OpenHarmony runtime.", "Validation pass is never inferred from source diffs."],
            "A RISC-V board route can become a conditional method when product config, board/vendor config, build target, SDK/toolchain, and musl/runtime evidence all appear across multiple RISC-V-primary scenarios.",
            "A C906 firmware blob inside an ARM-primary board is not evidence for RISC-V-primary OpenHarmony distribution support.",
        ),
        "driver_hdf_porting_runbook.md": runbook_doc(
            "Driver/HDF Porting Runbook",
            "Use this runbook for HDF, audio, camera/media, display/GPU, USB, WiFi, SDIO, kernel driver, HAL, and vendor policy integration.",
            ["cases.jsonl filtered by hdf_integration or driver_enablement", "conditional_methods.jsonl for HDF driver, media/camera HDF, and WiFi/SDIO clusters", "evidence_trace_index.jsonl for pattern-to-case and meta-method links"],
            ["Driver/HDF chain map", "Generated asset and binary separation notes", "Runtime validation requirements"],
            [
                "Select all cases in the subsystem chain before interpreting any single driver patch.",
                "Connect driver implementation, Kconfig/Makefile or BUILD.gn, board DTS, SoC glue, vendor HCS/HCB or policy, and product component wiring.",
                "Separate source-level driver fixes from generated archives, firmware, modules, or local dirty files.",
                "Map missing runtime validation into explicit test requirements instead of proof.",
                "Promote only conditional methods unless cross-scenario source cases prove a broader method.",
            ],
            ["Driver or HAL source path.", "Board/SoC binding path.", "Vendor/product configuration path.", "Generated/binary asset risk record when present."],
            ["subsystem contains hdf_audio, hdf_camera_media, wifi_sdio, network_wifi_sdio, display_gpu_g2d, usb_camera, or kernel_driver_dts_defconfig"],
            ["If only generated HCB/HCS binary output is present, mark source proof missing.", "If a kernel fix lacks board/vendor binding, keep it subsystem-local.", "If runtime behavior is claimed, require logs or validation_status."],
            ["Every conditional driver method has supporting_cases from at least two scenarios.", "Binary and dirty evidence stays risk-only.", "Non-applicability lists architecture or vendor limits."],
            "An HDF audio case is useful when it links codec or driver source, board ALSA glue, vendor audio policy/HCS, product configuration, and validation requirements.",
            "A codec patch alone, a delivered .ko file alone, or a generated HCB alone is not a full HDF/driver enablement method.",
        ),
        "binary_prebuilt_governance.md": runbook_doc(
            "Binary/Prebuilt Governance",
            "Use this runbook whenever firmware, boot assets, kernel modules, object archives, prebuilts, generated HDF assets, toolchains, or proprietary libraries appear.",
            ["binary asset records from cases.jsonl", "evidence_index.jsonl", "risk_taxonomy.yaml", "anti_patterns.jsonl"],
            ["Binary/prebuilt inventory", "Provenance and redistribution risk notes", "Regeneration or replacement requirements"],
            [
                "Record path, hash, architecture, possible usage, source or upstream origin, license, and redistribution status.",
                "Identify whether the asset is source input, generated output, runtime dependency, firmware payload, or toolchain prebuilt.",
                "Link the asset to source cases only as risk or dependency evidence unless source regeneration is proven.",
                "For boot/firmware assets, separate partition policy and editable config from binary payload provenance.",
                "Document validation requirements for runtime-loaded modules or firmware.",
            ],
            ["sha256 or equivalent stable identifier.", "Path and owning scenario_id.", "Usage and provenance status.", "Evidence_ref back to the case record."],
            ["evidence_type is dirty_or_binary_only", "case evidence has binary_assets", "rule mentions firmware, prebuilt, generated, .ko, .bin, .o, .a, or hcb"],
            ["If provenance is unknown, keep the record risk_only.", "If redistribution is unclear, block release-grade promotion.", "If generated output lacks generator path, require regeneration evidence."],
            ["No binary import becomes a source fix.", "No initial import is treated as proof of origin.", "No runtime validation is inferred from asset presence."],
            "A boot firmware record can support a conditional governance method when it lists the asset, hash, board boot stage, regeneration or signing status, and validation gap.",
            "A committed proprietary library without source, license, or usage notes must not be promoted as reusable source-porting guidance.",
        ),
        "dirty_workspace_governance.md": runbook_doc(
            "Dirty Workspace Governance",
            "Use this runbook for uncommitted local modifications, generated outputs, local scripts, temporary build changes, and files that explain current porting state but are not clean source history.",
            ["dirty file evidence embedded in cases.jsonl", "evidence_index.jsonl", "anti_patterns.jsonl", "scenario_registry.yaml"],
            ["Dirty workspace inventory", "Conversion plan to clean evidence", "Risk-only or workaround classification"],
            [
                "List every dirty file with path, repo, relation, and associated case or subsystem.",
                "Classify each record as local experiment, generated output, workaround, missing commit, or provenance risk.",
                "Do not merge dirty files into committed history evidence; keep them attached as risk notes.",
                "When a dirty change is required for a fix, create a clean patch or commit before promotion.",
                "Re-run validation after dirty records are converted or intentionally excluded.",
            ],
            ["Dirty file path and repo.", "Reason for relation to the case.", "Conversion or exclusion decision.", "Validation status after conversion."],
            ["case evidence has dirty_files", "rule mentions dirty, local, workaround, generated, or uncommitted"],
            ["If dirty evidence conflicts with committed evidence, prefer committed evidence and record the conflict.", "If dirty files are generated, identify the generator.", "If dirty files are required but uncommitted, block reusable source-fix promotion."],
            ["Dirty records are never counted as committed source proof.", "Workarounds remain workaround or risk_only until validated.", "Generated outputs are not accepted without generator traceability."],
            "A local kernel build script change may explain why a board currently builds, but it remains dirty governance evidence until captured as a clean commit or documented patch.",
            "Do not fold a dirty defconfig or generated binary into a conditional method as if it were reviewed source history.",
        ),
    }
    for filename, lines in runbooks.items():
        (out / "03_methodology" / filename).write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_global_kb(out: Path, cases: list[dict[str, Any]], patterns: list[dict[str, Any]], fragments: list[dict[str, Any]], anti_patterns: list[dict[str, Any]], meta_methods: list[dict[str, Any]]) -> None:
    evidence_rows = []
    for case in cases:
        evidence_rows.append(
            {
                "scenario_id": case.get("scenario_id"),
                "case_id": case.get("case_id"),
                "evidence_ref": case.get("evidence_ref"),
                "source_case_path": case.get("source_case_path"),
                "evidence": case.get("evidence", {}),
            }
        )
    write_jsonl(out / "04_global_kb/evidence_index.jsonl", evidence_rows)
    traces = []
    cases_by_id = {case.get("case_id"): case for case in cases}
    patterns_by_id = {pattern.get("pattern_id"): pattern for pattern in patterns}
    trace_seq = 0

    def next_trace_id(prefix: str) -> str:
        nonlocal trace_seq
        trace_seq += 1
        return f"TRACE-{prefix}-{trace_seq:05d}"

    for pattern in patterns:
        for case_id in pattern.get("source_case_ids") or []:
            case = cases_by_id.get(case_id)
            traces.append(
                {
                    "trace_id": next_trace_id("PATTERN-CASE"),
                    "trace_type": "pattern_to_case",
                    "pattern_id": pattern.get("pattern_id"),
                    "case_id": case_id,
                    "scenario_id": case.get("scenario_id") if case else pattern.get("scenario_id"),
                    "evidence_ref": evidence_ref_for_case(case, case_id),
                }
            )
    for fragment in fragments:
        global_fragment_id = fragment.get("global_method_fragment_id") or global_method_fragment_id(fragment)
        for pattern_id in fragment.get("source_patterns") or []:
            pattern = patterns_by_id.get(pattern_id)
            traces.append(
                {
                    "trace_id": next_trace_id("METHOD-PATTERN"),
                    "trace_type": "method_to_pattern",
                    "method_fragment_id": fragment.get("method_fragment_id"),
                    "global_method_fragment_id": global_fragment_id,
                    "pattern_id": pattern_id,
                    "scenario_id": fragment.get("scenario_id"),
                    "pattern_exists": bool(pattern),
                }
            )
        for case_id in fragment.get("source_case_ids") or []:
            case = cases_by_id.get(case_id)
            traces.append(
                {
                    "trace_id": next_trace_id("METHOD-CASE"),
                    "trace_type": "method_to_case",
                    "method_fragment_id": fragment.get("method_fragment_id"),
                    "global_method_fragment_id": global_fragment_id,
                    "case_id": case_id,
                    "scenario_id": fragment.get("scenario_id"),
                    "case_exists": bool(case),
                    "evidence_ref": evidence_ref_for_case(case, case_id),
                }
            )
    for method in meta_methods:
        method_id = str(method.get("method_id") or "")
        if not method_id:
            continue
        for pattern_id in method.get("supporting_patterns") or []:
            pattern = patterns_by_id.get(pattern_id)
            traces.append(
                {
                    "trace_id": next_trace_id("META-METHOD-PATTERN"),
                    "trace_type": "meta_method_to_pattern",
                    "meta_method_id": method_id,
                    "pattern_id": pattern_id,
                    "scenario_id": pattern.get("scenario_id") if pattern else None,
                    "pattern_exists": bool(pattern),
                }
            )
        for case_id in method.get("supporting_cases") or []:
            case = cases_by_id.get(case_id)
            traces.append(
                {
                    "trace_id": next_trace_id("META-METHOD-CASE"),
                    "trace_type": "meta_method_to_case",
                    "meta_method_id": method_id,
                    "case_id": case_id,
                    "scenario_id": case.get("scenario_id") if case else None,
                    "case_exists": bool(case),
                    "evidence_ref": evidence_ref_for_case(case, case_id),
                }
            )
    write_jsonl(out / "04_global_kb/evidence_trace_index.jsonl", traces)
    (out / "04_global_kb/path_module_ontology.md").write_text(
        "# Path / Module Ontology\n\n- `device/board`: board binding and hardware configuration.\n- `device/soc`: SoC BSP, UAPI, drivers and platform glue.\n- `vendor`: product/vendor configuration and generated HDF assets.\n- `drivers`: HDF and kernel-facing driver code.\n- `third_party`: imported runtime/build dependencies and architecture compatibility work.\n- `prebuilts`: toolchain/runtime prebuilts requiring provenance governance.\n",
        encoding="utf-8",
    )
    problem_taxonomy = {
        "schema_version": 1,
        "problem_types": sorted({ptype for case in cases for ptype in listify(case.get("problem_type"))}),
    }
    risk_taxonomy = {
        "schema_version": 1,
        "risks": sorted({str(item.get("risk")) for item in anti_patterns if item.get("risk")}),
    }
    dump_yaml(out / "04_global_kb/problem_taxonomy.yaml", problem_taxonomy)
    dump_yaml(out / "04_global_kb/risk_taxonomy.yaml", risk_taxonomy)
    (out / "04_global_kb/glossary.md").write_text(
        "# Glossary\n\n- universal_candidate: a rule that may become universal after cross-scenario confirmation.\n- conditional: reusable only under explicit architecture, SoC/vendor, subsystem, or project-shape conditions.\n- scenario_specific: concrete knowledge retained for one board/SoC/project context.\n- anti_pattern: a recurring way knowledge can be polluted or misclassified.\n",
        encoding="utf-8",
    )


def generated_skill_doc(
    title: str,
    selector: str,
    focus: list[str],
    gates: list[str],
    scenario_count: int,
    non_applicability: list[str] | None = None,
    examples: list[str] | None = None,
    anti_examples: list[str] | None = None,
    method_refs: list[str] | None = None,
) -> str:
    lines = [
        f"# {title}",
        "",
        "This generated skill draft is evidence-bound. The installable Codex Skill package is emitted under `meta_skill_pack/`.",
        "",
        "## Applicability",
        "",
        selector,
        "",
        "## Non-Applicability",
        "",
    ]
    lines.extend(f"- {item}" for item in (non_applicability or ["Do not use this skill when the registry scope or evidence class does not match the selector.", "Do not use this skill to infer validation success without logs."]))
    lines.extend([
        "",
        "## Input Contract",
        "",
        "- `00_scenario_registry/scenario_registry.yaml` defines scenario IDs, scenario_type, runtime_arch, SoC/vendor, board, kernel, and validation status.",
        "- `01_normalized_cases/cases.jsonl` provides canonical `evidence_type`, `evidence_strength`, and registry-scoped `scenario_type` values.",
        "- `02_patterns/meta_methods.jsonl`, `conditional_methods.jsonl`, `pattern_candidates.jsonl`, `anti_patterns.jsonl`, and `method_fragments.jsonl` provide promotion and traceability inputs.",
        "- `04_global_kb/evidence_trace_index.jsonl` links methods and patterns back to compact evidence references.",
        "- `meta_skill_pack/references/conditional_method_index.md` maps installable skills to conditional method IDs.",
        "- `meta_skill_pack/examples/case_selector_examples.yaml` provides minimal selector examples.",
        "",
        "## Output Contract",
        "",
        "- A scoped answer that names the selected scenario_id, scenario_type, and evidence class.",
        "- A case or method selection list with `case_id`, `pattern_id`, `method_id`, and `evidence_ref` where available.",
        "- Explicit validation status for build, boot, runtime, and tests; unknown must remain unknown.",
        "- Non-applicability notes when a rule is architecture-, board-, vendor-, or subsystem-specific.",
        "",
        "## Case Selector",
        "",
        selector,
        "",
        "## Method References",
        "",
    ])
    lines.extend(f"- `{item}`" for item in (method_refs or ["02_patterns/meta_methods.jsonl", "02_patterns/conditional_methods.jsonl"]))
    lines.extend([
        "",
        "## Cross-Scenario Relationship",
        "",
        "- Single-scenario pipeline runs produce `07_meta_inputs`; the cross-scenario aggregator normalizes and promotes those compact records.",
        "- This skill uses cross-scenario methods only after checking registry scope, case selectors, and evidence trace rows.",
        "- When installed outside the output tree, keep a copy of the meta output path or pass it explicitly in the task request.",
        "",
        "## Installed Use",
        "",
        "- Install with `bash meta_skill_pack/install.sh` from a generated meta output directory.",
        "- Invoke the installed skill by naming the task scope and the meta output directory in the Codex request.",
        "- Re-run validation after editing any generated Skill, reference, schema, or conditional method file.",
        "",
        "## Workflow",
        "",
        "1. Freeze scenario scope from the registry before reading cases.",
        "2. Select candidate cases by `scenario_type`, `applicability`, `porting_phase`, `subsystem`, and `problem_type`.",
        "3. Prefer `conditional_methods.jsonl` for cross-scenario conditional rules before falling back to single-scenario pattern lists.",
        "4. Follow evidence references into case or pattern records; keep dirty and binary records separate from committed source proof.",
        "5. Apply anti-pattern checks before promoting a rule or using it as a reusable fix.",
        "6. Preserve validation unknowns unless build, boot, runtime, or test logs prove success.",
        "",
        "## Evidence Rules",
        "",
        "- `evidence_type` and `evidence_level` must describe the evidence source class, not confidence.",
        "- `evidence_strength` must describe confidence only.",
        "- `universal_by_design` is a pipeline guardrail, not a source-fix method.",
        "- `conditional` methods require explicit applicability and non-applicability.",
        "- Dirty files, binaries, prebuilts, generated assets, and initial imports are risk or provenance records until source/regeneration evidence exists.",
        "",
        "## Focus Areas",
        "",
    ])
    lines.extend(f"- {item}" for item in focus)
    lines.extend(["", "## Failure Gates", ""])
    lines.extend(f"- {item}" for item in gates)
    lines.extend(
        [
            "",
            "## Quality Checklist",
            "",
            "- Scenario labels are registry-defined; synthesized labels stay in `scenario_shape`.",
            "- Every reusable statement names supporting cases, patterns, or method fragments.",
            "- Cross-scenario methods list scenario support and non-applicability.",
            "- Binary and dirty evidence are not counted as committed source proof.",
            "- Validation claims are backed by logs or explicit validation_status fields.",
            "",
            "## Examples",
            "",
        ]
    )
    lines.extend(f"- {item}" for item in (examples or ["Select a conditional method, list supporting case IDs, and keep validation unknown when logs are absent."]))
    lines.extend(["", "## Anti-Examples", ""])
    lines.extend(f"- {item}" for item in (anti_examples or ["Do not treat a single generated file, binary asset, or dirty workspace edit as a reusable source fix."]))
    lines.extend(
        [
            "",
            "## Tool Commands",
            "",
            "```bash",
            "python3 tools/validate_meta_output.py --out <openharmony_porting_meta_output>",
            "bash tools/run_cross_scenario_aggregator.sh --input <porting_knowledge_output> --out <openharmony_porting_meta_output>",
            "```",
            "",
            "## Minimum Test Commands",
            "",
            "```bash",
            "test -x <openharmony_porting_meta_output>/meta_skill_pack/install.sh",
            "python3 tools/validate_meta_output.py --out <openharmony_porting_meta_output>",
            "python3 -m json.tool <openharmony_porting_meta_output>/meta_skill_pack/schemas/meta_method.schema.json >/dev/null",
            "```",
            "",
            f"Current scenario count at generation time: `{scenario_count}`.",
        ]
    )
    return "\n".join(lines) + "\n"


def skill_pack_doc(name: str, description: str, selector: str, focus: list[str], gates: list[str], scenario_count: int) -> str:
    spec = skill_specs().get(name, {})
    body = generated_skill_doc(
        name.replace("_", " ").title(),
        selector,
        focus,
        gates,
        scenario_count,
        list(spec.get("non_applicability", [])),
        list(spec.get("examples", [])),
        list(spec.get("anti_examples", [])),
        list(spec.get("method_refs", [])),
    )
    return "\n".join(
        [
            "---",
            f"name: {name}",
            f"description: {description}",
            "---",
            "",
            body,
        ]
    )


def skill_specs() -> dict[str, dict[str, Any]]:
    return {
        "universal_openharmony_porting": {
            "description": "Apply evidence-bound OpenHarmony porting governance across multiple scenarios without over-promoting rules.",
            "selector": "Use this when the task is cross-scenario method extraction, validation, promotion review, or quality gating.",
            "focus": [
                "universal_by_design guardrails: evidence-class separation, scenario scope authority, and validation separation.",
                "universal_from_evidence only when `meta_methods.jsonl` supplies source cases or patterns across enough diverse scenarios.",
                "conditional dispatch into ARM-primary, RISC-V-primary, or heterogeneous auxiliary-core skills.",
            ],
            "gates": [
                "Do not use `promotion_level=universal`; choose universal_by_design or universal_from_evidence.",
                "Do not infer build, boot, runtime, or test pass from commit/file/diff evidence alone.",
                "Do not use generated single-scenario skill text as promotion evidence.",
            ],
            "non_applicability": [
                "Single board debugging where no cross-scenario method or promotion decision is needed.",
                "Runtime validation claims without validation_status or logs.",
            ],
            "examples": [
                "Use `META-CONDITIONAL-HDF-DRIVER-MULTIREPO-CHAIN` when several scenarios show HDF driver cases with driver and vendor configuration evidence.",
                "Use `universal_by_design` methods only as guardrails before selecting conditional source methods.",
            ],
            "anti_examples": [
                "Do not call evidence-class separation a case-derived source fix.",
                "Do not merge ARM-primary and RISC-V-primary evidence into an unlabeled universal rule.",
            ],
            "method_refs": [
                "META-CONDITIONAL-HDF-DRIVER-MULTIREPO-CHAIN",
                "META-CONDITIONAL-WIFI-SDIO-RUNTIME-CHAIN",
                "META-CONDITIONAL-RISCV-BUILD-RUNTIME-ROUTE",
                "META-CONDITIONAL-BINARY-PREBUILT-PROVENANCE",
                "META-CONDITIONAL-DIRTY-WORKSPACE-GOVERNANCE",
            ],
        },
        "arm_primary_board_soc": {
            "description": "Review ARM-primary OpenHarmony board/SoC porting cases with auxiliary-core separation.",
            "selector": "Use when `scenario_type` contains `board_soc_arm_primary` or the case concerns ARM board, SoC, product, vendor, HDF, DTS, or boot binding.",
            "focus": [
                "Product, board, vendor, and SoC binding chains.",
                "Driver/HDF/HCS/DTS integration and generated asset separation.",
                "Boot firmware provenance and auxiliary-core non-promotion.",
            ],
            "gates": [
                "Do not collapse `heterogeneous_aux_core` into RISC-V-primary runtime scope.",
                "Do not treat binary boot assets as source fixes.",
                "Require registry-defined scenario_type labels only.",
            ],
            "non_applicability": [
                "RISC-V-primary distribution route work without ARM-primary board scope.",
                "Auxiliary firmware analysis that lacks board/product binding evidence.",
            ],
            "examples": [
                "Select T113 board cases by `board_soc_arm_primary`, then link product/vendor config to HDF, WiFi, DTS, or boot cases.",
                "Keep a synthesized shape such as ARM-primary plus auxiliary core in `scenario_shape`, not as a new registry type.",
            ],
            "anti_examples": [
                "Do not treat an auxiliary RISC-V firmware blob as the OpenHarmony runtime architecture.",
                "Do not call a single board DTS patch the full board/SoC port.",
            ],
            "method_refs": [
                "META-CONDITIONAL-HDF-DRIVER-MULTIREPO-CHAIN",
                "META-CONDITIONAL-WIFI-SDIO-RUNTIME-CHAIN",
                "META-CONDITIONAL-BOOT-FIRMWARE-PROVENANCE",
                "META-CONDITIONAL-BINARY-PREBUILT-PROVENANCE",
                "META-CONDITIONAL-DIRTY-WORKSPACE-GOVERNANCE",
            ],
        },
        "riscv_primary_distribution": {
            "description": "Review RISC-V-primary OpenHarmony distribution porting cases.",
            "selector": "Use when `scenario_type` contains `riscv_primary_distribution` or the case involves RISC-V runtime architecture, product route, SDK/toolchain, musl, kernel, or board/vendor integration.",
            "focus": [
                "RISC-V build/runtime/toolchain routing.",
                "Product, board, vendor, and SoC binding for RISC-V boards.",
                "HDF, WiFi/SDIO, camera/media, display/GPU, boot, and binary governance under RISC-V-primary scope.",
            ],
            "gates": [
                "Do not promote one vendor board workaround as universal RISC-V behavior.",
                "Do not mix evidence_type and evidence_strength vocabularies.",
                "Keep dirty scripts and prebuilts as risk records until committed or validated.",
            ],
            "non_applicability": [
                "ARM-primary board ports with only auxiliary RISC-V firmware.",
                "Binary-only toolchain or firmware imports without source route evidence.",
            ],
            "examples": [
                "Use the RISC-V build/runtime conditional method when product, board/vendor, build variables, SDK/toolchain, and musl/runtime cases line up.",
                "Classify whitelist-only fixes as conditional board accommodations unless more architecture evidence exists.",
            ],
            "anti_examples": [
                "Do not infer RISC-V runtime support from a prebuilt toolchain alone.",
                "Do not promote one SoC vendor workaround as a general RISC-V distribution rule.",
            ],
            "method_refs": [
                "META-CONDITIONAL-RISCV-BUILD-RUNTIME-ROUTE",
                "META-CONDITIONAL-WIFI-SDIO-RUNTIME-CHAIN",
                "META-CONDITIONAL-MEDIA-CAMERA-HDF-CHAIN",
                "META-CONDITIONAL-BINARY-PREBUILT-PROVENANCE",
                "META-CONDITIONAL-DIRTY-WORKSPACE-GOVERNANCE",
            ],
        },
        "heterogeneous_aux_core": {
            "description": "Review auxiliary-core evidence inside non-RISC-V-primary OpenHarmony scenarios.",
            "selector": "Use when `scenario_type` contains `heterogeneous_aux_core`, or when RISC-V firmware, DSP, ARISC, C906, or coprocessor evidence appears inside another primary runtime.",
            "focus": [
                "Auxiliary firmware and coprocessor evidence classification.",
                "Primary runtime scope protection.",
                "Firmware provenance, binary governance, and non-applicability notes.",
            ],
            "gates": [
                "Do not classify auxiliary RISC-V firmware as RISC-V-primary OpenHarmony runtime.",
                "Do not convert firmware presence into build/boot/runtime validation.",
                "Keep scenario_shape separate from registry-defined scenario_type.",
            ],
            "non_applicability": [
                "Primary RISC-V OpenHarmony distribution porting.",
                "Board/SoC product binding that does not involve auxiliary-core evidence.",
            ],
            "examples": [
                "Record C906, DSP, ARISC, or other coprocessor evidence as auxiliary scope when the primary runtime remains ARM.",
                "Attach auxiliary firmware assets to binary/prebuilt governance until provenance and validation are known.",
            ],
            "anti_examples": [
                "Do not move a board into RISC-V-primary scope because an auxiliary firmware file is RISC-V.",
                "Do not treat firmware presence as proof of runtime feature validation.",
            ],
            "method_refs": [
                "META-CONDITIONAL-BOOT-FIRMWARE-PROVENANCE",
                "META-CONDITIONAL-BINARY-PREBUILT-PROVENANCE",
                "META-CONDITIONAL-DIRTY-WORKSPACE-GOVERNANCE",
            ],
        },
    }


def write_generated_skills(out: Path, scenario_count: int) -> None:
    specs = skill_specs()
    filenames = {
        "universal_openharmony_porting": "universal_openharmony_porting_skill.md",
        "arm_primary_board_soc": "arm_primary_board_soc_skill.md",
        "riscv_primary_distribution": "riscv_primary_distribution_skill.md",
        "heterogeneous_aux_core": "heterogeneous_aux_core_skill.md",
    }
    for name, spec in specs.items():
        text = generated_skill_doc(
            name.replace("_", " ").title(),
            str(spec["selector"]),
            list(spec["focus"]),
            list(spec["gates"]),
            scenario_count,
            list(spec.get("non_applicability", [])),
            list(spec.get("examples", [])),
            list(spec.get("anti_examples", [])),
        )
        (out / "05_generated_skills" / filenames[name]).write_text(text, encoding="utf-8")


def write_meta_skill_pack(out: Path, scenario_count: int, conditional_methods: list[dict[str, Any]]) -> None:
    pack = out / "meta_skill_pack"
    specs = skill_specs()
    for name, spec in specs.items():
        skill_dir = pack / name
        skill_dir.mkdir(parents=True, exist_ok=True)
        (skill_dir / "SKILL.md").write_text(
            skill_pack_doc(
                name,
                str(spec["description"]),
                str(spec["selector"]),
                list(spec["focus"]),
                list(spec["gates"]),
                scenario_count,
            ),
            encoding="utf-8",
        )
    references = pack / "references"
    schemas = pack / "schemas"
    examples = pack / "examples"
    references.mkdir(parents=True, exist_ok=True)
    schemas.mkdir(parents=True, exist_ok=True)
    examples.mkdir(parents=True, exist_ok=True)
    (references / "meta_output_contract.md").write_text(
        "# Meta Output Contract\n\n"
        "- `scenario_type` in cases must be a subset of the registry scenario_type for the same scenario_id.\n"
        "- `evidence_type` and `evidence_level` use evidence source enums; `evidence_strength` uses strength enums.\n"
        "- `promotion_level` distinguishes `universal_by_design` from `universal_from_evidence`.\n"
        "- Cross-scenario conditional methods use `promotion_level=conditional` and `derivation=conditional_from_evidence`.\n"
        "- `evidence_trace_index.jsonl` includes explicit `meta_method_to_case` and `meta_method_to_pattern` rows for machine audit.\n"
        "- `scenario_shape` may hold synthesized labels, but registry-defined `scenario_type` must remain canonical.\n",
        encoding="utf-8",
    )
    method_index_lines = [
        "# Conditional Method Index",
        "",
        "This reference maps generated installable Skills to conditional methods in `../../02_patterns/conditional_methods.jsonl`.",
        "",
    ]
    method_refs_by_skill = {name: set(list(spec.get("method_refs", []))) for name, spec in specs.items()}
    for method in conditional_methods:
        method_id = str(method.get("method_id") or "")
        method_index_lines.extend(
            [
                f"## {method_id}",
                "",
                f"- Title: {method.get('title')}",
                f"- Scenario IDs: {', '.join(listify(method.get('scenario_ids')))}",
                f"- Supporting cases: {', '.join(listify(method.get('supporting_cases')))}",
                f"- Supporting patterns: {', '.join(listify(method.get('supporting_patterns')))}",
                f"- Skill refs: {', '.join(sorted(name for name, refs in method_refs_by_skill.items() if method_id in refs)) or 'unassigned'}",
                "",
            ]
        )
    (references / "conditional_method_index.md").write_text("\n".join(method_index_lines), encoding="utf-8")
    (schemas / "meta_method.schema.json").write_text(
        json.dumps(
            {
                "type": "object",
                "required": ["method_id", "title", "promotion_level", "scenario_ids", "statement"],
                "properties": {
                    "method_id": {"type": "string"},
                    "title": {"type": "string"},
                    "promotion_level": {"type": "string", "enum": PROMOTION_LEVELS},
                    "supporting_patterns": {"type": "array", "items": {"type": "string"}},
                    "supporting_cases": {"type": "array", "items": {"type": "string"}},
                    "scenario_ids": {"type": "array", "items": {"type": "string"}},
                    "statement": {"type": "string"},
                    "derivation": {"type": "string"},
                    "evidence_types": {"type": "array", "items": {"type": "string"}},
                    "quality_gates": {"type": "array", "items": {"type": "string"}},
                },
                "additionalProperties": True,
            },
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    (schemas / "case_selector.schema.json").write_text(
        json.dumps(
            {
                "type": "object",
                "required": ["scenario_type", "selectors"],
                "properties": {
                    "scenario_type": {"type": "array", "items": {"type": "string"}},
                    "selectors": {
                        "type": "object",
                        "properties": {
                            "subsystem": {"type": "array", "items": {"type": "string"}},
                            "problem_type": {"type": "array", "items": {"type": "string"}},
                            "method_refs": {"type": "array", "items": {"type": "string"}},
                        },
                        "additionalProperties": True,
                    },
                    "required_evidence": {"type": "array", "items": {"type": "string"}},
                    "validation_required_for_claims": {"type": "array", "items": {"type": "string"}},
                },
                "additionalProperties": True,
            },
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    (schemas / "scenario_registry.schema.json").write_text(
        json.dumps(
            {
                "type": "object",
                "required": ["scenarios"],
                "properties": {
                    "scenarios": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "required": ["scenario_id", "scenario_type"],
                            "properties": {
                                "scenario_id": {"type": "string"},
                                "scenario_type": {"type": "array", "items": {"type": "string"}},
                                "scenario_shape": {"type": "array", "items": {"type": "string"}},
                                "runtime_arch": {"type": "string"},
                                "soc_vendor": {"type": "string"},
                                "board": {"type": "string"},
                                "validation_status": {"type": "object"},
                            },
                            "additionalProperties": True,
                        },
                    }
                },
                "additionalProperties": True,
            },
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    (examples / "case_selector_examples.yaml").write_text(
        "universal_openharmony_porting:\n"
        "  scenario_type: [board_soc_arm_primary, riscv_primary_distribution]\n"
        "  selectors:\n"
        "    method_refs: [META-CONDITIONAL-HDF-DRIVER-MULTIREPO-CHAIN, META-CONDITIONAL-WIFI-SDIO-RUNTIME-CHAIN]\n"
        "  required_evidence: [supporting_cases, supporting_patterns, evidence_ref]\n"
        "arm_primary_board_soc:\n"
        "  scenario_type: [board_soc_arm_primary]\n"
        "  selectors:\n"
        "    subsystem: [hdf_audio, kernel_wifi_build, boot_firmware]\n"
        "    method_refs: [META-CONDITIONAL-HDF-DRIVER-MULTIREPO-CHAIN, META-CONDITIONAL-BOOT-FIRMWARE-PROVENANCE]\n"
        "riscv_primary_distribution:\n"
        "  scenario_type: [riscv_primary_distribution]\n"
        "  selectors:\n"
        "    problem_type: [riscv_build, product_board_binding, camera_usb_host_integration]\n"
        "    method_refs: [META-CONDITIONAL-RISCV-BUILD-RUNTIME-ROUTE, META-CONDITIONAL-MEDIA-CAMERA-HDF-CHAIN]\n"
        "heterogeneous_aux_core:\n"
        "  scenario_type: [heterogeneous_aux_core]\n"
        "  selectors:\n"
        "    subsystem: [boot_firmware]\n"
        "    method_refs: [META-CONDITIONAL-BINARY-PREBUILT-PROVENANCE]\n",
        encoding="utf-8",
    )
    (pack / "README.md").write_text(
        "# OpenHarmony Porting Meta Skill Pack\n\n"
        "Installable Codex Skill drafts generated from cross-scenario OpenHarmony porting evidence.\n\n"
        "Run `bash install.sh` from this directory to copy the skill folders into `${CODEX_HOME:-$HOME/.codex}/skills`.\n\n"
        "References:\n\n"
        "- `references/conditional_method_index.md` maps skills to conditional method IDs.\n"
        "- `schemas/*.schema.json` documents the expected method, registry, and selector contracts.\n"
        "- `examples/case_selector_examples.yaml` gives minimal selector templates.\n",
        encoding="utf-8",
    )
    install = pack / "install.sh"
    install.write_text(
        """#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEST="${CODEX_HOME:-${HOME}/.codex}/skills"
mkdir -p "${DEST}"

for skill in universal_openharmony_porting arm_primary_board_soc riscv_primary_distribution heterogeneous_aux_core; do
  mkdir -p "${DEST}/${skill}"
  cp -R "${SCRIPT_DIR}/${skill}/." "${DEST}/${skill}/"
  mkdir -p "${DEST}/${skill}/references" "${DEST}/${skill}/schemas" "${DEST}/${skill}/examples"
  cp -R "${SCRIPT_DIR}/references/." "${DEST}/${skill}/references/"
  cp -R "${SCRIPT_DIR}/schemas/." "${DEST}/${skill}/schemas/"
  cp -R "${SCRIPT_DIR}/examples/." "${DEST}/${skill}/examples/"
  echo "installed ${skill} -> ${DEST}/${skill}"
done
""",
        encoding="utf-8",
    )
    install.chmod(0o755)


def write_meta_report(out: Path, scenarios: list[dict[str, Any]], cases: list[dict[str, Any]], patterns: list[dict[str, Any]], anti_patterns: list[dict[str, Any]], conditional_methods: list[dict[str, Any]]) -> None:
    reuse_counts = Counter(str(case.get("reuse_level") or "unknown") for case in cases)
    scenario_count = len(scenarios)
    evidence_strength = "multi_scenario" if scenario_count >= 2 else "single_scenario"
    lines = [
        "# Cross-Scenario Meta Report",
        "",
        f"- Generated at: `{now_iso()}`",
        f"- Scenario count: `{scenario_count}`",
        f"- Normalized cases: `{len(cases)}`",
        f"- Pattern candidates: `{len(patterns)}`",
        f"- Anti-pattern records: `{len(anti_patterns)}`",
        f"- Conditional methods: `{len(conditional_methods)}`",
        f"- evidence_strength: `{evidence_strength}`",
        "",
        "## Promotion Classes",
        "",
        "- universal_by_design: pipeline guardrail supported by scenario coverage but not derived from source cases.",
        "- universal_from_evidence: requires at least 3 distinct scenario_id values, source cases or patterns, and scenario type or vendor diversity.",
        "- universal_candidate: plausible method fragment awaiting more scenarios.",
        "- conditional: applicable under explicit architecture, subsystem, vendor, system type or engineering-shape constraints.",
        "- scenario_specific: concrete board/SoC/vendor/module knowledge retained without promotion.",
        "- risk_only: evidence retained for risk/governance, not as a reusable fix.",
        "- anti_pattern: knowledge-pollution or evidence-governance failure mode with prevention.",
        "",
        "## Reuse Level Counts",
        "",
    ]
    for key in ["universal_candidate", "conditional", "scenario_specific", "risk_only", "workaround", "anti_pattern", "unknown"]:
        lines.append(f"- {key}: {reuse_counts.get(key, 0)}")
    if scenario_count < FORMAL_UNIVERSAL_MIN_SCENARIOS:
        lines.extend(
            [
                "",
                "## Universal Promotion Gate",
                "",
                f"No formal universal method is promoted because fewer than {FORMAL_UNIVERSAL_MIN_SCENARIOS} scenarios were supplied. Keep shared-looking rules as universal_candidate or conditional.",
            ]
        )
    lines.extend(
        [
            "",
            "## Generated Skill Pack",
            "",
            "- Installable drafts are under `meta_skill_pack/`.",
            "- Human-readable generated skill notes remain under `05_generated_skills/`.",
            "- Full case inventory is under `02_patterns/case_inventory_by_scenario.md`; `scenario_specific_knowledge.md` is reserved for exact `reuse_level=scenario_specific` cases.",
            "- Cross-scenario conditional methods are under `02_patterns/conditional_methods.jsonl` and summarized in `02_patterns/conditional_patterns.md`.",
        ]
    )
    (out / "meta_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_refine_placeholders(out: Path) -> None:
    log_dir = out / "_codex_logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    result = {
        "status": "skipped",
        "summary": "LLM refinement was not requested; deterministic cross-scenario aggregation output is retained.",
        "input_files_read": [],
        "output_files_written": [
            "_llm_refine_result.json",
            "_llm_refine.ndjson",
            "_codex_logs/09_cross_scenario_refine.skipped.json",
        ],
        "blocking_issues": [],
        "non_blocking_issues": ["Run run_cross_scenario_aggregator.sh with --llm-refine to request Codex text refinement."],
        "next_stage_inputs": ["openharmony_porting_meta_output"],
        "generated_at": now_iso(),
    }
    (out / "_llm_refine_result.json").write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    event = {
        "event": "llm_refine_skipped",
        "reason": "--llm-refine not requested",
        "generated_at": result["generated_at"],
    }
    (out / "_llm_refine.ndjson").write_text(json.dumps(event, ensure_ascii=False) + "\n", encoding="utf-8")
    (log_dir / "09_cross_scenario_refine.skipped.json").write_text(json.dumps(event, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", action="append", default=[], help="porting_knowledge_output or 07_meta_inputs path")
    parser.add_argument("--input-root", help="root containing */porting_knowledge_output/07_meta_inputs")
    parser.add_argument("--out", required=True, help="openharmony_porting_meta_output directory")
    parser.add_argument("--redact-local-paths", action="store_true", help="omit absolute local source paths from scenario_registry.yaml and result JSON")
    args = parser.parse_args()

    meta_dirs = find_inputs(args.input, args.input_root)
    scenarios = load_scenarios(meta_dirs)
    out = Path(args.out).resolve()
    reset_dir(out)
    for subdir in [
        "00_scenario_registry",
        "01_normalized_cases",
        "02_patterns",
        "03_methodology",
        "04_global_kb",
        "05_generated_skills",
        "meta_skill_pack",
    ]:
        (out / subdir).mkdir(parents=True, exist_ok=True)

    cases = [case for scenario in scenarios for case in scenario["cases"]]
    patterns = [pattern for scenario in scenarios for pattern in scenario["patterns"]]
    anti_patterns = [item for scenario in scenarios for item in scenario["anti_patterns"]]
    fragments = [fragment for scenario in scenarios for fragment in scenario["method_fragments"]]
    for case in cases:
        if case.get("reuse_level") == "universal":
            case["reuse_level"] = "universal_candidate"
    dedupe_pattern_ids(patterns, fragments)
    annotate_global_records(cases, fragments)
    normalize_pattern_evidence(patterns, cases)

    write_registry(out, scenarios, redact_local_paths=args.redact_local_paths)
    write_case_indexes(out, cases)
    write_machine_readable_patterns(out, patterns, fragments, anti_patterns)
    conditional_methods = write_universal_methods(out, scenarios, fragments, cases, patterns)
    meta_methods = read_jsonl(out / "02_patterns/meta_methods.jsonl")
    write_conditional_patterns(out, patterns, cases, conditional_methods)
    write_scenario_specific(out, cases)
    write_anti_patterns(out, anti_patterns)
    write_additional_pattern_views(out, cases, patterns)
    write_methodology(out, len(scenarios), cases)
    write_global_kb(out, cases, patterns, fragments, anti_patterns, meta_methods)
    write_generated_skills(out, len(scenarios))
    write_meta_skill_pack(out, len(scenarios), conditional_methods)
    write_meta_report(out, scenarios, cases, patterns, anti_patterns, conditional_methods)
    write_refine_placeholders(out)

    result = {
        "schema_version": 1,
        "status": "passed",
        "generated_at": now_iso(),
        "scenario_count": len(scenarios),
        "case_count": len(cases),
        "pattern_candidate_count": len(patterns),
        "anti_pattern_count": len(anti_patterns),
        "method_fragment_count": len(fragments),
        "meta_method_count": len(read_jsonl(out / "02_patterns/meta_methods.jsonl")),
        "conditional_method_count": len(conditional_methods),
        "input_meta_labels": [scenario_summary(scenario, Path.cwd(), redact_local_paths=True)["source_meta_dir_label"] for scenario in scenarios],
        "output_label": out.name,
    }
    if not args.redact_local_paths:
        result["input_meta_dirs"] = [str(path) for path in meta_dirs]
        result["output_dir"] = str(out)
    (out / "cross_scenario_result.json").write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
