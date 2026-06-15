#!/usr/bin/env python3
"""Version-lane binary asset audit wrapper."""

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
AUDIT = TOOL_ROOT / "audit_binary_assets.py"


def dump_data(data: Any) -> str:
    if yaml is not None:
        return yaml.safe_dump(data, allow_unicode=True, sort_keys=False)
    return json.dumps(data, indent=2, ensure_ascii=False) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage-result")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--lane-id", default="version-lane")
    args = parser.parse_args()

    audit_out = args.out / "binary_asset_audit"
    argv = [sys.executable, str(AUDIT), "--out", str(audit_out)]
    if args.stage_result:
        argv.extend(["--stage-result", args.stage_result])
    proc = subprocess.run(argv, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "binary_asset_audit_run.json").write_text(
        json.dumps({"argv": argv, "returncode": proc.returncode, "stdout": proc.stdout, "stderr": proc.stderr}, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    summary = {
        "lane_id": args.lane_id,
        "status": "completed" if proc.returncode == 0 else "failed",
        "audit_out": str(audit_out),
        "stage_result": args.stage_result or "",
        "notes": "Use this wrapper to keep binary debt attached to the version lane.",
    }
    (args.out / "lane_binary_asset_audit.yaml").write_text(dump_data(summary), encoding="utf-8")
    print(args.out / "lane_binary_asset_audit.yaml")
    return proc.returncode


if __name__ == "__main__":
    raise SystemExit(main())
