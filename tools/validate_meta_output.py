#!/usr/bin/env python3
"""Validate openharmony_porting_meta_output produced by aggregate_cross_scenario.py."""

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
    "02_patterns/universal_methods.md",
    "02_patterns/conditional_patterns.md",
    "02_patterns/scenario_specific_knowledge.md",
    "02_patterns/anti_patterns.md",
    "03_methodology/openharmony_porting_general_method.md",
    "03_methodology/board_soc_porting_runbook.md",
    "03_methodology/architecture_porting_runbook.md",
    "03_methodology/driver_hdf_porting_runbook.md",
    "03_methodology/binary_prebuilt_governance.md",
    "03_methodology/dirty_workspace_governance.md",
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


def count_jsonl(path: Path) -> int:
    require_file(path)
    count = 0
    with path.open(encoding="utf-8", errors="ignore") as f:
        for lineno, line in enumerate(f, start=1):
            if not line.strip():
                continue
            try:
                json.loads(line)
            except Exception as exc:
                fail(f"JSONL parse failed for {path}:{lineno}: {exc}")
            count += 1
    return count


def require_terms(path: Path, terms: list[str]) -> None:
    text = path.read_text(encoding="utf-8", errors="ignore").lower()
    missing = [term for term in terms if term.lower() not in text]
    if missing:
        fail(f"{path} missing required terms: {missing}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    out = Path(args.out)
    for rel in REQUIRED_FILES:
        require_file(out / rel)

    registry = read_yaml(out / "00_scenario_registry/scenario_registry.yaml")
    result = read_json(out / "cross_scenario_result.json")
    scenario_count = int(registry.get("scenario_count") or 0)
    if scenario_count != int(result.get("scenario_count") or -1):
        fail("scenario_registry.yaml scenario_count does not match cross_scenario_result.json")
    scenarios = registry.get("scenarios") or []
    if scenario_count != len(scenarios):
        fail("scenario_registry.yaml scenario_count does not match scenarios list length")
    if scenario_count < 1:
        fail("scenario registry must contain at least one scenario")

    case_count = count_jsonl(out / "01_normalized_cases/cases.jsonl")
    if case_count != int(result.get("case_count") or -1):
        fail("cases.jsonl row count does not match cross_scenario_result.json case_count")

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
        ["universal", "conditional", "scenario_specific", "risk_only", "anti_pattern"],
    )
    universal_text = (out / "02_patterns/universal_methods.md").read_text(encoding="utf-8", errors="ignore").lower()
    if scenario_count < 3 and "no formal universal methods promoted" not in universal_text:
        fail("universal_methods.md must not promote formal universal methods when scenario_count < 3")

    print(f"[OK] meta output valid: scenarios={scenario_count} cases={case_count}")


if __name__ == "__main__":
    main()
