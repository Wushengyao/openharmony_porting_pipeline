#!/usr/bin/env python3
"""Create patch-planner task packets from a version-lane upgrade patch plan."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

try:
    import yaml
except Exception:  # pragma: no cover
    yaml = None


def load_data(path: Path) -> Any:
    text = path.read_text(encoding="utf-8")
    if yaml is not None:
        return yaml.safe_load(text)
    return json.loads(text)


def dump_data(data: Any) -> str:
    if yaml is not None:
        return yaml.safe_dump(data, allow_unicode=True, sort_keys=False)
    return json.dumps(data, indent=2, ensure_ascii=False) + "\n"


def write(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dump_data(data), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--patch-plan", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--max-tasks", type=int, default=20)
    args = parser.parse_args()

    plan = load_data(args.patch_plan)
    patches = plan.get("patches", []) if isinstance(plan, dict) else []
    created = []
    for idx, patch in enumerate(patches[: args.max_tasks], 1):
        task_id = f"version-lane-patch-plan-{idx:03d}"
        task_dir = args.out_dir / task_id
        task = {
            "task_id": task_id,
            "role": "patch-planner",
            "model": "gpt-5.5",
            "model_reasoning_effort": "high",
            "workspace": args.workspace,
            "sandbox": "plan_only",
            "priority": "P1",
            "allowed_tools": ["rg", "git diff --stat", "python tools/diff_risk_scanner.py"],
            "forbidden": ["edit_source", "flash_device", "delete_files", "modify_binary_assets"],
            "path_permissions": {
                "read_roots": [args.workspace],
                "write_roots": [str(task_dir / "outputs")],
                "must_not_touch": ["/"],
            },
            "inputs": [str(args.patch_plan)],
            "outputs": ["patch_plan.yaml", "risk_assessment.md"],
            "budget": {"max_runtime_sec": 900, "max_log_bytes": 200000, "max_tokens_label": "frontier-medium"},
            "stop_conditions": {
                "must_return_structured_summary": True,
                "stop_on_high_risk": True,
            },
            "risk_policy": {
                "escalate_to_main_agent_when": ["boot_related", "partition_related", "hdf_service_startup_related", "binary_dependency"],
                "requires_writer_lock": False,
            },
            "evidence_requirements": {
                "require_file_paths": True,
                "require_command_lines": True,
            },
            "patch_candidate": patch,
        }
        write(task_dir / "task.yaml", task)
        created.append(str(task_dir / "task.yaml"))
    summary = {"created_count": len(created), "tasks": created}
    write(args.out_dir / "patch_planner_task_index.yaml", summary)
    print(args.out_dir / "patch_planner_task_index.yaml")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
