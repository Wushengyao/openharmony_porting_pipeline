#!/usr/bin/env python3
"""Validate openharmony_porting_meta_output.

The validator focuses on cross-scenario evidence integrity, not just file
existence. It verifies method -> pattern -> case -> scenario -> evidence
traceability and prevents universal over-promotion from sparse inputs.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import yaml


REQUIRED_FILES = [
    "00_scenario_registry/scenario_registry.yaml",
    "00_scenario_registry/scenario_comparison_matrix.md",
    "01_normalized_cases/cases.jsonl",
    "02_patterns/pattern_candidates.jsonl",
    "02_patterns/method_fragments.jsonl",
    "02_patterns/anti_patterns.jsonl",
    "02_patterns/universal_methods.md",
    "02_patterns/conditional_patterns.md",
    "02_patterns/scenario_specific_knowledge.md",
    "02_patterns/anti_patterns.md",
    "02_patterns/workaround_patterns.md",
    "03_methodology/openharmony_porting_general_method.md",
    "03_methodology/board_soc_porting_runbook.md",
    "03_methodology/architecture_porting_runbook.md",
    "03_methodology/driver_hdf_porting_runbook.md",
    "03_methodology/binary_prebuilt_governance.md",
    "03_methodology/dirty_workspace_governance.md",
    "04_global_kb/evidence_index.jsonl",
    "04_global_kb/evidence_trace_index.jsonl",
    "04_global_kb/path_module_ontology.md",
    "04_global_kb/problem_taxonomy.yaml",
    "04_global_kb/risk_taxonomy.yaml",
    "04_global_kb/glossary.md",
    "05_generated_skills/universal_openharmony_porting_skill.md",
    "05_generated_skills/arm_primary_board_soc_skill.md",
    "05_generated_skills/riscv_primary_distribution_skill.md",
    "05_generated_skills/heterogeneous_aux_core_skill.md",
    "meta_report.md",
    "cross_scenario_result.json",
]


def fail(message: str) -> None:
    print(f"[BLOCKED] {message}", file=sys.stderr)
    raise SystemExit(1)


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
    return data if isinstance(data, dict) else {}


def read_json(path: Path) -> dict[str, Any]:
    require_file(path)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        fail(f"JSON parse failed for {path}: {exc}")
    return data if isinstance(data, dict) else {}


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


def require_terms(path: Path, terms: list[str]) -> None:
    text = path.read_text(encoding="utf-8", errors="ignore").lower()
    missing = [term for term in terms if term.lower() not in text]
    if missing:
        fail(f"{path} missing required terms: {missing}")


def listify(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()]
    if value is None:
        return []
    text = str(value).strip()
    return [text] if text else []


def evidence_nonempty(case: dict[str, Any]) -> bool:
    evidence = case.get("evidence") or {}
    if not isinstance(evidence, dict):
        return False
    for key in ["commits", "files", "diffs", "dirty_files", "binary_assets"]:
        value = evidence.get(key)
        if isinstance(value, list) and value:
            return True
    return False


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    out = Path(args.out)
    for rel in REQUIRED_FILES:
        require_file(out / rel)

    registry = read_yaml(out / "00_scenario_registry/scenario_registry.yaml")
    result = read_json(out / "cross_scenario_result.json")
    cases = read_jsonl(out / "01_normalized_cases/cases.jsonl")
    patterns = read_jsonl(out / "02_patterns/pattern_candidates.jsonl")
    fragments = read_jsonl(out / "02_patterns/method_fragments.jsonl")
    anti_patterns = read_jsonl(out / "02_patterns/anti_patterns.jsonl")
    evidence_traces = read_jsonl(out / "04_global_kb/evidence_trace_index.jsonl")
    scenario_count = int(registry.get("scenario_count") or 0)
    if scenario_count != int(result.get("scenario_count") or -1):
        fail("scenario_registry.yaml scenario_count does not match cross_scenario_result.json")
    scenarios = registry.get("scenarios") or []
    if scenario_count != len(scenarios):
        fail("scenario_registry.yaml scenario_count does not match scenarios list length")
    if scenario_count < 1:
        fail("scenario registry must contain at least one scenario")
    scenario_ids = {str(item.get("scenario_id")) for item in scenarios}

    if len(cases) != int(result.get("case_count") or -1):
        fail("cases.jsonl row count does not match cross_scenario_result.json case_count")
    if len(patterns) != int(result.get("pattern_candidate_count") or -1):
        fail("pattern_candidates.jsonl row count does not match cross_scenario_result.json pattern_candidate_count")

    case_ids: set[str] = set()
    for case in cases:
        case_id = str(case.get("case_id") or "")
        if not case_id:
            fail("case row missing case_id")
        if case_id in case_ids:
            fail(f"duplicate case_id in meta cases: {case_id}")
        case_ids.add(case_id)
        scenario_id = str(case.get("scenario_id") or "")
        if scenario_id not in scenario_ids:
            fail(f"case {case_id} references unknown scenario_id {scenario_id}")
        if case.get("reuse_level") == "universal":
            fail(f"normalized case must not use formal universal reuse_level: {case_id}")
        for key in ["porting_phase", "subsystem", "problem_type", "scenario_type"]:
            if not listify(case.get(key)):
                fail(f"case {case_id} missing non-empty {key}")
        if not evidence_nonempty(case):
            fail(f"case {case_id} has no evidence in commits/files/diffs/dirty/binary")

    pattern_ids: set[str] = set()
    for pattern in patterns:
        pid = str(pattern.get("pattern_id") or "")
        if not pid:
            fail("pattern row missing pattern_id")
        if pid in pattern_ids:
            fail(f"duplicate pattern_id: {pid}")
        pattern_ids.add(pid)
        scenario_id = str(pattern.get("scenario_id") or "")
        if scenario_id not in scenario_ids:
            fail(f"pattern {pid} references unknown scenario_id {scenario_id}")
        if pattern.get("candidate_scope") == "universal":
            fail(f"pattern candidate must not use formal universal scope before promotion: {pid}")
        if pattern.get("candidate_scope") != "scenario_specific" and pattern.get("needs_cross_scenario_confirmation") is not True:
            fail(f"pattern {pid} must set needs_cross_scenario_confirmation=true unless scenario_specific")
        for case_id in pattern.get("source_case_ids") or []:
            if case_id not in case_ids:
                fail(f"pattern {pid} references unknown source_case_id {case_id}")

    for fragment in fragments:
        fid = str(fragment.get("method_fragment_id") or "")
        if not fid:
            fail("method fragment missing method_fragment_id")
        scenario_id = str(fragment.get("scenario_id") or "")
        if scenario_id not in scenario_ids:
            fail(f"method fragment {fid} references unknown scenario_id {scenario_id}")
        for case_id in fragment.get("source_case_ids") or []:
            if case_id not in case_ids:
                fail(f"method fragment {fid} references unknown source_case_id {case_id}")
        for pattern_id in fragment.get("source_patterns") or []:
            if pattern_id not in pattern_ids:
                fail(f"method fragment {fid} references unknown source_pattern {pattern_id}")

    anti_ids = {str(item.get("anti_pattern_id") or "") for item in anti_patterns}
    for required in [
        "ANTI-FORCE-SYNC-AS-PORTING",
        "ANTI-GITATTRIBUTES-ONLY-AS-SUBSYSTEM",
        "ANTI-DIRTY-AS-COMMITTED",
        "ANTI-BINARY-IMPORT-AS-SOURCE-FIX",
        "ANTI-RISCV-AUX-AS-PRIMARY",
        "ANTI-SINGLE-SCENARIO-AS-UNIVERSAL",
    ]:
        if required not in anti_ids:
            fail(f"missing required anti-pattern: {required}")

    trace_pattern_refs = set()
    for trace in evidence_traces:
        if trace.get("pattern_id"):
            trace_pattern_refs.add(str(trace.get("pattern_id")))
    for pattern in patterns:
        if pattern.get("source_case_ids") and str(pattern.get("pattern_id")) not in trace_pattern_refs:
            fail(f"pattern {pattern.get('pattern_id')} has source cases but no evidence_trace_index entry")

    require_terms(
        out / "02_patterns/conditional_patterns.md",
        ["ARM-primary", "RISC-V-primary", "heterogeneous_aux_core"],
    )
    require_terms(
        out / "02_patterns/anti_patterns.md",
        ["dirty", "binary", "force-sync", ".gitattributes", "RISC-V"],
    )
    require_terms(
        out / "meta_report.md",
        ["universal", "universal_candidate", "conditional", "scenario_specific", "risk_only", "anti_pattern"],
    )
    universal_text = (out / "02_patterns/universal_methods.md").read_text(encoding="utf-8", errors="ignore").lower()
    if scenario_count < 3 and "no formal universal methods promoted" not in universal_text:
        fail("universal_methods.md must not promote formal universal methods when scenario_count < 3")

    print(f"[OK] meta output valid: scenarios={scenario_count} cases={len(cases)} patterns={len(patterns)} fragments={len(fragments)} traces={len(evidence_traces)}")


if __name__ == "__main__":
    main()
