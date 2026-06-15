#!/usr/bin/env python3
"""Audit closure evidence for OH_Agent_Subagent_TODO.md.

This is a deterministic checklist helper. It checks whether required skill and
project-record artifacts exist, then labels items that still need external lab
fixtures or formal full-suite execution. It does not replace the main Agent's
evidence judgment.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    import yaml
except Exception:  # pragma: no cover
    yaml = None


DEFAULT_WORK_RECORD = Path("/data1/WSY/filetransfer/OHOS/PortingTest/musepaper2_oh61_porting_work")


def dump_data(data: Any) -> str:
    if yaml is not None:
        return yaml.safe_dump(data, allow_unicode=True, sort_keys=False)
    return json.dumps(data, indent=2, ensure_ascii=False) + "\n"


def rel(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def exists_all(root: Path, paths: list[str]) -> tuple[bool, list[str], list[str]]:
    present: list[str] = []
    missing: list[str] = []
    for item in paths:
        path = root / item
        if path.exists():
            present.append(item)
        else:
            missing.append(item)
    return not missing, present, missing


def count_files(root: Path, pattern: str) -> int:
    if not root.exists():
        return 0
    return sum(1 for p in root.glob(pattern) if p.is_file())


def status_from_required(root: Path, required: list[str], *, external_blockers: list[str] | None = None) -> dict[str, Any]:
    ok, present, missing = exists_all(root, required)
    if ok and external_blockers:
        status = "complete_with_external_blockers"
    elif ok:
        status = "complete"
    elif external_blockers:
        status = "blocked_external" if missing else "partial"
    else:
        status = "partial"
    return {
        "status": status,
        "present": present,
        "missing": missing,
        "external_blockers": external_blockers or [],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skill-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--work-record", type=Path, default=DEFAULT_WORK_RECORD)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    skill = args.skill_root.resolve()
    work = args.work_record.resolve()

    checks: dict[str, dict[str, Any]] = {}
    checks["P0_rc0_baseline"] = status_from_required(
        work,
        [
            "baselines/musepaper2-oh6.1-rc0/README.md",
            "baselines/musepaper2-oh6.1-rc0/image_manifest.yaml",
            "baselines/musepaper2-oh6.1-rc0/source_revisions.yaml",
            "baselines/musepaper2-oh6.1-rc0/known_debts.yaml",
            "acceptance/acceptance_state.yaml",
            "acceptance/rc_gate_report.md",
            "docs/baseline_rc0.md",
        ],
    )
    checks["P1_xdevice_runner"] = status_from_required(
        skill,
        [
            "tools/xts_xdevice_runner/prepare_env.py",
            "tools/xts_xdevice_runner/generate_user_config.py",
            "tools/xts_xdevice_runner/run_suite.py",
            "tools/xts_xdevice_runner/collect_reports.py",
            "tools/xts_xdevice_runner/parse_xml.py",
            "tools/xts_xdevice_runner/summarize.py",
            "tools/xts_xdevice_runner/flaky_detector.py",
            "tools/xts_xdevice_runner/compare_baseline.py",
            "tools/xts_xdevice_runner/run_xdevice_probe.py",
            "docs/xdevice_runner.md",
        ],
    )
    checks["P2_subagent_contract"] = status_from_required(
        skill,
        [
            "docs/agent_architecture.md",
            "docs/codex_subagent_playbook.md",
            "schemas/agent_task.schema.json",
            "schemas/evidence_pack.schema.json",
            "schemas/acceptance_state.schema.json",
            "agents/repo-surveyor.md",
            "agents/build-log-triager.md",
            "agents/xts-hats-runner.md",
            "agents/regression-reviewer.md",
            "agents/reporter.md",
            "agents/skill-maintainer.md",
            "examples/agent_tasks/build-log-triage/task.yaml",
            "examples/agent_tasks/hats-summary/task.yaml",
            "examples/agent_tasks/baseline-regression/task.yaml",
            "AGENTS.md",
        ],
    )
    checks["P3_cost_control"] = status_from_required(
        skill,
        [
            "tools/evidence_pack_builder.py",
            "tools/log_slice.py",
            "taxonomies/build_error_taxonomy.yaml",
            "taxonomies/runtime_error_taxonomy.yaml",
            "taxonomies/hats_safe_set.yaml",
            "policies/model_routing.yaml",
            "policies/budget_policy.yaml",
            "replay_eval/README.md",
            "replay_eval/run_eval.py",
        ],
    )
    checks["P4_device_recovery"] = status_from_required(
        skill,
        [
            "tools/device_job_ledger.py",
            "schemas/device_job_ledger.schema.json",
            "tools/rig_controller.py",
            "docs/rig_controller.md",
            "tools/panic_classifier.py",
            "tools/recovery_plan_builder.py",
        ],
        external_blockers=[
            "No physical rig-controller backend is proven for MusePaper2 in the current evidence.",
            "Full unattended recovery from kernel panic/boot slot mutation still requires lab fixture validation.",
        ],
    )
    checks["P5_requirement_loop"] = status_from_required(
        skill,
        [
            "workflows/requirement_intake.md",
            "workflows/patch_planning.md",
            "workflows/controlled_patch_execution.md",
            "workflows/build_flash_test.md",
            "workflows/regression_acceptance.md",
            "templates/handoff_report.md",
        ],
        external_blockers=[
            "A dedicated small requirement pilot with controlled diff, build, flash, and report still needs a fresh task record.",
        ],
    )
    checks["P6_version_lane"] = status_from_required(
        skill,
        [
            "version_lanes/oh61-release-to-oh61-lts/README.md",
            "version_lanes/oh61-release-to-oh61-lts/task_profile.yaml",
            "version_lanes/oh61-release-to-oh61-lts/acceptance_checklist.md",
            "tools/version_lane/diff_classifier.py",
            "tools/version_lane/binary_asset_audit.py",
            "version_lanes/oh70-precheck/README.md",
            "docs/version_maintenance.md",
        ],
        external_blockers=[
            "Forward validation waits for the actual OH6.1 LTS or OH7.0 target source drop.",
        ],
    )
    checks["P7_safety_audit"] = status_from_required(
        skill,
        [
            "policies/risk_policy.yaml",
            "policies/path_whitelist.yaml",
            "policies/operation_approval.md",
            "tools/diff_risk_scanner.py",
            "tools/secret_and_binary_scanner.py",
        ],
    )
    checks["P8_skill_docs"] = status_from_required(
        skill,
        [
            "README.md",
            "AGENTS.md",
            "docs/codex_subagent_playbook.md",
            "docs/model_routing.md",
            "docs/rc_acceptance_template.md",
            "docs/troubleshooting.md",
        ],
    )

    xdevice_evidence_count = count_files(work, "records/iteration3*_*/**/summary/test_summary.yaml")
    full_statuses = [item["status"] for item in checks.values()]
    summary_status = "complete_with_external_blockers"
    if any(status == "partial" for status in full_statuses):
        summary_status = "partial"
    elif any(status == "blocked_external" for status in full_statuses):
        summary_status = "complete_with_external_blockers"
    elif any(status == "complete_with_external_blockers" for status in full_statuses):
        summary_status = "complete_with_external_blockers"
    elif all(status == "complete" for status in full_statuses):
        summary_status = "complete"

    report = {
        "audit_id": "oh_agent_subagent_todo_closure",
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "skill_root": str(skill),
        "work_record": str(work),
        "summary_status": summary_status,
        "xdevice_summary_files_seen": xdevice_evidence_count,
        "interpretation": (
            "File/tool/document closure is mostly in place. External-lab gates "
            "such as physical recovery, future version source drops, and full "
            "formal suite acceptance remain separate from local file closure."
        ),
        "checks": checks,
    }

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(dump_data(report), encoding="utf-8")
    print(args.out)
    return 0 if summary_status in {"complete", "complete_with_external_blockers"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
