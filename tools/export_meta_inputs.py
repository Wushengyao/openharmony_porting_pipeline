#!/usr/bin/env python3
"""Export one scenario's pipeline output as normalized cross-scenario inputs."""

from __future__ import annotations

import argparse
import csv
import json
import re
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml


REUSE_LEVELS = {
    "universal_candidate",
    "conditional",
    "scenario_specific",
    "risk_only",
    "anti_pattern",
    "workaround",
    "unknown",
}

ANTI_PATTERN_DEFS = [
    {
        "anti_pattern_id": "ANTI-FORCE-SYNC-AS-PORTING",
        "description": "Treating a force-sync SDK commit as reusable OpenHarmony porting experience.",
        "risk": "knowledge_base_pollution",
        "prevention": "Keep force-sync/import commits in rejected evidence unless subsystem-specific commit/file evidence proves an actual porting fix.",
    },
    {
        "anti_pattern_id": "ANTI-GITATTRIBUTES-ONLY-AS-SUBSYSTEM",
        "description": "Promoting a .gitattributes-only commit into a subsystem case.",
        "risk": "false_subsystem_case",
        "prevention": "Require subsystem source/config paths beyond .gitattributes before creating cases or method fragments.",
    },
    {
        "anti_pattern_id": "ANTI-DIRTY-AS-COMMITTED",
        "description": "Treating dirty workspace records as already committed project history.",
        "risk": "evidence_class_confusion",
        "prevention": "Preserve dirty_file_records separately and require clean commits or patches before calling the work historical porting evidence.",
    },
    {
        "anti_pattern_id": "ANTI-BINARY-IMPORT-AS-SOURCE-FIX",
        "description": "Presenting binary/prebuilt imports as source-level fixes.",
        "risk": "binary_provenance_blind_spot",
        "prevention": "Record path, sha256, architecture, provenance and redistribution risk, then separate binary governance from source adaptation rules.",
    },
    {
        "anti_pattern_id": "ANTI-RISCV-AUX-AS-PRIMARY",
        "description": "Treating RISC-V auxiliary firmware/context as evidence that OpenHarmony runs on RISC-V primary architecture.",
        "risk": "scope_misclassification",
        "prevention": "Use task_profile.yaml runtime_core and treat_riscv_as_primary_arch as authoritative unless a scope-change request is produced.",
    },
    {
        "anti_pattern_id": "ANTI-SINGLE-SCENARIO-AS-UNIVERSAL",
        "description": "Promoting a single-scenario case or generated skill directly to a universal OpenHarmony porting method.",
        "risk": "overgeneralization",
        "prevention": "Export single-scenario rules as universal_candidate or conditional only; require cross-scenario aggregation rules before promotion.",
    },
]


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def read_text(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8", errors="ignore")


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not path.exists():
        return rows
    with path.open(encoding="utf-8", errors="ignore") as f:
        for line in f:
            if not line.strip():
                continue
            try:
                obj = json.loads(line)
            except Exception:
                continue
            if isinstance(obj, dict):
                rows.append(obj)
    return rows


def count_csv_rows(path: Path) -> int:
    if not path.exists() or path.stat().st_size == 0:
        return 0
    with path.open(encoding="utf-8", errors="ignore", newline="") as f:
        try:
            return max(0, sum(1 for _ in csv.reader(f)) - 1)
        except Exception:
            return 0


def read_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8", errors="ignore")) or {}
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def dump_yaml(path: Path, data: dict[str, Any]) -> None:
    path.write_text(
        yaml.safe_dump(data, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )


def listify(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()]
    if isinstance(value, tuple):
        return [str(item) for item in value if str(item).strip()]
    text = str(value).strip()
    return [text] if text else []


def first_value(*values: Any, default: str = "unknown") -> Any:
    for value in values:
        if value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue
        if isinstance(value, (list, dict)) and not value:
            continue
        return value
    return default


def slugify(value: str) -> str:
    value = value.lower()
    value = value.replace("open harmony", "openharmony")
    value = re.sub(r"[^a-z0-9]+", "_", value)
    value = re.sub(r"_+", "_", value).strip("_")
    return value or "unknown"


def short_scenario_type_token(scenario_type: list[str]) -> str:
    tokens: list[str] = []
    if "board_soc_arm_primary" in scenario_type:
        tokens.append("arm_primary")
    if "riscv_primary_distribution" in scenario_type:
        tokens.append("riscv_primary")
    if "heterogeneous_aux_core" in scenario_type:
        tokens.append("aux_core")
    if not tokens and scenario_type:
        tokens.append(slugify(scenario_type[0])[:28])
    return "_".join(tokens) or "unknown_scenario"


def openharmony_token(version: str, project_name: str) -> str:
    candidates = [version, project_name]
    for candidate in candidates:
        text = str(candidate or "")
        match = re.search(r"(?:openharmony|oh)\s*([0-9]+)(?:[._-]([0-9]+))?", text, re.I)
        if match:
            major = match.group(1)
            minor = match.group(2)
            return f"oh{major}{minor or ''}"
        match = re.search(r"\b([0-9]+)\.([0-9]+)\b", text)
        if match and "harmony" in text.lower():
            return f"oh{match.group(1)}{match.group(2)}"
    return "oh_unknown"


def generate_scenario_id(card_seed: dict[str, Any]) -> str:
    hint = slugify(str(card_seed.get("scenario_id_hint") or card_seed.get("scenario_id") or ""))
    scenario_type = listify(card_seed.get("scenario_type"))
    type_token = short_scenario_type_token(scenario_type)
    version_token = openharmony_token(str(card_seed.get("openharmony_version") or ""), str(card_seed.get("project_name") or ""))
    runtime = slugify(str(card_seed.get("runtime_core") or card_seed.get("openharmony_runtime_core") or card_seed.get("runtime_arch") or "unknown"))
    identity = slugify(str(card_seed.get("board") or card_seed.get("soc") or card_seed.get("project_name") or "scenario"))
    if hint and hint not in {"unknown", "t113"} and len(hint.split("_")) >= 3:
        base = hint
    else:
        base = "_".join(token for token in [identity, version_token, runtime, type_token] if token and token != "unknown")
    base = re.sub(r"_+", "_", base).strip("_")
    if base in {"", "unknown", "t113"}:
        base = f"{identity}_{version_token}_{runtime}_{type_token}"
    return base[:96].strip("_")


def normalize_arch(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return "unknown"
    aliases = {
        "arm32": "armv7-a",
        "arm": "arm",
        "riscv": "riscv64",
    }
    return aliases.get(text.lower(), text)


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


def infer_kernel(value: Any, *context: Any) -> str:
    explicit = str(value or "").strip()
    if explicit and explicit.lower() != "unknown":
        return explicit
    text = text_blob(*context)
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


def infer_system_type(value: Any, *context: Any) -> str:
    explicit = str(value or "").strip()
    if explicit and explicit.lower() != "unknown":
        return explicit
    text = text_blob(*context)
    if re.search(r"\briscv[_-]?rich\b|\brich\b", text):
        return "standard_or_rich"
    if re.search(r"\bstandard\b", text):
        return "standard"
    if re.search(r"(^|[^a-z0-9])small([^a-z0-9]|$)|_small_defconfig|small_defconfig", text):
        return "small"
    if re.search(r"(^|[^a-z0-9])mini([^a-z0-9]|$)", text):
        return "mini"
    return "unknown"


def relative_to_cwd(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(Path.cwd().resolve()))
    except Exception:
        return str(path)


def statistics_from_outputs(out: Path, stats: dict[str, Any]) -> dict[str, Any]:
    keys = [
        "repo_count",
        "changed_repo_count",
        "commit_records_count",
        "initial_import_commit_count",
        "post_import_commit_count",
        "file_change_records_count",
        "binary_asset_records_count",
        "dirty_file_records_count",
    ]
    fallback_counts = {
        "commit_records_count": len(read_jsonl(out / "01_raw_records/commit_records.jsonl")),
        "file_change_records_count": len(read_jsonl(out / "01_raw_records/file_change_records.jsonl")),
        "dirty_file_records_count": len(read_jsonl(out / "01_raw_records/dirty_file_records.jsonl")),
        "binary_asset_records_count": count_csv_rows(out / "01_raw_records/binary_asset_records.csv"),
    }
    result: dict[str, Any] = {}
    for key in keys:
        if key in stats:
            result[key] = stats[key]
        elif key in fallback_counts:
            result[key] = fallback_counts[key]
        else:
            result[key] = "unknown"
    return result


def stage_status(out: Path, stage: str, default: str = "unknown") -> str:
    data = read_json(out / "_stage_results" / f"{stage}.json")
    status = str(data.get("status") or "").strip()
    return status if status else default


def final_audit_quality(out: Path) -> dict[str, Any]:
    result = read_json(out / "_stage_results/07_final_auditor.json")
    blocking_text = read_text(out / "06_audit/blocking_issues.md")
    non_blocking_text = read_text(out / "06_audit/non_blocking_issues.md")

    blocking_count = result.get("blocking_issue_count")
    if blocking_count is None:
        if "- None" in blocking_text:
            blocking_count = 0
        else:
            blocking_count = len([line for line in blocking_text.splitlines() if line.strip().startswith("- ")])
    non_blocking_count = result.get("non_blocking_issue_count")
    if non_blocking_count is None:
        non_blocking_count = len([line for line in non_blocking_text.splitlines() if line.strip().startswith("- ") and line.strip() != "- None"])

    if result.get("status") == "passed" and blocking_count == 0:
        audit_status = "passed_or_conditional"
    elif result.get("status"):
        audit_status = str(result.get("status"))
    else:
        audit_status = "unknown"
    return {
        "final_audit_status": audit_status,
        "blocking_issue_count": blocking_count,
        "non_blocking_issue_count": non_blocking_count,
    }


def build_validation_status(scenario_id: str, out: Path, focus: list[str]) -> dict[str, Any]:
    runtime_features: dict[str, Any] = {}
    for item in focus:
        key = slugify(item)
        if key in {"wifi", "audio", "hdf_audio", "bluetooth", "display", "camera"} or any(token in key for token in ["wifi", "audio", "hdf"]):
            runtime_features[key] = {"status": "unknown", "logs": []}
    if not runtime_features:
        runtime_features["general_runtime"] = {"status": "unknown", "logs": []}
    return {
        "schema_version": 1,
        "scenario_id": scenario_id,
        "build": {"status": "unknown", "logs": []},
        "boot": {"status": "unknown", "logs": []},
        "runtime_features": runtime_features,
        "tests": {"xts": {"status": "unknown", "logs": []}},
        "knowledge_extraction": {
            "raw_records": stage_status(out, "02_raw_record_extractor"),
            "statistics_qc": stage_status(out, "03_statistics_qc"),
            "semantic_analysis": stage_status(out, "04_semantic_analyzer"),
            "case_kb": stage_status(out, "05_case_kb_builder"),
            "final_audit": stage_status(out, "07_final_auditor"),
        },
        "notes": ["Do not infer runtime validation from commit evidence only."],
    }


def build_scenario_card(out: Path, task_profile: dict[str, Any], stats: dict[str, Any]) -> dict[str, Any]:
    identity = task_profile.get("task_identity") if isinstance(task_profile.get("task_identity"), dict) else {}
    scenario_type = listify(first_value(task_profile.get("scenario_type"), default=[]))
    focus = listify(first_value(task_profile.get("primary_focus"), task_profile.get("analysis_focus"), default=[]))
    project_name = str(first_value(task_profile.get("project_name"), task_profile.get("project_name_hint"), identity.get("task_name")))
    version = str(first_value(task_profile.get("openharmony_version"), task_profile.get("ohos_version")))
    runtime_core = str(first_value(task_profile.get("runtime_core"), task_profile.get("openharmony_runtime_core")))
    runtime_arch = normalize_arch(first_value(task_profile.get("runtime_arch"), task_profile.get("primary_cpu_arch"), runtime_core))
    auxiliary_cores = listify(task_profile.get("auxiliary_cores"))
    if not auxiliary_cores and str(task_profile.get("riscv_role") or "").lower() in {"auxiliary_core", "auxiliary", "firmware"}:
        auxiliary_cores = ["riscv"]
    card_seed = {
        "scenario_id": task_profile.get("scenario_id"),
        "scenario_id_hint": task_profile.get("scenario_id_hint"),
        "scenario_type": scenario_type,
        "openharmony_version": version,
        "runtime_core": runtime_core,
        "runtime_arch": runtime_arch,
        "project_name": project_name,
        "board": task_profile.get("board"),
        "soc": task_profile.get("soc"),
    }
    scenario_id = generate_scenario_id(card_seed)
    quality = final_audit_quality(out)
    kernel = infer_kernel(first_value(task_profile.get("kernel"), task_profile.get("kernel_type")), task_profile)
    system_type = infer_system_type(task_profile.get("system_type"), task_profile)
    card = {
        "schema_version": 1,
        "scenario_id": scenario_id,
        "source_output_dir": str(out),
        "source_output_label": scenario_id,
        "source_output_dir_relative": relative_to_cwd(out),
        "project_name": project_name,
        "openharmony_version": version,
        "scenario_type": scenario_type or ["unknown"],
        "runtime_arch": runtime_arch,
        "runtime_core": runtime_core,
        "auxiliary_cores": auxiliary_cores,
        "soc_vendor": str(first_value(task_profile.get("soc_vendor"), task_profile.get("vendor"))),
        "soc": str(first_value(task_profile.get("soc"), task_profile.get("chip"))),
        "board": str(first_value(task_profile.get("board"), task_profile.get("board_name"))),
        "kernel": kernel,
        "system_type": system_type,
        "primary_focus": focus,
        "statistics": statistics_from_outputs(out, stats),
        "validation_status": {
            "build": "unknown",
            "boot": "unknown",
            "runtime": "unknown",
            "tests": "unknown",
            "evidence_level": "commit_file_diff_only",
        },
        "quality": quality,
        "notes": [],
    }
    if "heterogeneous_aux_core" in scenario_type and runtime_core != "riscv":
        card["notes"].append("RISC-V is auxiliary context, not OpenHarmony primary runtime architecture.")
    if not focus:
        card["notes"].append("primary_focus is unknown because task_profile.yaml did not provide analysis_focus/primary_focus.")
    return card


def extract_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    if not text.startswith("---\n"):
        return {}, text
    end = text.find("\n---", 4)
    if end < 0:
        return {}, text
    raw = text[4:end]
    rest = text[end + 4 :]
    try:
        data = yaml.safe_load(raw) or {}
        return data if isinstance(data, dict) else {}, rest
    except Exception:
        return {}, rest


def section_text(text: str, name: str) -> str:
    pattern = re.compile(rf"^##\s+{re.escape(name)}\s*$", re.I | re.M)
    match = pattern.search(text)
    if not match:
        return ""
    start = match.end()
    next_match = re.search(r"^##\s+", text[start:], re.M)
    end = start + next_match.start() if next_match else len(text)
    return text[start:end].strip()


def first_heading(text: str) -> str:
    match = re.search(r"^#\s+(.+?)\s*$", text, re.M)
    return match.group(1).strip() if match else "unknown"


def extract_case_id(text: str, fallback: str) -> str:
    body = section_text(text, "Case ID")
    for line in body.splitlines():
        line = line.strip().strip("`")
        if line:
            return line
    return fallback


def extract_evidence(text: str) -> dict[str, Any]:
    evidence_section = section_text(text, "Evidence")
    code_match = re.search(r"```(?:yaml|yml)?\s*(.*?)```", evidence_section, re.S | re.I)
    raw = code_match.group(1).strip() if code_match else evidence_section
    parsed: dict[str, Any] = {}
    try:
        data = yaml.safe_load(raw) or {}
        if isinstance(data, dict):
            parsed = data.get("evidence") if isinstance(data.get("evidence"), dict) else data
    except Exception:
        parsed = {}
    commits = parsed.get("commits") if isinstance(parsed.get("commits"), list) else []
    files = parsed.get("files") if isinstance(parsed.get("files"), list) else []
    diffs = parsed.get("diffs") if isinstance(parsed.get("diffs"), list) else []
    dirty = (
        parsed.get("dirty_files")
        or parsed.get("dirty_records")
        or parsed.get("dirty")
        or []
    )
    binaries = (
        parsed.get("binary_assets")
        or parsed.get("binary_records")
        or parsed.get("binaries")
        or []
    )
    return {
        "commits": commits if isinstance(commits, list) else [],
        "files": files if isinstance(files, list) else [],
        "diffs": diffs if isinstance(diffs, list) else [],
        "dirty_files": dirty if isinstance(dirty, list) else [],
        "binary_assets": binaries if isinstance(binaries, list) else [],
    }


def infer_tokens(text: str, filename: str) -> dict[str, list[str] | str]:
    lower = f"{filename} {text}".lower()
    phases: list[str] = []
    subsystems: list[str] = []
    problem_types: list[str] = []
    applicability: list[str] = []

    def add(target: list[str], *values: str) -> None:
        for value in values:
            if value not in target:
                target.append(value)

    if any(token in lower for token in ["hdf", "audio", "codec", "dai", "dma", "hcs", "hcb"]):
        add(phases, "driver_enablement", "hdf_integration", "board_vendor_binding")
        add(subsystems, "audio", "hdf", "driver")
        add(problem_types, "multi_repo_binding", "driver_config_chain")
    if any(token in lower for token in ["wifi", "wpa", "supplicant", "dhcpcd", "wireless", "bk7236"]):
        add(phases, "driver_enablement", "runtime_integration")
        add(subsystems, "wifi", "network", "third_party")
        add(problem_types, "vendor_code_compatibility", "runtime_service_chain")
    if any(token in lower for token in ["boot", "firmware", "u-boot", "uboot", "spl", "brandy", "efex", "fex"]):
        add(phases, "boot_firmware", "board_vendor_binding")
        add(subsystems, "bootloader", "firmware")
        add(problem_types, "binary_provenance", "board_boot_binding")
    if any(token in lower for token in ["product", "board", "soc", "vendor", "build.gn", "bundle", "config.gni"]):
        add(phases, "board_vendor_binding", "build_integration")
        add(subsystems, "product", "board", "soc", "build")
        add(problem_types, "product_config_binding", "build_graph_integration")
    if any(token in lower for token in ["binary", "prebuilt", "sha256", ".bin", ".a", ".so"]):
        add(problem_types, "binary_prebuilt_governance")
    if any(token in lower for token in ["dirty", "workspace", "generated", ".cmd"]):
        add(problem_types, "dirty_workspace_governance")

    if "risc-v" in lower or "riscv" in lower:
        applicability.append("riscv_context")
    if "arm" in lower or "t113" in lower:
        applicability.append("arm_primary_board_soc")
    if not phases:
        phases.append("knowledge_extraction")
    if not subsystems:
        subsystems.append("general")
    if not problem_types:
        problem_types.append("porting_adaptation")
    return {
        "porting_phase": phases,
        "subsystem": subsystems,
        "problem_type": problem_types,
        "applicability": applicability,
    }


def evidence_level(evidence: dict[str, Any]) -> str:
    has_commit = bool(evidence.get("commits"))
    has_file = bool(evidence.get("files"))
    has_diff = bool(evidence.get("diffs"))
    has_dirty = bool(evidence.get("dirty_files"))
    has_binary = bool(evidence.get("binary_assets"))
    if has_commit and has_file and has_diff:
        return "commit_file_diff"
    if has_commit and has_file:
        return "commit_file"
    if has_dirty or has_binary:
        return "dirty_or_binary_only"
    return "unknown"


def normalize_reuse_level(value: Any, audit_notes: list[str], source: str) -> str:
    level = slugify(str(value or "conditional"))
    if level == "universal":
        audit_notes.append(f"{source}: downgraded reuse_level=universal to universal_candidate for single-scenario export.")
        return "universal_candidate"
    if level not in REUSE_LEVELS:
        audit_notes.append(f"{source}: unknown reuse_level={value!r}; using conditional.")
        return "conditional"
    return level


def normalize_confidence(value: Any) -> str:
    if isinstance(value, (int, float)):
        score = float(value)
        if score >= 0.90:
            return "high"
        if score >= 0.75:
            return "medium_high"
        if score >= 0.55:
            return "medium"
        return "low"
    text = str(value or "").lower()
    number = re.search(r"\b(?:0(?:\.\d+)?|1(?:\.0+)?)\b", text)
    if number:
        score = float(number.group(0))
        if score >= 0.90:
            return "high"
        if score >= 0.75:
            return "medium_high"
        if score >= 0.55:
            return "medium"
        return "low"
    if "high" in text and "medium" in text:
        return "medium_high"
    if "high" in text:
        return "high"
    if "low" in text:
        return "low"
    if "medium" in text:
        return "medium"
    return "unknown"


def normalize_evidence_type(value: Any, evidence: dict[str, Any]) -> str:
    text = slugify(str(value or ""))
    allowed = {
        "commit_file_diff",
        "commit_file",
        "log_verified",
        "dirty_or_binary_only",
        "operator_context",
        "unknown",
    }
    if text in allowed:
        return text
    return evidence_level(evidence)


def normalize_evidence_strength(value: Any, confidence: str, evidence_type_value: str) -> str:
    text = slugify(str(value or ""))
    if text in {"high", "medium", "low"}:
        return text
    if confidence in {"high", "medium_high"} and evidence_type_value in {"commit_file_diff", "log_verified"}:
        return "high"
    if confidence in {"high", "medium_high", "medium"}:
        return "medium"
    return "low"


def unknownish(value: Any) -> bool:
    return value is None or value == "" or value == [] or value == "unknown"


def normalize_cases(out: Path, card: dict[str, Any], audit_notes: list[str]) -> list[dict[str, Any]]:
    cases_dir = out / "04_knowledge_base/cases"
    rows: list[dict[str, Any]] = []
    for idx, path in enumerate(sorted(cases_dir.glob("*.md")), start=1):
        raw_text = read_text(path)
        frontmatter, body = extract_frontmatter(raw_text)
        title = str(first_value(frontmatter.get("title"), first_heading(body), path.stem))
        case_id = str(first_value(frontmatter.get("case_id"), extract_case_id(body, f"{card['scenario_id'].upper()}-CASE-{idx:03d}")))
        evidence = extract_evidence(body)
        inferred = infer_tokens(body, path.name)
        rule = str(first_value(frontmatter.get("rule"), section_text(body, "Reusable Rule").splitlines()[0] if section_text(body, "Reusable Rule") else "unknown"))
        reuse_level = normalize_reuse_level(frontmatter.get("reuse_level"), audit_notes, str(path.relative_to(out)))
        if reuse_level == "unknown":
            reuse_level = "conditional"
        confidence = normalize_confidence(first_value(frontmatter.get("confidence"), section_text(body, "Confidence")))
        evidence_type_value = normalize_evidence_type(
            first_value(frontmatter.get("evidence_type"), frontmatter.get("evidence_level"), evidence_level(evidence)),
            evidence,
        )
        evidence_strength_value = normalize_evidence_strength(
            frontmatter.get("evidence_strength"),
            confidence,
            evidence_type_value,
        )
        row = {
            "schema_version": 1,
            "case_id": case_id,
            "scenario_id": card["scenario_id"],
            "source_case_path": str(path.relative_to(out)),
            "title": title,
            "scenario_type": listify(first_value(frontmatter.get("scenario_type"), card.get("scenario_type"), default=[])),
            "porting_phase": listify(first_value(frontmatter.get("porting_phase"), inferred["porting_phase"], default=[])),
            "subsystem": listify(first_value(frontmatter.get("subsystem"), inferred["subsystem"], default=[])),
            "problem_type": listify(first_value(frontmatter.get("problem_type"), inferred["problem_type"], default=[])),
            "reuse_level": reuse_level,
            "evidence_level": str(first_value(frontmatter.get("evidence_level"), evidence_level(evidence))),
            "evidence_type": evidence_type_value,
            "evidence_strength": evidence_strength_value,
            "applicability": listify(first_value(frontmatter.get("applicability"), inferred["applicability"], default=[])),
            "non_applicability": listify(first_value(frontmatter.get("non_applicability"), ["riscv_primary_distribution"] if "board_soc_arm_primary" in card.get("scenario_type", []) else [], default=[])),
            "evidence": evidence,
            "rule": rule,
            "risks": listify(frontmatter.get("risks")),
            "confidence": confidence,
            "validation": {
                "build": "unknown",
                "boot": "unknown",
                "runtime_feature": "unknown",
                "test_logs": [],
            },
        }
        rows.append(row)
    return rows


def first_markdown_heading_or_sentence(text: str, fallback: str) -> str:
    heading = first_heading(text)
    if heading != "unknown":
        return heading
    for line in text.splitlines():
        line = line.strip().strip("- ")
        if line:
            return line[:240]
    return fallback


def build_pattern_candidates(out: Path, card: dict[str, Any], cases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for case in cases:
        base = slugify(str(case["case_id"]))
        pattern_id = f"PATTERN-{base.upper().replace('_', '-')}"
        if pattern_id in seen:
            pattern_id = f"{pattern_id}-{len(seen) + 1}"
        seen.add(pattern_id)
        scope = case.get("reuse_level") or "conditional"
        if scope == "universal":
            scope = "universal_candidate"
        rows.append(
            {
                "schema_version": 1,
                "pattern_id": pattern_id,
                "scenario_id": card["scenario_id"],
                "source_case_ids": [case["case_id"]],
                "candidate_scope": scope,
                "hypothesis": case.get("rule") or case.get("title") or "unknown",
                "supporting_evidence": [
                    {
                        "case_id": case["case_id"],
                        "evidence_level": case.get("evidence_level", "unknown"),
                        "source_case_path": case.get("source_case_path"),
                    }
                ],
                "evidence_strength": "single_scenario",
                "needs_cross_scenario_confirmation": scope != "scenario_specific",
                "promotion_constraints": [
                    "Requires support from additional scenario_id values before promotion beyond single-scenario scope."
                ],
                "counterexamples": [],
            }
        )
    patterns_dir = out / "04_knowledge_base/patterns"
    for path in sorted(patterns_dir.glob("*.md")):
        text = read_text(path)
        lower = text.lower()
        pattern_id = f"PATTERN-DOC-{slugify(path.stem).upper().replace('_', '-')}"
        if pattern_id in seen:
            pattern_id = f"{pattern_id}-{len(seen) + 1}"
        seen.add(pattern_id)
        scope = "risk_only" if any(token in lower for token in ["risk", "noise", "dirty", "binary", "prebuilt", "provenance"]) else "conditional"
        rows.append(
            {
                "schema_version": 1,
                "pattern_id": pattern_id,
                "scenario_id": card["scenario_id"],
                "source_case_ids": [],
                "candidate_scope": scope,
                "hypothesis": first_markdown_heading_or_sentence(text, path.stem),
                "supporting_evidence": [
                    {
                        "source_pattern_path": str(path.relative_to(out)),
                        "evidence_level": "single_scenario_pattern_doc",
                    }
                ],
                "evidence_strength": "single_scenario",
                "needs_cross_scenario_confirmation": True,
                "promotion_constraints": [
                    "Pattern document originated in one scenario; require cross-scenario evidence before broad promotion."
                ],
                "counterexamples": [],
            }
        )
    return rows


def build_anti_patterns(card: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "schema_version": 1,
            "anti_pattern_id": item["anti_pattern_id"],
            "scenario_id": card["scenario_id"],
            "description": item["description"],
            "risk": item["risk"],
            "evidence": [],
            "prevention": item["prevention"],
            "reuse_level": "anti_pattern",
        }
        for item in ANTI_PATTERN_DEFS
    ]


def build_method_fragments(card: dict[str, Any], cases: list[dict[str, Any]], patterns: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = [
        {
            "schema_version": 1,
            "method_fragment_id": "MF-EVIDENCE-FIRST-001",
            "scenario_id": card["scenario_id"],
            "porting_phase": "knowledge_extraction",
            "statement": "Separate committed history, dirty workspace, binary/prebuilt assets, and initial imports before generating reusable cases.",
            "source_case_ids": [],
            "source_patterns": [],
            "candidate_scope": "universal_candidate",
            "preconditions": [],
            "failure_modes": ["knowledge base pollution", "false reusable rule"],
            "evidence_strength": "single_scenario",
        },
        {
            "schema_version": 1,
            "method_fragment_id": "MF-SCOPE-AUTHORITY-001",
            "scenario_id": card["scenario_id"],
            "porting_phase": "scope_classification",
            "statement": "Treat task_profile.yaml runtime architecture and RISC-V role as scope authority until repository evidence justifies a formal scope change.",
            "source_case_ids": [],
            "source_patterns": [],
            "candidate_scope": "universal_candidate",
            "preconditions": ["task_profile.yaml exists"],
            "failure_modes": ["ARM-primary and RISC-V-primary scenario confusion"],
            "evidence_strength": "single_scenario",
        },
        {
            "schema_version": 1,
            "method_fragment_id": "MF-VALIDATION-SEPARATION-001",
            "scenario_id": card["scenario_id"],
            "porting_phase": "validation_governance",
            "statement": "Do not infer build, boot, runtime, or test validation from commit/file evidence alone.",
            "source_case_ids": [],
            "source_patterns": [],
            "candidate_scope": "universal_candidate",
            "preconditions": [],
            "failure_modes": ["false validation status"],
            "evidence_strength": "single_scenario",
        },
    ]
    pattern_by_case = {
        case_id: pattern["pattern_id"]
        for pattern in patterns
        for case_id in pattern.get("source_case_ids", [])
    }
    for idx, case in enumerate(cases, start=1):
        rows.append(
            {
                "schema_version": 1,
                "method_fragment_id": f"MF-CASE-{idx:03d}",
                "scenario_id": card["scenario_id"],
                "porting_phase": (case.get("porting_phase") or ["knowledge_extraction"])[0],
                "statement": case.get("rule") or case.get("title") or "unknown",
                "source_case_ids": [case["case_id"]],
                "source_patterns": [pattern_by_case[case["case_id"]]] if case["case_id"] in pattern_by_case else [],
                "candidate_scope": case.get("reuse_level", "conditional"),
                "preconditions": case.get("applicability", []),
                "failure_modes": case.get("risks", []),
                "evidence_strength": "single_scenario",
            }
        )
    return rows


def build_meta_input_audit(
    out: Path,
    card: dict[str, Any],
    cases: list[dict[str, Any]],
    patterns: list[dict[str, Any]],
    anti_patterns: list[dict[str, Any]],
    method_fragments: list[dict[str, Any]],
    audit_notes: list[str],
) -> str:
    case_md_count = len(list((out / "04_knowledge_base/cases").glob("*.md")))
    missing_card_fields = [
        key
        for key in ["project_name", "runtime_arch", "runtime_core", "soc_vendor", "soc", "board", "system_type"]
        if unknownish(card.get(key))
    ]
    reuse_counts = Counter(str(case.get("reuse_level") or "unknown") for case in cases)
    lines = [
        "# Meta Input Audit",
        "",
        f"- Generated at: `{now_iso()}`",
        f"- Source output: `{out}`",
        f"- Scenario ID: `{card['scenario_id']}`",
        f"- Case Markdown files: `{case_md_count}`",
        f"- Normalized cases: `{len(cases)}`",
        f"- Pattern candidates: `{len(patterns)}`",
        f"- Anti-patterns: `{len(anti_patterns)}`",
        f"- Method fragments: `{len(method_fragments)}`",
        "",
        "## Reuse Level Distribution",
        "",
    ]
    if reuse_counts:
        lines.extend(f"- `{key}`: {value}" for key, value in sorted(reuse_counts.items()))
    else:
        lines.append("- None")
    lines.extend(["", "## Missing Or Unknown Scenario Fields", ""])
    if missing_card_fields:
        lines.extend(f"- `{field}` is unknown; downstream aggregation must treat it as an applicability gap." for field in missing_card_fields)
    else:
        lines.append("- None")
    lines.extend(["", "## Downgrades And Notes", ""])
    if audit_notes:
        lines.extend(f"- {note}" for note in audit_notes)
    else:
        lines.append("- None")
    lines.extend(
        [
            "",
            "## Validation Guardrails",
            "",
            "- Build, boot, runtime and test status remain `unknown` unless explicit logs are attached.",
            "- Single-scenario cases are not exported as formal `universal` methods.",
            "- Dirty workspace and binary/prebuilt evidence remain separate from committed history.",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True, help="porting_knowledge_output directory")
    parser.add_argument("--stage-result")
    args = parser.parse_args()

    out = Path(args.out)
    meta = out / "07_meta_inputs"
    meta.mkdir(parents=True, exist_ok=True)
    audit_notes: list[str] = []
    blocking: list[str] = []
    non_blocking: list[str] = []

    task_profile_path = out / "00_config/task_profile.yaml"
    stats_path = out / "02_statistics/statistics_summary.json"
    if not task_profile_path.exists():
        blocking.append("Missing 00_config/task_profile.yaml; cannot build scenario_card.yaml.")
    if not stats_path.exists():
        blocking.append("Missing 02_statistics/statistics_summary.json; statistics must come from stage 03 output.")

    task_profile = read_yaml(task_profile_path)
    stats = read_json(stats_path)
    card = build_scenario_card(out, task_profile, stats)
    validation = build_validation_status(card["scenario_id"], out, listify(card.get("primary_focus")))
    cases = normalize_cases(out, card, audit_notes)
    patterns = build_pattern_candidates(out, card, cases)
    anti_patterns = build_anti_patterns(card)
    method_fragments = build_method_fragments(card, cases, patterns)

    if not cases and (out / "04_knowledge_base/cases").exists():
        non_blocking.append("No case Markdown files were normalized; downstream output will be sparse.")

    dump_yaml(meta / "scenario_card.yaml", card)
    write_jsonl(meta / "normalized_cases.jsonl", cases)
    write_jsonl(meta / "pattern_candidates.jsonl", patterns)
    write_jsonl(meta / "anti_patterns.jsonl", anti_patterns)
    write_jsonl(meta / "method_fragments.jsonl", method_fragments)
    dump_yaml(meta / "validation_status.yaml", validation)
    (meta / "meta_input_audit.md").write_text(
        build_meta_input_audit(out, card, cases, patterns, anti_patterns, method_fragments, audit_notes),
        encoding="utf-8",
    )

    outputs = [
        "07_meta_inputs/scenario_card.yaml",
        "07_meta_inputs/normalized_cases.jsonl",
        "07_meta_inputs/pattern_candidates.jsonl",
        "07_meta_inputs/anti_patterns.jsonl",
        "07_meta_inputs/method_fragments.jsonl",
        "07_meta_inputs/validation_status.yaml",
        "07_meta_inputs/meta_input_audit.md",
    ]
    result = {
        "stage": "08_meta_input_exporter",
        "status": "blocked" if blocking else "passed",
        "summary": f"Exported cross-scenario meta inputs for {card['scenario_id']}: {len(cases)} cases, {len(patterns)} pattern candidates, {len(anti_patterns)} anti-patterns.",
        "input_files_read": [
            "00_config/task_profile.yaml",
            "02_statistics/statistics_summary.json",
            "04_knowledge_base/cases/",
            "04_knowledge_base/patterns/",
            "06_audit/final_audit_report.md",
            "_stage_results/*.json",
        ],
        "output_files_written": outputs,
        "blocking_issues": blocking,
        "non_blocking_issues": non_blocking + audit_notes,
        "next_stage_inputs": outputs,
        "case_count": len(cases),
        "pattern_candidate_count": len(patterns),
        "anti_pattern_count": len(anti_patterns),
        "method_fragment_count": len(method_fragments),
    }
    if args.stage_result:
        Path(args.stage_result).write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
