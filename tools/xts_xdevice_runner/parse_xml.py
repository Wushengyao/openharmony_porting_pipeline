#!/usr/bin/env python3
"""Parse xDevice XML reports into structured counts and case statuses."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
from common import COUNT_KEYS, FAILURE_STATUSES, derive_status, parse_xml_report, write_json  # noqa: E402


def merge_unique_cases(reports):
    cases = {}
    for report in reports:
        for case in report.get("cases", []):
            key = (
                case.get("classname") or "",
                case.get("name") or "",
            )
            if key == ("", ""):
                key = (report.get("path", ""), str(len(cases)))
            previous = cases.get(key)
            if previous is None or previous.get("status") == "passed":
                cases[key] = {"report": report["path"], **case}
    return list(cases.values())


def counts_from_cases(cases):
    counts = {key: 0 for key in COUNT_KEYS}
    counts["total"] = len(cases)
    for case in cases:
        status = case.get("status")
        if status in counts:
            counts[status] += 1
        elif status == "passed":
            counts["passed"] += 1
        else:
            counts["failed"] += 1
    return counts


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report-root", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    xml_files = sorted(args.report_root.rglob("*.xml")) if args.report_root.exists() else []
    reports = [parse_xml_report(path) for path in xml_files]
    unique_cases = merge_unique_cases(reports)
    counts = counts_from_cases(unique_cases)
    if not unique_cases:
        counts = {key: 0 for key in COUNT_KEYS}
        for item in reports:
            for key, value in item["counts"].items():
                counts[key] += value
    failures = [
        case for case in unique_cases
        if case.get("status") in FAILURE_STATUSES
    ]
    result = {
        "status": derive_status(counts),
        "report_root": str(args.report_root),
        "xml_files": len(xml_files),
        "parsed_xml_files": sum(1 for item in reports if item.get("parsed")),
        "counts": counts,
        "failures": failures[:1000],
        "reports": reports,
    }
    write_json(args.out, result)
    print(args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
