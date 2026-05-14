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


def slugify(value: str) -> str:
    value = str(value).lower()
    value = re.sub(r"[^a-z0-9]+", "_", value)
    return re.sub(r"_+", "_", value).strip("_") or "unknown"


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


def scenario_summary(card: dict[str, Any], meta_dir: Path) -> dict[str, Any]:
    return {
        "scenario_id": card.get("scenario_id"),
        "source_meta_dir": str(meta_dir),
        "source_output_dir": card.get("source_output_dir"),
        "project_name": card.get("project_name", "unknown"),
        "scenario_type": card.get("scenario_type", []),
        "runtime_arch": card.get("runtime_arch", "unknown"),
        "runtime_core": card.get("runtime_core", "unknown"),
        "soc_vendor": card.get("soc_vendor", "unknown"),
        "soc": card.get("soc", "unknown"),
        "board": card.get("board", "unknown"),
        "kernel": card.get("kernel", "unknown"),
        "system_type": card.get("system_type", "unknown"),
        "primary_focus": card.get("primary_focus", []),
        "validation_status": card.get("validation_status", {}),
        "statistics": card.get("statistics", {}),
        "quality": card.get("quality", {}),
    }


def write_registry(out: Path, scenarios: list[dict[str, Any]]) -> None:
    summaries = [scenario_summary(item["card"], item["meta_dir"]) for item in scenarios]
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


def write_machine_readable_patterns(out: Path, patterns: list[dict[str, Any]], fragments: list[dict[str, Any]], anti_patterns: list[dict[str, Any]]) -> None:
    write_jsonl(out / "02_patterns/pattern_candidates.jsonl", patterns)
    write_jsonl(out / "02_patterns/method_fragments.jsonl", fragments)
    write_jsonl(out / "02_patterns/anti_patterns.jsonl", anti_patterns)


def support_count_by_statement(fragments: list[dict[str, Any]]) -> dict[str, set[str]]:
    support: dict[str, set[str]] = defaultdict(set)
    for fragment in fragments:
        statement = str(fragment.get("statement") or "").strip()
        if not statement:
            continue
        support[statement].add(str(fragment.get("scenario_id") or "unknown"))
    return support


def write_universal_methods(out: Path, scenarios: list[dict[str, Any]], fragments: list[dict[str, Any]]) -> None:
    support = support_count_by_statement(fragments)
    formal = [
        (statement, sorted(ids))
        for statement, ids in support.items()
        if len(ids) >= FORMAL_UNIVERSAL_MIN_SCENARIOS and len(scenarios) >= FORMAL_UNIVERSAL_MIN_SCENARIOS
    ]
    lines = [
        "# Universal Methods",
        "",
        f"Promotion rule: a formal universal method requires at least {FORMAL_UNIVERSAL_MIN_SCENARIOS} distinct scenario_id values, broad applicability, explicit constraints, and no workaround-only basis.",
        "",
    ]
    if formal:
        lines.extend(["## Promoted Universal Methods", ""])
        for statement, ids in formal:
            lines.append(f"- {statement} Supported scenarios: {', '.join(ids)}.")
    else:
        lines.extend(
            [
                "## No Formal Universal Methods Promoted",
                "",
                f"Input scenario count is {len(scenarios)}. Evidence is insufficient for formal universal promotion; keep these as universal_candidate until at least {FORMAL_UNIVERSAL_MIN_SCENARIOS} scenarios support them.",
                "",
                "## Universal Candidates",
                "",
            ]
        )
        for statement, ids in sorted(support.items(), key=lambda item: (-len(item[1]), item[0]))[:30]:
            lines.append(f"- {statement} Evidence strength: {len(ids)} scenario(s): {', '.join(sorted(ids))}.")
    (out / "02_patterns/universal_methods.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_conditional_patterns(out: Path, patterns: list[dict[str, Any]], cases: list[dict[str, Any]]) -> None:
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
    ]
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
    lines = [
        "# Scenario-Specific Knowledge",
        "",
        "These records are retained as concrete case knowledge and must not be promoted without more scenarios.",
        "",
    ]
    selected = [
        case for case in cases
        if case.get("reuse_level") in {"scenario_specific", "risk_only", "workaround"}
        or len({str(case.get("scenario_id"))}) == 1
    ]
    for case in selected:
        lines.append(f"- `{case.get('scenario_id')}` / `{case.get('case_id')}`: {case.get('title')} Scope: {case.get('reuse_level')}.")
    if len(lines) == 4:
        lines.append("- No scenario-specific cases were present.")
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
        "board_soc_porting_runbook.md": [
            "# Board/SoC Porting Runbook",
            "",
            "Start by confirming board, SoC, runtime architecture, product path, vendor path, kernel type, and system type. Then trace product/board/vendor/SoC binding through BUILD.gn, productdefine, HDF/HCS/HCB, DTS, and vendor configuration evidence.",
        ],
        "architecture_porting_runbook.md": [
            "# Architecture Porting Runbook",
            "",
            "Classify whether the scenario is ARM-primary, RISC-V-primary, or heterogeneous auxiliary-core before interpreting toolchain, firmware, and third_party changes. Do not treat auxiliary firmware as runtime architecture evidence.",
        ],
        "driver_hdf_porting_runbook.md": [
            "# Driver/HDF Porting Runbook",
            "",
            "For HDF and driver enablement, require a chain across driver implementation, SoC/board binding, vendor HDF configuration, generated runtime assets, and verification logs. Isolated driver commits are conditional evidence only.",
        ],
        "binary_prebuilt_governance.md": [
            "# Binary/Prebuilt Governance",
            "",
            "Record path, sha256, architecture, possible usage, source/provenance, redistribution risk, and runtime dependency. Binary imports are not source fixes and should not be merged into universal source-level methods.",
        ],
        "dirty_workspace_governance.md": [
            "# Dirty Workspace Governance",
            "",
            "Dirty workspace records are local evidence. They can reveal ongoing work, generated outputs, or risks, but they must stay separate from committed history until converted to clean commits or documented patches.",
        ],
    }
    for filename, lines in runbooks.items():
        (out / "03_methodology" / filename).write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_global_kb(out: Path, cases: list[dict[str, Any]], patterns: list[dict[str, Any]], fragments: list[dict[str, Any]], anti_patterns: list[dict[str, Any]]) -> None:
    evidence_rows = []
    for case in cases:
        evidence_rows.append(
            {
                "scenario_id": case.get("scenario_id"),
                "case_id": case.get("case_id"),
                "source_case_path": case.get("source_case_path"),
                "evidence": case.get("evidence", {}),
            }
        )
    write_jsonl(out / "04_global_kb/evidence_index.jsonl", evidence_rows)
    traces = []
    cases_by_id = {case.get("case_id"): case for case in cases}
    patterns_by_id = {pattern.get("pattern_id"): pattern for pattern in patterns}
    for pattern in patterns:
        for case_id in pattern.get("source_case_ids") or []:
            case = cases_by_id.get(case_id)
            traces.append(
                {
                    "trace_type": "pattern_to_case",
                    "pattern_id": pattern.get("pattern_id"),
                    "case_id": case_id,
                    "scenario_id": case.get("scenario_id") if case else pattern.get("scenario_id"),
                    "evidence": case.get("evidence") if case else {},
                }
            )
    for fragment in fragments:
        for pattern_id in fragment.get("source_patterns") or []:
            pattern = patterns_by_id.get(pattern_id)
            traces.append(
                {
                    "trace_type": "method_to_pattern",
                    "method_fragment_id": fragment.get("method_fragment_id"),
                    "pattern_id": pattern_id,
                    "scenario_id": fragment.get("scenario_id"),
                    "pattern_exists": bool(pattern),
                }
            )
        for case_id in fragment.get("source_case_ids") or []:
            case = cases_by_id.get(case_id)
            traces.append(
                {
                    "trace_type": "method_to_case",
                    "method_fragment_id": fragment.get("method_fragment_id"),
                    "case_id": case_id,
                    "scenario_id": fragment.get("scenario_id"),
                    "case_exists": bool(case),
                    "evidence": case.get("evidence") if case else {},
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


def write_generated_skills(out: Path, scenario_count: int) -> None:
    shared_guard = (
        "Use normalized scenario cards, cases, pattern candidates, anti-patterns, and method fragments. "
        "Do not promote single-scenario generated_skill.md content into formal universal guidance."
    )
    skill_files = {
        "universal_openharmony_porting_skill.md": f"# Universal OpenHarmony Porting Skill\n\n{shared_guard}\n\nFormal universal methods require at least {FORMAL_UNIVERSAL_MIN_SCENARIOS} supporting scenarios. Current scenario count: {scenario_count}.\n",
        "arm_primary_board_soc_skill.md": f"# ARM-Primary Board/SoC Skill\n\n{shared_guard}\n\nFocus on product/board/vendor/SoC binding, driver/HDF chains, boot firmware provenance, dirty workspace separation, and binary/prebuilt governance.\n",
        "riscv_primary_distribution_skill.md": f"# RISC-V Primary Distribution Skill\n\n{shared_guard}\n\nFocus on runtime architecture classification, toolchain and third_party compatibility, boot stack, kernel/userspace ABI, and avoiding auxiliary-core confusion.\n",
        "heterogeneous_aux_core_skill.md": f"# Heterogeneous Auxiliary-Core Skill\n\n{shared_guard}\n\nKeep auxiliary firmware, DSP, ARISC, C906, and RISC-V coprocessor evidence separate from the primary OpenHarmony runtime architecture.\n",
    }
    for filename, text in skill_files.items():
        (out / "05_generated_skills" / filename).write_text(text, encoding="utf-8")


def write_meta_report(out: Path, scenarios: list[dict[str, Any]], cases: list[dict[str, Any]], patterns: list[dict[str, Any]], anti_patterns: list[dict[str, Any]]) -> None:
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
        f"- evidence_strength: `{evidence_strength}`",
        "",
        "## Promotion Classes",
        "",
        "- universal: requires at least 3 distinct scenario_id values and is not promoted from single-scenario evidence here.",
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
    (out / "meta_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", action="append", default=[], help="porting_knowledge_output or 07_meta_inputs path")
    parser.add_argument("--input-root", help="root containing */porting_knowledge_output/07_meta_inputs")
    parser.add_argument("--out", required=True, help="openharmony_porting_meta_output directory")
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

    write_registry(out, scenarios)
    write_case_indexes(out, cases)
    write_machine_readable_patterns(out, patterns, fragments, anti_patterns)
    write_universal_methods(out, scenarios, fragments)
    write_conditional_patterns(out, patterns, cases)
    write_scenario_specific(out, cases)
    write_anti_patterns(out, anti_patterns)
    write_additional_pattern_views(out, cases, patterns)
    write_methodology(out, len(scenarios), cases)
    write_global_kb(out, cases, patterns, fragments, anti_patterns)
    write_generated_skills(out, len(scenarios))
    write_meta_report(out, scenarios, cases, patterns, anti_patterns)

    result = {
        "schema_version": 1,
        "status": "passed",
        "generated_at": now_iso(),
        "scenario_count": len(scenarios),
        "case_count": len(cases),
        "pattern_candidate_count": len(patterns),
        "anti_pattern_count": len(anti_patterns),
        "method_fragment_count": len(fragments),
        "input_meta_dirs": [str(path) for path in meta_dirs],
        "output_dir": str(out),
    }
    (out / "cross_scenario_result.json").write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
