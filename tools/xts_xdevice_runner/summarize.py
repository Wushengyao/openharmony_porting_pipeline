#!/usr/bin/env python3
"""Generate test_summary.yaml and summary.md from xDevice runner outputs."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
from common import derive_status, load_data, parse_summary_line, write_data, write_json  # noqa: E402


def load_runner_summary(runner_dir: Path) -> dict[str, object]:
    summary_path = runner_dir / "xdevice_summary.json"
    if summary_path.exists():
        return load_data(summary_path)
    run_path = runner_dir / "xdevice_run.json"
    if run_path.exists():
        payload = load_data(run_path)
        stdout = payload.get("stdout", "") if isinstance(payload, dict) else ""
        return parse_summary_line(stdout)
    return {"summary_found": False}


def compact_xml_summary(parsed_xml: object) -> object:
    if not isinstance(parsed_xml, dict):
        return parsed_xml
    reports = parsed_xml.get("reports")
    compact = {
        "status": parsed_xml.get("status"),
        "report_root": parsed_xml.get("report_root"),
        "xml_files": parsed_xml.get("xml_files"),
        "parsed_xml_files": parsed_xml.get("parsed_xml_files"),
        "counts": parsed_xml.get("counts"),
        "failure_count": len(parsed_xml.get("failures") or []),
        "failures": parsed_xml.get("failures") or [],
    }
    if isinstance(reports, list):
        compact["reports"] = [
            {
                "path": item.get("path"),
                "parsed": item.get("parsed"),
                "counts": item.get("counts"),
                "error_count": len(item.get("errors") or []),
            }
            for item in reports
            if isinstance(item, dict)
        ]
    return compact


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runner-dir", type=Path)
    parser.add_argument("--parsed-xml", type=Path)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--suite-name", default="")
    parser.add_argument("--module", default="")
    args = parser.parse_args()

    args.out_dir.mkdir(parents=True, exist_ok=True)
    runner_summary = load_runner_summary(args.runner_dir) if args.runner_dir else {"summary_found": False}
    parsed_xml_raw = load_data(args.parsed_xml) if args.parsed_xml and args.parsed_xml.exists() else {}
    parsed_xml = compact_xml_summary(parsed_xml_raw)
    counts = parsed_xml_raw.get("counts") if isinstance(parsed_xml_raw, dict) else None
    status = derive_status(counts) if isinstance(counts, dict) else "unknown"
    if status == "unknown" and isinstance(runner_summary, dict):
        runner_counts = {
            "total": runner_summary.get("total") or 0,
            "passed": runner_summary.get("passed") or 0,
            "failed": runner_summary.get("failed") or 0,
            "blocked": runner_summary.get("blocked") or 0,
            "ignored": runner_summary.get("ignored") or 0,
            "unavailable": runner_summary.get("unavailable") or 0,
        }
        status = derive_status(runner_counts)
        counts = runner_counts

    test_summary = {
        "status": status,
        "suite_name": args.suite_name,
        "module": args.module,
        "runner_summary": runner_summary,
        "xml_summary": parsed_xml,
    }
    write_data(args.out_dir / "test_summary.yaml", test_summary)
    write_json(args.out_dir / "test_summary.json", test_summary)

    lines = [
        "# xDevice Test Summary",
        "",
        f"- status: `{status}`",
        f"- suite: `{args.suite_name}`",
        f"- module: `{args.module}`",
    ]
    if isinstance(counts, dict):
        lines.extend(
            [
                f"- total: `{counts.get('total', 0)}`",
                f"- passed: `{counts.get('passed', 0)}`",
                f"- failed: `{counts.get('failed', 0)}`",
                f"- blocked: `{counts.get('blocked', 0)}`",
                f"- unavailable: `{counts.get('unavailable', 0)}`",
            ]
        )
    (args.out_dir / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(args.out_dir / "test_summary.yaml")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
