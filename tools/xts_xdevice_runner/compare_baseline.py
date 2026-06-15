#!/usr/bin/env python3
"""Compare a current xDevice summary with a baseline summary or acceptance state."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
from common import load_data, write_data  # noqa: E402


ORDER = {"passed": 4, "partial": 3, "blocked_or_unavailable": 2, "failed": 1, "unknown": 0, "not_run": 0}


def extract_counts(payload: object) -> dict[str, int]:
    if not isinstance(payload, dict):
        return {}
    if isinstance(payload.get("xml_summary"), dict):
        counts = payload["xml_summary"].get("counts")
        if isinstance(counts, dict):
            return {key: int(value or 0) for key, value in counts.items() if isinstance(value, int)}
    if isinstance(payload.get("counts"), dict):
        return {key: int(value or 0) for key, value in payload["counts"].items() if isinstance(value, int)}
    runner = payload.get("runner_summary")
    if isinstance(runner, dict):
        return {
            key: int(runner.get(key) or 0)
            for key in ["total", "passed", "failed", "blocked", "ignored", "unavailable"]
        }
    return {}


def extract_status(payload: object) -> str:
    if isinstance(payload, dict):
        if isinstance(payload.get("status"), str):
            return payload["status"]
        gates = payload.get("gates")
        if isinstance(gates, dict):
            formal = gates.get("xdevice_formal")
            if isinstance(formal, dict):
                return str(formal.get("status", "unknown"))
    return "unknown"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--current", type=Path, required=True)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    current = load_data(args.current)
    baseline = load_data(args.baseline)
    cur_counts = extract_counts(current)
    base_counts = extract_counts(baseline)
    cur_status = extract_status(current)
    base_status = extract_status(baseline)

    findings = []
    if cur_counts and base_counts:
        if cur_counts.get("failed", 0) > base_counts.get("failed", 0):
            findings.append("failed_count_increased")
        if cur_counts.get("passed", 0) < base_counts.get("passed", 0):
            findings.append("passed_count_decreased")
    if ORDER.get(cur_status, 0) < ORDER.get(base_status, 0):
        findings.append("status_regressed")

    result = {
        "status": "regression" if findings else "no_regression_detected",
        "current": {"path": str(args.current), "status": cur_status, "counts": cur_counts},
        "baseline": {"path": str(args.baseline), "status": base_status, "counts": base_counts},
        "findings": findings,
    }
    write_data(args.out, result)
    print(args.out)
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
