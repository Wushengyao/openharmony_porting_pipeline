#!/usr/bin/env python3
"""Validate openharmony_porting_meta_output.

The validator focuses on cross-scenario evidence integrity, not just file
existence. It verifies method -> pattern -> case -> scenario -> evidence
traceability and prevents universal over-promotion from sparse inputs.
"""

from __future__ import annotations

import argparse
import json
import os
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
    "02_patterns/meta_methods.jsonl",
    "02_patterns/conditional_methods.jsonl",
    "02_patterns/anti_patterns.jsonl",
    "02_patterns/universal_methods.md",
    "02_patterns/conditional_patterns.md",
    "02_patterns/case_inventory_by_scenario.md",
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
    "meta_skill_pack/README.md",
    "meta_skill_pack/install.sh",
    "meta_skill_pack/references/meta_output_contract.md",
    "meta_skill_pack/references/conditional_method_index.md",
    "meta_skill_pack/schemas/meta_method.schema.json",
    "meta_skill_pack/schemas/case_selector.schema.json",
    "meta_skill_pack/schemas/scenario_registry.schema.json",
    "meta_skill_pack/examples/case_selector_examples.yaml",
    "meta_skill_pack/universal_openharmony_porting/SKILL.md",
    "meta_skill_pack/arm_primary_board_soc/SKILL.md",
    "meta_skill_pack/riscv_primary_distribution/SKILL.md",
    "meta_skill_pack/heterogeneous_aux_core/SKILL.md",
    "_llm_refine_result.json",
    "_llm_refine.ndjson",
    "meta_report.md",
    "cross_scenario_result.json",
]

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
PROMOTION_LEVELS = {
    "universal_by_design",
    "universal_from_evidence",
    "universal_candidate",
    "conditional",
    "scenario_specific",
    "risk_only",
    "anti_pattern",
}


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


def max_jsonl_line_length(path: Path) -> int:
    require_file(path)
    max_len = 0
    with path.open(encoding="utf-8", errors="ignore") as f:
        for line in f:
            if line.strip():
                max_len = max(max_len, len(line.rstrip("\n")))
    return max_len


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
    meta_methods = read_jsonl(out / "02_patterns/meta_methods.jsonl")
    anti_patterns = read_jsonl(out / "02_patterns/anti_patterns.jsonl")
    conditional_methods = read_jsonl(out / "02_patterns/conditional_methods.jsonl")
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
    scenario_types_by_id = {str(item.get("scenario_id")): set(listify(item.get("scenario_type"))) for item in scenarios}
    soc_vendors_by_id = {str(item.get("scenario_id")): str(item.get("soc_vendor") or "unknown") for item in scenarios}
    for item in scenarios:
        scenario_id = str(item.get("scenario_id") or "")
        for key in ["source_meta_dir_label", "source_meta_dir_relative", "source_output_label", "source_output_dir_relative"]:
            if not str(item.get(key) or "").strip():
                fail(f"scenario {scenario_id} missing registry portability field {key}")

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
        case_scenario_types = set(listify(case.get("scenario_type")))
        unknown_types = case_scenario_types - scenario_types_by_id.get(scenario_id, set())
        if unknown_types:
            fail(
                f"case {case_id} uses scenario_type outside registry for {scenario_id}: "
                f"{sorted(unknown_types)} not in {sorted(scenario_types_by_id.get(scenario_id, set()))}"
            )
        evidence_type = str(case.get("evidence_type") or "")
        evidence_level = str(case.get("evidence_level") or "")
        evidence_strength = str(case.get("evidence_strength") or "")
        if evidence_type not in EVIDENCE_TYPES:
            fail(f"case {case_id} has invalid evidence_type={evidence_type}")
        if evidence_level not in EVIDENCE_TYPES:
            fail(f"case {case_id} has invalid evidence_level={evidence_level}; evidence_level must be a canonical evidence type")
        if evidence_level != evidence_type:
            fail(f"case {case_id} evidence_level={evidence_level} must match evidence_type={evidence_type}")
        if evidence_strength not in EVIDENCE_STRENGTHS:
            fail(f"case {case_id} has invalid evidence_strength={evidence_strength}")
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

    global_fragment_ids: set[str] = set()
    for fragment in fragments:
        fid = str(fragment.get("method_fragment_id") or "")
        if not fid:
            fail("method fragment missing method_fragment_id")
        global_fid = str(fragment.get("global_method_fragment_id") or "")
        if not global_fid:
            fail(f"method fragment {fid} missing global_method_fragment_id")
        if global_fid in global_fragment_ids:
            fail(f"duplicate global_method_fragment_id: {global_fid}")
        global_fragment_ids.add(global_fid)
        scenario_id = str(fragment.get("scenario_id") or "")
        if scenario_id not in scenario_ids:
            fail(f"method fragment {fid} references unknown scenario_id {scenario_id}")
        for case_id in fragment.get("source_case_ids") or []:
            if case_id not in case_ids:
                fail(f"method fragment {fid} references unknown source_case_id {case_id}")
        for pattern_id in fragment.get("source_patterns") or []:
            if pattern_id not in pattern_ids:
                fail(f"method fragment {fid} references unknown source_pattern {pattern_id}")

    meta_method_ids: set[str] = set()
    conditional_method_ids = {str(method.get("method_id") or "") for method in conditional_methods}
    if len(conditional_methods) < 5:
        fail(f"conditional_methods.jsonl must contain at least 5 cross-scenario conditional methods; found {len(conditional_methods)}")
    for method in meta_methods:
        method_id = str(method.get("method_id") or "")
        if not method_id:
            fail("meta method missing method_id")
        if method_id in meta_method_ids:
            fail(f"duplicate meta method_id: {method_id}")
        meta_method_ids.add(method_id)
        promotion_level = str(method.get("promotion_level") or "")
        if promotion_level not in PROMOTION_LEVELS:
            fail(f"meta method {method_id} has invalid promotion_level={promotion_level}")
        method_scenario_ids = listify(method.get("scenario_ids"))
        if not method_scenario_ids:
            fail(f"meta method {method_id} missing scenario_ids")
        for scenario_id in method_scenario_ids:
            if scenario_id not in scenario_ids:
                fail(f"meta method {method_id} references unknown scenario_id {scenario_id}")
        supporting_cases = listify(method.get("supporting_cases"))
        supporting_patterns = listify(method.get("supporting_patterns"))
        for case_id in supporting_cases:
            if case_id not in case_ids:
                fail(f"meta method {method_id} references unknown supporting case {case_id}")
        for pattern_id in supporting_patterns:
            if pattern_id not in pattern_ids:
                fail(f"meta method {method_id} references unknown supporting pattern {pattern_id}")
        if promotion_level == "universal_by_design":
            if supporting_cases or supporting_patterns:
                fail(f"meta method {method_id} is universal_by_design but has source case/pattern evidence")
        if promotion_level == "universal_from_evidence":
            if len(set(method_scenario_ids)) < 3:
                fail(f"meta method {method_id} universal_from_evidence requires at least 3 scenario_id values")
            if len(supporting_cases) + len(supporting_patterns) < 2:
                fail(f"meta method {method_id} universal_from_evidence requires at least 2 source cases or patterns")
            method_types = set()
            method_vendors = set()
            for scenario_id in method_scenario_ids:
                method_types.update(scenario_types_by_id.get(scenario_id, set()))
                vendor = soc_vendors_by_id.get(scenario_id, "unknown")
                if vendor != "unknown":
                    method_vendors.add(vendor)
            if len(method_types) < 2 and len(method_vendors) < 2:
                fail(f"meta method {method_id} universal_from_evidence requires at least 2 scenario_type values or 2 SoC/vendor values")
        if promotion_level == "conditional":
            if method_id not in conditional_method_ids:
                fail(f"conditional meta method {method_id} missing from conditional_methods.jsonl")
            if str(method.get("derivation") or "") != "conditional_from_evidence":
                fail(f"conditional meta method {method_id} must set derivation=conditional_from_evidence")
            if len(set(method_scenario_ids)) < 2:
                fail(f"conditional meta method {method_id} requires at least 2 scenario_id values")
            if len(supporting_cases) < 2:
                fail(f"conditional meta method {method_id} requires at least 2 supporting cases")
            if not listify(method.get("applicability")) or not listify(method.get("non_applicability")):
                fail(f"conditional meta method {method_id} must include applicability and non_applicability")
            if not listify(method.get("quality_gates")):
                fail(f"conditional meta method {method_id} must include quality_gates")
    for method in conditional_methods:
        method_id = str(method.get("method_id") or "")
        if method_id not in meta_method_ids:
            fail(f"conditional method {method_id} missing from meta_methods.jsonl")

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
    meta_case_traces: set[tuple[str, str]] = set()
    meta_pattern_traces: set[tuple[str, str]] = set()
    trace_ids: set[str] = set()
    for trace in evidence_traces:
        trace_id = str(trace.get("trace_id") or "")
        if not trace_id:
            fail("evidence_trace_index row missing trace_id")
        if trace_id in trace_ids:
            fail(f"duplicate evidence trace_id: {trace_id}")
        trace_ids.add(trace_id)
        if "evidence" in trace:
            fail(f"evidence_trace_index row {trace_id} embeds full evidence; use evidence_ref and 04_global_kb/evidence_index.jsonl instead")
        if trace.get("pattern_id"):
            trace_pattern_refs.add(str(trace.get("pattern_id")))
        trace_type = str(trace.get("trace_type") or "")
        if trace_type in {"pattern_to_case", "method_to_case", "meta_method_to_case"} and not trace.get("evidence_ref"):
            fail(f"evidence_trace_index row {trace_id} missing evidence_ref")
        if trace_type in {"method_to_pattern", "method_to_case"} and not trace.get("global_method_fragment_id"):
            fail(f"evidence_trace_index row {trace_id} missing global_method_fragment_id")
        if trace_type in {"meta_method_to_case", "meta_method_to_pattern"}:
            meta_method_id = str(trace.get("meta_method_id") or "")
            if meta_method_id not in meta_method_ids:
                fail(f"evidence_trace_index row {trace_id} references unknown meta_method_id {meta_method_id}")
            if trace_type == "meta_method_to_case":
                case_id = str(trace.get("case_id") or "")
                if case_id not in case_ids:
                    fail(f"evidence_trace_index row {trace_id} references unknown case_id {case_id}")
                meta_case_traces.add((meta_method_id, case_id))
            if trace_type == "meta_method_to_pattern":
                pattern_id = str(trace.get("pattern_id") or "")
                if pattern_id not in pattern_ids:
                    fail(f"evidence_trace_index row {trace_id} references unknown pattern_id {pattern_id}")
                meta_pattern_traces.add((meta_method_id, pattern_id))
    for pattern in patterns:
        if pattern.get("source_case_ids") and str(pattern.get("pattern_id")) not in trace_pattern_refs:
            fail(f"pattern {pattern.get('pattern_id')} has source cases but no evidence_trace_index entry")
    for method in meta_methods:
        method_id = str(method.get("method_id") or "")
        for case_id in listify(method.get("supporting_cases")):
            if (method_id, case_id) not in meta_case_traces:
                fail(f"meta method {method_id} missing meta_method_to_case trace for {case_id}")
        for pattern_id in listify(method.get("supporting_patterns")):
            if (method_id, pattern_id) not in meta_pattern_traces:
                fail(f"meta method {method_id} missing meta_method_to_pattern trace for {pattern_id}")
    trace_max_len = max_jsonl_line_length(out / "04_global_kb/evidence_trace_index.jsonl")
    if trace_max_len > 4096:
        fail(f"evidence_trace_index.jsonl lines are too long ({trace_max_len} bytes max); use evidence_ref instead of embedded evidence")

    require_terms(
        out / "02_patterns/conditional_patterns.md",
        ["ARM-primary", "RISC-V-primary", "heterogeneous_aux_core", "Cross-Scenario Conditional Methods", "conditional_from_evidence"],
    )
    require_terms(
        out / "02_patterns/anti_patterns.md",
        ["dirty", "binary", "force-sync", ".gitattributes", "RISC-V"],
    )
    require_terms(
        out / "meta_report.md",
        ["universal_by_design", "universal_from_evidence", "universal_candidate", "conditional", "scenario_specific", "risk_only", "anti_pattern"],
    )
    for rel in [
        "meta_skill_pack/universal_openharmony_porting/SKILL.md",
        "meta_skill_pack/arm_primary_board_soc/SKILL.md",
        "meta_skill_pack/riscv_primary_distribution/SKILL.md",
        "meta_skill_pack/heterogeneous_aux_core/SKILL.md",
    ]:
        path = out / rel
        text = path.read_text(encoding="utf-8", errors="ignore")
        if path.stat().st_size < 3000:
            fail(f"{path} is too short for release-grade Skill draft; expected at least 3000 bytes")
        if not text.startswith("---\n"):
            fail(f"{path} missing SKILL.md frontmatter")
        for term in ["name:", "description:", "Applicability", "Non-Applicability", "Input Contract", "Output Contract", "Workflow", "Case Selector", "Method References", "Cross-Scenario Relationship", "Installed Use", "Evidence Rules", "Failure Gates", "Quality Checklist", "Examples", "Anti-Examples", "Minimum Test Commands"]:
            if term not in text:
                fail(f"{path} missing required Skill contract term {term}")
    for rel in [
        "03_methodology/board_soc_porting_runbook.md",
        "03_methodology/architecture_porting_runbook.md",
        "03_methodology/driver_hdf_porting_runbook.md",
        "03_methodology/binary_prebuilt_governance.md",
        "03_methodology/dirty_workspace_governance.md",
    ]:
        path = out / rel
        if path.stat().st_size < 1500:
            fail(f"{path} is too short for runbook output; expected at least 1500 bytes")
        require_terms(path, ["Applicability", "Inputs", "Outputs", "Workflow", "Evidence Requirements", "Case Selector", "Failure Handling", "Quality Gates", "Example", "Anti-Example"])
    if not os.access(out / "meta_skill_pack/install.sh", os.X_OK):
        fail("meta_skill_pack/install.sh must be executable")
    if not any((out / "_codex_logs").glob("09_cross_scenario_refine.*")):
        fail("_codex_logs must retain 09_cross_scenario_refine.* LLM refinement log or skip marker")
    universal_text = (out / "02_patterns/universal_methods.md").read_text(encoding="utf-8", errors="ignore").lower()
    if "### universal:" in universal_text or "promotion_level: universal\n" in universal_text:
        fail("universal_methods.md must use universal_by_design or universal_from_evidence, not bare universal")
    if scenario_count >= 3 and "universal_by_design" not in universal_text:
        fail("universal_methods.md must distinguish universal_by_design pipeline guardrails when formal guardrails are present")
    if scenario_count < 3 and "no formal universal methods promoted" not in universal_text:
        fail("universal_methods.md must not promote formal universal methods when scenario_count < 3")

    print(f"[OK] meta output valid: scenarios={scenario_count} cases={len(cases)} patterns={len(patterns)} fragments={len(fragments)} meta_methods={len(meta_methods)} conditional_methods={len(conditional_methods)} traces={len(evidence_traces)}")


if __name__ == "__main__":
    main()
