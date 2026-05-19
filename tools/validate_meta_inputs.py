#!/usr/bin/env python3
"""Validate 07_meta_inputs produced by export_meta_inputs.py."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import yaml


REQUIRED_CASE_FIELDS = [
    "case_id",
    "scenario_id",
    "source_case_path",
    "title",
    "scenario_type",
    "porting_phase",
    "subsystem",
    "problem_type",
    "reuse_level",
    "evidence_level",
    "evidence",
    "rule",
    "confidence",
    "validation",
]

REQUIRED_ANTI_IDS = {
    "ANTI-FORCE-SYNC-AS-PORTING",
    "ANTI-GITATTRIBUTES-ONLY-AS-SUBSYSTEM",
    "ANTI-DIRTY-AS-COMMITTED",
    "ANTI-BINARY-IMPORT-AS-SOURCE-FIX",
    "ANTI-RISCV-AUX-AS-PRIMARY",
    "ANTI-SINGLE-SCENARIO-AS-UNIVERSAL",
}


def fail(message: str) -> None:
    print(f"[BLOCKED] {message}", file=sys.stderr)
    raise SystemExit(1)


def warn(message: str) -> None:
    print(f"[WARN] {message}", file=sys.stderr)


def require_file(path: Path) -> None:
    if not path.exists():
        fail(f"Missing required file: {path}")
    if path.stat().st_size == 0:
        fail(f"Empty required file: {path}")
    print(f"[OK] {path} ({path.stat().st_size} bytes)")


def read_yaml(path: Path) -> dict[str, Any]:
    require_file(path)
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8", errors="ignore")) or {}
    except Exception as exc:
        fail(f"YAML parse failed for {path}: {exc}")
    if not isinstance(data, dict):
        fail(f"YAML root must be object: {path}")
    return data


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    require_file(path)
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8", errors="ignore") as f:
        for lineno, line in enumerate(f, start=1):
            if not line.strip():
                continue
            try:
                obj = json.loads(line)
            except Exception as exc:
                fail(f"JSONL parse failed for {path}:{lineno}: {exc}")
            if not isinstance(obj, dict):
                fail(f"JSONL row must be object: {path}:{lineno}")
            rows.append(obj)
    return rows


def validation_status_is_proven_passed(value: Any) -> bool:
    if isinstance(value, dict):
        status = str(value.get("status") or "").lower()
        logs = value.get("logs") or value.get("test_logs") or []
        return status == "passed" and bool(logs)
    return str(value or "").lower() == "passed"


def is_missing(value: Any) -> bool:
    return value is None or value == "" or value == []


def listify(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()]
    if isinstance(value, tuple):
        return [str(item) for item in value if str(item).strip()]
    text = str(value).strip()
    return [text] if text else []


def validate_scope_tokens(scenario_card: dict[str, Any], cases: list[dict[str, Any]], method_fragments: list[dict[str, Any]]) -> None:
    scenario_type = set(listify(scenario_card.get("scenario_type")))
    riscv_primary = "riscv_primary_distribution" in scenario_type
    arm_primary = "board_soc_arm_primary" in scenario_type
    if riscv_primary and not arm_primary:
        for case in cases:
            applicability = set(listify(case.get("applicability")))
            if "arm_primary_board_soc" in applicability:
                fail(f"RISC-V primary case has ARM-primary applicability token: {case.get('case_id')}")
        for fragment in method_fragments:
            preconditions = set(listify(fragment.get("preconditions")))
            if "arm_primary_board_soc" in preconditions:
                fail(f"RISC-V primary method fragment has ARM-primary precondition: {fragment.get('method_fragment_id')}")
    if arm_primary and not riscv_primary:
        for case in cases:
            applicability = set(listify(case.get("applicability")))
            if "riscv_primary_distribution" in applicability:
                fail(f"ARM-primary case has RISC-V-primary applicability token: {case.get('case_id')}")
        for fragment in method_fragments:
            preconditions = set(listify(fragment.get("preconditions")))
            if "riscv_primary_distribution" in preconditions:
                fail(f"ARM-primary method fragment has RISC-V-primary precondition: {fragment.get('method_fragment_id')}")


def validate_runtime_status_not_inferred(validation: dict[str, Any]) -> None:
    for key in ["build", "boot"]:
        value = validation.get(key, {})
        if isinstance(value, dict) and str(value.get("status") or "").lower() == "passed" and not value.get("logs"):
            fail(f"validation_status.yaml marks {key}=passed without logs")
    tests = validation.get("tests") or {}
    if isinstance(tests, dict):
        for name, value in tests.items():
            if isinstance(value, dict) and str(value.get("status") or "").lower() == "passed" and not value.get("logs"):
                fail(f"validation_status.yaml marks test {name}=passed without logs")
    runtime_features = validation.get("runtime_features") or {}
    if isinstance(runtime_features, dict):
        for name, value in runtime_features.items():
            if isinstance(value, dict) and str(value.get("status") or "").lower() == "passed" and not value.get("logs"):
                fail(f"validation_status.yaml marks runtime feature {name}=passed without logs")


def count_case_markdown(out: Path) -> int:
    cases_dir = out / "04_knowledge_base/cases"
    if not cases_dir.exists():
        return 0
    return len(list(cases_dir.glob("*.md")))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True, help="porting_knowledge_output directory")
    args = parser.parse_args()

    out = Path(args.out)
    meta = out / "07_meta_inputs"
    if not meta.exists():
        fail(f"Missing 07_meta_inputs directory: {meta}")

    scenario_card = read_yaml(meta / "scenario_card.yaml")
    validation_status = read_yaml(meta / "validation_status.yaml")
    cases = read_jsonl(meta / "normalized_cases.jsonl")
    patterns = read_jsonl(meta / "pattern_candidates.jsonl")
    anti_patterns = read_jsonl(meta / "anti_patterns.jsonl")
    method_fragments = read_jsonl(meta / "method_fragments.jsonl")
    require_file(meta / "meta_input_audit.md")
    validate_scope_tokens(scenario_card, cases, method_fragments)

    scenario_id = str(scenario_card.get("scenario_id") or "")
    if not scenario_id:
        fail("scenario_card.yaml missing scenario_id")
    if scenario_id in {"t113", "ruyios", "unknown"}:
        fail(f"scenario_id is too short or ambiguous: {scenario_id}")
    if validation_status.get("scenario_id") != scenario_id:
        fail("validation_status.yaml scenario_id does not match scenario_card.yaml")

    stats = scenario_card.get("statistics")
    if not isinstance(stats, dict) or not stats:
        fail("scenario_card.yaml statistics must be a non-empty object")
    for key in ["commit_records_count", "file_change_records_count", "binary_asset_records_count", "dirty_file_records_count"]:
        if key not in stats:
            fail(f"scenario_card.yaml statistics missing {key}")

    validate_runtime_status_not_inferred(validation_status)

    expected_case_count = count_case_markdown(out)
    if len(cases) < expected_case_count:
        fail(f"normalized_cases.jsonl rows ({len(cases)}) < case Markdown files ({expected_case_count})")

    case_ids: set[str] = set()
    for idx, case in enumerate(cases, start=1):
        missing = [field for field in REQUIRED_CASE_FIELDS if field not in case or is_missing(case.get(field))]
        if missing:
            fail(f"normalized case row {idx} missing required fields: {missing}")
        if case.get("scenario_id") != scenario_id:
            fail(f"normalized case row {idx} has scenario_id={case.get('scenario_id')} expected {scenario_id}")
        if case.get("reuse_level") == "universal":
            fail(f"single-scenario normalized case must not use reuse_level=universal: {case.get('case_id')}")
        validation = case.get("validation") or {}
        for key in ["build", "boot", "runtime_feature"]:
            if validation_status_is_proven_passed(validation.get(key)) and not validation.get("test_logs"):
                fail(f"case {case.get('case_id')} marks {key}=passed without test logs")
        case_ids.add(str(case.get("case_id")))

    pattern_ids: set[str] = set()
    for pattern in patterns:
        pid = str(pattern.get("pattern_id") or "")
        if not pid:
            fail("pattern candidate missing pattern_id")
        pattern_ids.add(pid)
        if pattern.get("scenario_id") != scenario_id:
            fail(f"pattern {pid} scenario_id mismatch")
        scope = pattern.get("candidate_scope")
        if scope == "universal":
            fail(f"single-scenario pattern candidate must not use candidate_scope=universal: {pid}")
        if scope != "scenario_specific" and pattern.get("needs_cross_scenario_confirmation") is not True:
            fail(f"pattern {pid} must set needs_cross_scenario_confirmation=true")
        for case_id in pattern.get("source_case_ids") or []:
            if case_id not in case_ids:
                fail(f"pattern {pid} references unknown case_id {case_id}")

    anti_ids = {str(item.get("anti_pattern_id") or "") for item in anti_patterns}
    missing_anti = sorted(REQUIRED_ANTI_IDS - anti_ids)
    if missing_anti:
        fail(f"anti_patterns.jsonl missing required anti-patterns: {missing_anti}")
    for item in anti_patterns:
        if item.get("reuse_level") != "anti_pattern":
            fail(f"anti-pattern {item.get('anti_pattern_id')} must use reuse_level=anti_pattern")
        if not item.get("prevention"):
            fail(f"anti-pattern {item.get('anti_pattern_id')} missing prevention")

    for fragment in method_fragments:
        fid = str(fragment.get("method_fragment_id") or "")
        if not fid:
            fail("method fragment missing method_fragment_id")
        for case_id in fragment.get("source_case_ids") or []:
            if case_id not in case_ids:
                fail(f"method fragment {fid} references unknown case_id {case_id}")
        for pattern_id in fragment.get("source_patterns") or []:
            if pattern_id not in pattern_ids:
                fail(f"method fragment {fid} references unknown pattern_id {pattern_id}")

    if not cases:
        warn("No normalized cases were exported; this is allowed only for sparse or pre-case outputs.")

    print(f"[OK] 07_meta_inputs valid for scenario_id={scenario_id}; cases={len(cases)} patterns={len(patterns)} anti_patterns={len(anti_patterns)} method_fragments={len(method_fragments)}")


if __name__ == "__main__":
    main()
