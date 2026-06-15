#!/usr/bin/env python3
"""Collect or index xDevice report artifacts."""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
from common import load_data, write_json  # noqa: E402


def copy_reports(src: Path, dst: Path) -> list[dict[str, object]]:
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst)
    records = []
    for path in sorted(dst.rglob("*")):
        if path.is_file():
            records.append({"path": str(path), "size": path.stat().st_size})
    return records


def file_list_from_runner(path: Path) -> list[dict[str, object]]:
    payload = load_data(path)
    if isinstance(payload, dict) and "stdout" in payload:
        try:
            payload = load_data(Path(path.parent / "_report_file_list_payload.json"))
        except Exception:
            return [{"path": path.as_posix(), "note": "runner file list is raw admin-shell output"}]
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        return [payload]
    return []


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report-root", type=Path, help="Local xDevice reports directory to copy/index")
    parser.add_argument("--runner-dir", type=Path, help="Directory containing report_file_list.json from run_suite")
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--copy", action="store_true", help="Copy local report root into out-dir/reports")
    args = parser.parse_args()

    args.out_dir.mkdir(parents=True, exist_ok=True)
    files: list[dict[str, object]] = []
    status = "not_run"
    report_root = ""

    if args.report_root:
        report_root = str(args.report_root)
        if args.report_root.is_dir():
            status = "collected"
            files = copy_reports(args.report_root, args.out_dir / "reports") if args.copy else [
                {"path": str(path), "size": path.stat().st_size}
                for path in sorted(args.report_root.rglob("*"))
                if path.is_file()
            ]
        else:
            status = "missing"
    elif args.runner_dir and (args.runner_dir / "report_file_list.json").exists():
        status = "indexed_from_runner"
        report_root = str(args.runner_dir)
        files = file_list_from_runner(args.runner_dir / "report_file_list.json")

    xml_files = [item for item in files if str(item.get("path", "")).lower().endswith(".xml")]
    html_files = [item for item in files if str(item.get("path", "")).lower().endswith((".html", ".htm"))]
    logs = [item for item in files if str(item.get("path", "")).lower().endswith((".log", ".txt"))]
    result = {
        "status": status,
        "report_root": report_root,
        "file_count": len(files),
        "xml_files": len(xml_files),
        "html_files": len(html_files),
        "log_files": len(logs),
        "files": files[:5000],
    }
    write_json(args.out_dir / "collected_reports.json", result)
    print(args.out_dir / "collected_reports.json")
    return 0 if status not in {"missing"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
