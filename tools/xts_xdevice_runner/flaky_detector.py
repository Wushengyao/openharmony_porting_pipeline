#!/usr/bin/env python3
"""Create a rerun plan from one or more xDevice summaries or XML parse outputs."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
from common import load_data, write_data  # noqa: E402


def failure_keys(payload: object) -> set[str]:
    if not isinstance(payload, dict):
        return set()
    keys = set()
    for item in payload.get("failures", []):
        if isinstance(item, dict):
            keys.add(str(item.get("name") or item.get("test") or item))
    xml = payload.get("xml_summary")
    if isinstance(xml, dict):
        keys |= failure_keys(xml)
    return keys


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", action="append", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--max-rerun", type=int, default=50)
    args = parser.parse_args()

    runs = []
    all_failures: dict[str, int] = {}
    for path in args.input:
        payload = load_data(path)
        failures = failure_keys(payload)
        runs.append({"path": str(path), "failure_count": len(failures), "failures": sorted(failures)})
        for name in failures:
            all_failures[name] = all_failures.get(name, 0) + 1

    total_runs = len(runs)
    rerun = []
    for name, count in sorted(all_failures.items()):
        classification = "stable_failure" if count == total_runs else "suspected_flake"
        rerun.append({"case": name, "seen_in_runs": count, "total_runs": total_runs, "classification": classification})

    result = {
        "status": "no_failures" if not rerun else "rerun_recommended",
        "runs": runs,
        "rerun_cases": rerun[: args.max_rerun],
    }
    write_data(args.out, result)
    print(args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
