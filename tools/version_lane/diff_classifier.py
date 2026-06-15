#!/usr/bin/env python3
"""Version-lane wrapper around the four-tree upgrade classifier."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

try:
    import yaml
except Exception:  # pragma: no cover
    yaml = None


SCRIPT_DIR = Path(__file__).resolve().parent
TOOL_ROOT = SCRIPT_DIR.parent
COMPARE = TOOL_ROOT / "compare_four_tree_upgrade.py"


def load_data(path: Path) -> Any:
    text = path.read_text(encoding="utf-8")
    if yaml is not None:
        try:
            return yaml.safe_load(text)
        except Exception:
            pass
    return json.loads(text)


def dump_data(data: Any) -> str:
    if yaml is not None:
        return yaml.safe_dump(data, allow_unicode=True, sort_keys=False)
    return json.dumps(data, indent=2, ensure_ascii=False) + "\n"


def write_data(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dump_data(data), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--old-original")
    parser.add_argument("--old-ported", required=True)
    parser.add_argument("--new-original", required=True)
    parser.add_argument("--new-workspace", required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--lane-id", default="version-lane")
    parser.add_argument("--focus-path", action="append", default=[])
    parser.add_argument("--max-records")
    args = parser.parse_args()

    artifact_root = args.out / "four_tree"
    argv = [
        sys.executable,
        str(COMPARE),
        "--old-ported",
        args.old_ported,
        "--new-original",
        args.new_original,
        "--new-workspace",
        args.new_workspace,
        "--out",
        str(artifact_root),
    ]
    if args.old_original:
        argv.extend(["--old-original", args.old_original])
    for focus in args.focus_path:
        argv.extend(["--focus-path", focus])
    if args.max_records:
        argv.extend(["--max-records", args.max_records])
    proc = subprocess.run(argv, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    (args.out / "diff_classifier_run.json").write_text(
        json.dumps({"argv": argv, "returncode": proc.returncode, "stdout": proc.stdout, "stderr": proc.stderr}, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    if proc.returncode != 0:
        return proc.returncode

    matrix_path = artifact_root / "four_tree_conflict_matrix.yaml"
    summary_path = artifact_root / "upgrade_porting_summary.yaml"
    matrix = load_data(matrix_path) if matrix_path.exists() else {}
    summary = load_data(summary_path) if summary_path.exists() else {}
    rows = matrix.get("matrix", []) if isinstance(matrix, dict) else []
    by_decision: dict[str, int] = {}
    for row in rows:
        decision = str(row.get("migration_decision", "unknown"))
        by_decision[decision] = by_decision.get(decision, 0) + 1
    lane = {
        "lane_id": args.lane_id,
        "status": "classified",
        "four_tree_artifact_root": str(artifact_root),
        "decision_counts": by_decision,
        "summary": summary,
        "primary_outputs": {
            "conflict_matrix": str(matrix_path),
            "work_order": str(artifact_root / "upgrade_porting_work_order.yaml"),
            "patch_plan": str(artifact_root / "upgrade_patch_plan.yaml"),
            "external_dependency_followup": str(artifact_root / "external_dependency_followup.yaml"),
            "uncertainty_ledger": str(artifact_root / "uncertainty_ledger.yaml"),
        },
    }
    write_data(args.out / "lane_diff_classification.yaml", lane)
    print(args.out / "lane_diff_classification.yaml")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
