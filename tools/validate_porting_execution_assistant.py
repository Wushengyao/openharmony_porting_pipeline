#!/usr/bin/env python3
"""Validate Stage 10 OpenHarmony porting execution-assistant artifacts."""

from __future__ import annotations

import argparse
from datetime import datetime
import json
import re
import sys
from pathlib import Path
from typing import Any

import yaml


STAGE = "10_porting_execution_assistant"
DEFAULT_ARTIFACT_ROOT = "08_execution_assistant"

REQUIRED_FILES = [
    "target_profile.yaml",
    "meta_knowledge_digest.yaml",
    "meta_knowledge_digest.md",
    "implementation_readiness.yaml",
    "implementation_readiness.md",
    "source_file_blueprint.yaml",
    "source_file_blueprint.md",
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

ARTIFACT_CONTRACTS = {
    "target_profile.yaml": ("target_profile", "requirements"),
    "meta_knowledge_digest.yaml": ("meta_knowledge_digest", "selected_methods"),
    "implementation_readiness.yaml": ("implementation_readiness", "items"),
    "source_file_blueprint.yaml": ("source_file_blueprint", "blueprints"),
    "source_tree_survey.yaml": ("source_tree_survey", "items"),
    "gap_analysis.yaml": ("gap_analysis", "gaps"),
    "porting_plan.yaml": ("porting_plan", "phases"),
    "patch_plan.yaml": ("patch_plan", "patches"),
    "build_acceptance.yaml": ("build_acceptance", "commands"),
    "external_dependency_followup.yaml": ("external_dependency_followup", "items"),
    "target_dependency_inventory.yaml": ("target_dependency_inventory", "items"),
    "uncertainty_ledger.yaml": ("uncertainty_ledger", "items"),
}

EXTERNAL_DEPENDENCY_CATEGORIES = {
    "bsp",
    "bootloader",
    "firmware",
    "prebuilt",
    "closed_driver",
    "signing_packaging_tools",
}

EVIDENCE_PREFIXES = (
    "user_requirement:",
    "source_tree:",
    "source_file:",
    "task_profile:",
    "operator_context:",
    "raw_record:",
    "dirty_record:",
    "binary_asset:",
    "case:",
    "meta_method:",
    "method_fragment:",
    "pattern:",
    "log:",
    "build_log:",
    "workspace:",
    "unknown:",
)

SETUP_COMMAND_RE = re.compile(
    r"\b("
    r"apt(?:-get)?|yum|dnf|pacman|zypper|brew|pip(?:3)?\s+install|npm\s+install|"
    r"pnpm\s+install|yarn\s+install|curl|wget|repo\s+init|repo\s+sync"
    r")\b",
    re.IGNORECASE,
)

BOOT_RUNTIME_TEST_PASSED_RE = re.compile(
    r"\b(?:boot|runtime|run\s*time|test|tests)\b[^\n]{0,100}\bpassed\b|"
    r"\bpassed\b[^\n]{0,100}\b(?:boot|runtime|run\s*time|test|tests)\b|"
    r"\b(?:boot_status|runtime_status|test_status|tests_status)\s*:\s*passed\b",
    re.IGNORECASE,
)

PATCH_DIFF_RE = re.compile(r"(^diff --git\s+|^@@\s+[-+0-9, ]+\s+[-+0-9, ]+\s+@@)", re.MULTILINE)


def log(level: str, message: str) -> None:
    ts = datetime.now().astimezone().strftime("%Y-%m-%dT%H:%M:%S%z")
    print(f"[{ts}] [{level}] {message}", file=sys.stderr)


def fail(message: str) -> None:
    log("BLOCKED", message)
    raise SystemExit(1)


def require_file(path: Path) -> None:
    log("CHECK", f"require non-empty file: {path}")
    if not path.exists():
        fail(f"Missing required file: {path}")
    if not path.is_file():
        fail(f"Required path is not a file: {path}")
    if path.stat().st_size == 0:
        fail(f"Empty required file: {path}")
    log("OK", f"file present: {path} ({path.stat().st_size} bytes)")


def read_json(path: Path) -> dict[str, Any]:
    require_file(path)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        fail(f"JSON parse failed for {path}: {exc}")
    if not isinstance(data, dict):
        fail(f"JSON root must be object: {path}")
    return data


def read_yaml(path: Path) -> dict[str, Any]:
    require_file(path)
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8", errors="ignore")) or {}
    except Exception as exc:
        fail(f"YAML parse failed for {path}: {exc}")
    if not isinstance(data, dict):
        fail(f"YAML root must be mapping: {path}")
    return data


def listify(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def validate_stage_result(path: Path) -> dict[str, Any]:
    data = read_json(path)
    if data.get("stage") != STAGE:
        fail(f"stage-result stage must be {STAGE}, got {data.get('stage')}")
    if data.get("status") == "blocked":
        fail(f"stage-result is blocked: {data.get('blocking_issues')}")
    if data.get("execution_mode") != "plan-only":
        fail("execution_mode must be plan-only")
    if data.get("patch_apply_mode") not in {"none", "plan-only"}:
        fail("patch_apply_mode must be none or plan-only for P0")
    for key in ["input_files_read", "output_files_written", "blocking_issues", "non_blocking_issues", "next_stage_inputs"]:
        if not isinstance(data.get(key), list):
            fail(f"stage-result {key} must be a list")
    return data


def validate_evidence_refs(record: dict[str, Any], context: str) -> None:
    refs = listify(record.get("evidence_refs"))
    refs = [str(ref).strip() for ref in refs if str(ref).strip()]
    if not refs:
        fail(f"{context} missing evidence_refs")
    if not any(ref.startswith(EVIDENCE_PREFIXES) for ref in refs):
        fail(f"{context} evidence_refs must use an accepted evidence prefix: {refs[:3]}")
    if not context.startswith("uncertainty_ledger") and not any(
        ref.startswith(EVIDENCE_PREFIXES[:-1]) for ref in refs
    ):
        fail(f"{context} must not rely only on unknown evidence; move uncertain work to uncertainty_ledger")


def validate_nested_evidence(value: Any, context: str) -> None:
    if isinstance(value, dict):
        evidence_bearing_keys = [
            "requirement_id",
            "method_id",
            "case_id",
            "action_id",
            "item_id",
            "blueprint_id",
            "asset_id",
            "survey_id",
            "gap_id",
            "phase_id",
            "task_id",
            "patch_id",
            "command_id",
            "dependency_id",
            "uncertainty_id",
            "recommendation",
            "action",
            "command",
            "description",
            "objective",
            "observation",
            "rationale",
            "why_needed",
            "content_strategy",
            "apply_gate",
            "next_action",
            "risk",
            "unknown",
        ]
        if any(key in value for key in evidence_bearing_keys):
            validate_evidence_refs(value, context)
        for key, child in value.items():
            if key == "evidence_refs":
                continue
            validate_nested_evidence(child, f"{context}.{key}")
    elif isinstance(value, list):
        for idx, child in enumerate(value):
            validate_nested_evidence(child, f"{context}[{idx}]")


def validate_contract(path: Path, data: dict[str, Any], artifact_type: str, list_key: str) -> None:
    if data.get("schema_version") != 1:
        fail(f"{path.name} schema_version must be 1")
    if data.get("artifact_type") != artifact_type:
        fail(f"{path.name} artifact_type must be {artifact_type}")
    if not str(data.get("generated_at") or "").strip():
        fail(f"{path.name} missing generated_at")
    if not isinstance(data.get(list_key), list):
        fail(f"{path.name} {list_key} must be a list")
    validate_nested_evidence(data.get(list_key), f"{path.name}.{list_key}")


def validate_target_profile(path: Path, data: dict[str, Any]) -> None:
    target = data.get("target")
    if not isinstance(target, dict):
        fail("target_profile.yaml target must be a mapping")
    for key in ["product", "board", "soc", "vendor", "openharmony_version"]:
        if key not in target:
            fail(f"target_profile.yaml target missing {key}")
    requirements = data.get("requirements")
    if not isinstance(requirements, list):
        fail("target_profile.yaml requirements must be a list")
    for idx, req in enumerate(requirements):
        if isinstance(req, dict):
            validate_evidence_refs(req, f"target_profile.yaml.requirements[{idx}]")


def validate_meta_knowledge_digest(path: Path, data: dict[str, Any]) -> None:
    for key in ["selected_methods", "deferred_methods", "selected_cases", "action_bias"]:
        if key not in data:
            fail(f"meta_knowledge_digest.yaml missing {key}")
        if not isinstance(data.get(key), list):
            fail(f"meta_knowledge_digest.yaml {key} must be a list")
    for key in ["selected_methods", "deferred_methods", "selected_cases", "action_bias"]:
        for idx, item in enumerate(data.get(key) or []):
            if not isinstance(item, dict):
                fail(f"meta_knowledge_digest.yaml {key}[{idx}] must be a mapping")
            validate_evidence_refs(item, f"meta_knowledge_digest.yaml.{key}[{idx}]")


def validate_source_file_blueprint(path: Path, data: dict[str, Any]) -> None:
    if data.get("default_generation_mode") != "blueprint_only":
        fail("source_file_blueprint.yaml default_generation_mode must be blueprint_only")
    if data.get("apply_policy") != "do_not_apply_without_target_source_evidence":
        fail("source_file_blueprint.yaml apply_policy must block application without target source evidence")
    for idx, item in enumerate(data.get("blueprints") or []):
        if not isinstance(item, dict):
            fail(f"source_file_blueprint.yaml blueprints[{idx}] must be a mapping")
        validate_evidence_refs(item, f"source_file_blueprint.yaml.blueprints[{idx}]")
        if item.get("generation_mode") != "blueprint_only":
            fail(f"source_file_blueprint.yaml blueprints[{idx}] generation_mode must be blueprint_only")
        if not str(item.get("apply_gate") or "").strip():
            fail(f"source_file_blueprint.yaml blueprints[{idx}] missing apply_gate")


def validate_target_dependency_inventory(path: Path, data: dict[str, Any]) -> None:
    items = data.get("items")
    if not isinstance(items, list):
        fail("target_dependency_inventory.yaml items must be a list")
    if data.get("asset_count") != len(items):
        fail("target_dependency_inventory.yaml asset_count must equal items length")
    for idx, item in enumerate(items):
        if not isinstance(item, dict):
            fail(f"target_dependency_inventory.yaml items[{idx}] must be a mapping")
        validate_evidence_refs(item, f"target_dependency_inventory.yaml.items[{idx}]")
        if not str(item.get("path") or "").strip():
            fail(f"target_dependency_inventory.yaml items[{idx}] missing path")
        if not str(item.get("category") or "").strip():
            fail(f"target_dependency_inventory.yaml items[{idx}] missing category")


def validate_patch_plan(path: Path, md_path: Path, artifact_dir: Path) -> None:
    data = read_yaml(path)
    if data.get("default_apply_mode") not in {"plan-only", "none"}:
        fail("patch_plan.yaml default_apply_mode must be plan-only or none")
    patches = data.get("patches")
    if not isinstance(patches, list):
        fail("patch_plan.yaml patches must be a list")
    high_risk = {"high", "critical", "external_dependency", "vendor_required"}
    for idx, patch in enumerate(patches):
        if not isinstance(patch, dict):
            fail(f"patch_plan.yaml patches[{idx}] must be a mapping")
        validate_evidence_refs(patch, f"patch_plan.yaml.patches[{idx}]")
        if patch.get("auto_generate") is not False:
            fail(f"patch_plan.yaml patches[{idx}] auto_generate must be false in default plan-only mode")
        if str(patch.get("apply_mode") or "") not in {"plan-only", "manual_review", "none"}:
            fail(f"patch_plan.yaml patches[{idx}] apply_mode must stay plan-only/manual_review/none")
        risk_level = str(patch.get("risk_level") or "unknown").lower()
        if risk_level in high_risk and patch.get("auto_generate") is not False:
            fail(f"high-risk patch cannot be auto-generated: patches[{idx}]")
        for forbidden_key in ["patch", "diff", "generated_patch", "patch_content"]:
            if forbidden_key in patch:
                fail(f"patch_plan.yaml patches[{idx}] must not embed {forbidden_key} in P0")
    patch_text = md_path.read_text(encoding="utf-8", errors="ignore")
    if PATCH_DIFF_RE.search(patch_text):
        fail("patch_plan.md contains a patch diff; P0 must stay plan-only")
    patch_dir = artifact_dir / "patches"
    if patch_dir.exists() and any(item.is_file() for item in patch_dir.rglob("*")):
        fail("08_execution_assistant/patches contains generated files; P0 must not auto-generate patches")


def validate_build_acceptance(path: Path, md_path: Path) -> None:
    data = read_yaml(path)
    if data.get("scope") != "build_only":
        fail("build_acceptance.yaml scope must be build_only")
    if data.get("environment_setup_policy") != "forbidden":
        fail("build_acceptance.yaml environment_setup_policy must be forbidden")
    commands = data.get("commands")
    if not isinstance(commands, list):
        fail("build_acceptance.yaml commands must be a list")
    for idx, command_record in enumerate(commands):
        if not isinstance(command_record, dict):
            fail(f"build_acceptance.yaml commands[{idx}] must be a mapping")
        validate_evidence_refs(command_record, f"build_acceptance.yaml.commands[{idx}]")
        command = str(command_record.get("command") or "")
        if command and command.lower() != "unknown" and command_record.get("uses_existing_script") is not True:
            fail(f"build_acceptance command must use an existing OpenHarmony script: commands[{idx}]")
        if command_record.get("environment_setup") is not False:
            fail(f"build_acceptance command must not perform environment setup: commands[{idx}]")
        if SETUP_COMMAND_RE.search(command):
            fail(f"build_acceptance command performs environment/source setup: commands[{idx}]")
    text = path.read_text(encoding="utf-8", errors="ignore") + "\n" + md_path.read_text(encoding="utf-8", errors="ignore")
    if SETUP_COMMAND_RE.search(text):
        fail("build_acceptance artifact mentions environment setup/download commands")


def validate_external_dependency_followup(path: Path) -> None:
    data = read_yaml(path)
    coverage = data.get("coverage")
    if not isinstance(coverage, list):
        fail("external_dependency_followup.yaml coverage must be a list")
    categories = {
        str(item.get("category") or "").strip()
        for item in coverage
        if isinstance(item, dict)
    }
    missing = sorted(EXTERNAL_DEPENDENCY_CATEGORIES - categories)
    if missing:
        fail(f"external_dependency_followup.yaml missing coverage categories: {missing}")
    for idx, item in enumerate(data.get("items") or []):
        if not isinstance(item, dict):
            fail(f"external_dependency_followup.yaml items[{idx}] must be a mapping")
        validate_evidence_refs(item, f"external_dependency_followup.yaml.items[{idx}]")
        category = str(item.get("category") or "")
        if category and category not in EXTERNAL_DEPENDENCY_CATEGORIES and category != "other_third_party":
            fail(f"external_dependency_followup.yaml items[{idx}] has unknown category: {category}")


def validate_no_forbidden_status_claims(artifact_dir: Path) -> None:
    bad: list[str] = []
    for path in artifact_dir.glob("*"):
        if path.suffix not in {".yaml", ".yml", ".md", ".json"}:
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        if BOOT_RUNTIME_TEST_PASSED_RE.search(text):
            bad.append(path.name)
    if bad:
        fail(f"artifacts imply boot/runtime/test passed from build evidence: {bad}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--stage-result", required=True)
    parser.add_argument("--artifact-root", default=None)
    args = parser.parse_args()

    workspace = Path(args.workspace)
    out = Path(args.out)
    artifact_dir = Path(args.artifact_root) if args.artifact_root else out / DEFAULT_ARTIFACT_ROOT
    log("INFO", f"validate start: stage={STAGE} workspace={workspace} out={out} artifact_root={artifact_dir}")

    validate_stage_result(Path(args.stage_result))

    if not artifact_dir.exists() or not artifact_dir.is_dir():
        fail(f"Missing artifact directory: {artifact_dir}")
    for rel in REQUIRED_FILES:
        require_file(artifact_dir / rel)

    for rel, (artifact_type, list_key) in ARTIFACT_CONTRACTS.items():
        path = artifact_dir / rel
        data = read_yaml(path)
        validate_contract(path, data, artifact_type, list_key)
        if rel == "target_profile.yaml":
            validate_target_profile(path, data)
        elif rel == "meta_knowledge_digest.yaml":
            validate_meta_knowledge_digest(path, data)
        elif rel == "source_file_blueprint.yaml":
            validate_source_file_blueprint(path, data)
        elif rel == "target_dependency_inventory.yaml":
            validate_target_dependency_inventory(path, data)

    validate_patch_plan(artifact_dir / "patch_plan.yaml", artifact_dir / "patch_plan.md", artifact_dir)
    validate_build_acceptance(artifact_dir / "build_acceptance.yaml", artifact_dir / "build_acceptance.md")
    validate_external_dependency_followup(artifact_dir / "external_dependency_followup.yaml")
    validate_no_forbidden_status_claims(artifact_dir)

    log("INFO", f"validate complete: stage={STAGE}")
    print(f"[OK] {STAGE}")


if __name__ == "__main__":
    main()
