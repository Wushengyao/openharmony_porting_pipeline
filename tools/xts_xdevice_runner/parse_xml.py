#!/usr/bin/env python3
"""Parse xDevice XML reports into structured counts and case statuses."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
from common import derive_status, merge_counts, parse_xml_report, write_json  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report-root", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    xml_files = sorted(args.report_root.rglob("*.xml")) if args.report_root.exists() else []
    reports = [parse_xml_report(path) for path in xml_files]
    counts = merge_counts([item["counts"] for item in reports])
    failures = []
    for report in reports:
        for case in report.get("cases", []):
            if case.get("status") not in {"passed", "skipped", "ignored"}:
                failures.append({"report": report["path"], **case})
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
