#!/usr/bin/env python3
"""Collect or index xDevice report artifacts."""

from __future__ import annotations

import argparse
import base64
import json
import ntpath
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
from common import load_data, write_json  # noqa: E402

DEFAULT_OH_AUTOCTL = SCRIPT_DIR.parent / "oh_autoctl.py"
TEXT_REPORT_SUFFIXES = {".xml", ".ini", ".log", ".txt", ".record", ".html", ".htm"}
COMPRESSED_REPORT_SUFFIXES = {".gz"}


def copy_reports(src: Path, dst: Path) -> list[dict[str, object]]:
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst)
    records = []
    for path in sorted(dst.rglob("*")):
        if path.is_file():
            records.append({"path": str(path), "size": path.stat().st_size})
    return records


def parse_runner_stdout(payload: Any) -> list[dict[str, object]]:
    stdout = payload.get("stdout", "") if isinstance(payload, dict) else ""
    if not stdout.strip():
        return []
    try:
        decoded = json.loads(stdout)
    except json.JSONDecodeError:
        return []
    if isinstance(decoded, list):
        return decoded
    if isinstance(decoded, dict):
        return [decoded]
    return []


def normalize_runner_file(item: dict[str, object]) -> dict[str, object]:
    path = str(item.get("path") or item.get("FullName") or "")
    size = item.get("size", item.get("Length"))
    record: dict[str, object] = {"path": path}
    try:
        record["size"] = int(size)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        pass
    if "LastWriteTime" in item:
        record["last_write_time"] = item["LastWriteTime"]
    return record


def file_list_from_runner(path: Path) -> list[dict[str, object]]:
    payload = load_data(path)
    if isinstance(payload, dict) and "stdout" in payload:
        files = parse_runner_stdout(payload)
        if not files:
            return [{"path": path.as_posix(), "note": "runner file list is raw admin-shell output"}]
        return [normalize_runner_file(item) for item in files]
    if isinstance(payload, list):
        return [normalize_runner_file(item) for item in payload]
    if isinstance(payload, dict):
        return [normalize_runner_file(payload)]
    return []


def windows_common_dir(files: list[dict[str, object]]) -> str:
    paths = [str(item.get("path", "")) for item in files if item.get("path")]
    if not paths:
        return ""
    try:
        return ntpath.commonpath(paths)
    except ValueError:
        return ntpath.dirname(paths[0])


def should_pull_report(item: dict[str, object], max_bytes: int) -> bool:
    path = str(item.get("path", ""))
    suffix = Path(path.replace("\\", "/")).suffix.lower()
    if suffix not in TEXT_REPORT_SUFFIXES and suffix not in COMPRESSED_REPORT_SUFFIXES:
        return False
    try:
        return int(item.get("size", 0)) <= max_bytes
    except (TypeError, ValueError):
        return False


def ps_quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def powershell(script: str) -> str:
    encoded = base64.b64encode(script.encode("utf-16le")).decode("ascii")
    return f"powershell -NoProfile -ExecutionPolicy Bypass -EncodedCommand {encoded}"


def read_windows_text(args: argparse.Namespace, win_path: str) -> subprocess.CompletedProcess[str]:
    script = (
        "$ErrorActionPreference='Stop'; "
        "[Console]::OutputEncoding = [System.Text.Encoding]::UTF8; "
        f"[System.IO.File]::ReadAllText({ps_quote(win_path)}, [System.Text.Encoding]::UTF8)"
    )
    command = [
        sys.executable,
        str(args.oh_autoctl),
        "admin-shell",
        "--command-timeout-sec",
        "120",
        powershell(script),
    ]
    return subprocess.run(command, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def read_windows_base64(args: argparse.Namespace, win_path: str) -> subprocess.CompletedProcess[str]:
    script = (
        "$ErrorActionPreference='Stop'; "
        "[Console]::OutputEncoding = [System.Text.Encoding]::UTF8; "
        f"[Convert]::ToBase64String([System.IO.File]::ReadAllBytes({ps_quote(win_path)}))"
    )
    command = [
        sys.executable,
        str(args.oh_autoctl),
        "admin-shell",
        "--command-timeout-sec",
        "120",
        powershell(script),
    ]
    return subprocess.run(command, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def admin_stdout(text: str) -> str:
    try:
        payload = json.loads(text)
        if isinstance(payload, dict):
            return str(payload.get("stdout", ""))
    except json.JSONDecodeError:
        pass
    return text


def pull_text_reports(args: argparse.Namespace, files: list[dict[str, object]]) -> list[dict[str, object]]:
    report_base = windows_common_dir(files)
    pulled: list[dict[str, object]] = []
    for item in files:
        if not should_pull_report(item, args.max_pull_bytes):
            continue
        win_path = str(item.get("path", ""))
        rel = ntpath.relpath(win_path, report_base) if report_base else ntpath.basename(win_path)
        local = args.out_dir / "reports" / Path(rel.replace("\\", "/"))
        local.parent.mkdir(parents=True, exist_ok=True)
        suffix = Path(win_path.replace("\\", "/")).suffix.lower()
        binary_pull = suffix in COMPRESSED_REPORT_SUFFIXES
        proc = read_windows_base64(args, win_path) if binary_pull else read_windows_text(args, win_path)
        record: dict[str, object] = {
            "windows_path": win_path,
            "local_path": str(local),
            "returncode": proc.returncode,
            "mode": "binary_base64" if binary_pull else "text_utf8",
        }
        if proc.returncode == 0:
            content = admin_stdout(proc.stdout)
            if binary_pull:
                local.write_bytes(base64.b64decode(content.strip()))
            else:
                local.write_text(content, encoding="utf-8")
            record["size"] = local.stat().st_size
        else:
            record["stderr"] = proc.stderr
            record["stdout"] = proc.stdout
        pulled.append(record)
    return pulled


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report-root", type=Path, help="Local xDevice reports directory to copy/index")
    parser.add_argument("--runner-dir", type=Path, help="Directory containing report_file_list.json from run_suite")
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--copy", action="store_true", help="Copy local report root into out-dir/reports")
    parser.add_argument("--pull-text-from-runner", action="store_true")
    parser.add_argument("--oh-autoctl", type=Path, default=DEFAULT_OH_AUTOCTL)
    parser.add_argument("--max-pull-bytes", type=int, default=2_000_000)
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
        if args.pull_text_from_runner:
            pulled = pull_text_reports(args, files)
            write_json(args.out_dir / "pulled_reports.json", {"files": pulled})
            if any(item.get("returncode") == 0 for item in pulled):
                status = "collected_from_runner"
                files.extend(
                    {
                        "path": str(path),
                        "size": path.stat().st_size,
                    }
                    for path in sorted((args.out_dir / "reports").rglob("*"))
                    if path.is_file()
                )

    xml_files = [item for item in files if str(item.get("path", "")).lower().endswith(".xml")]
    html_files = [item for item in files if str(item.get("path", "")).lower().endswith((".html", ".htm"))]
    logs = [
        item
        for item in files
        if str(item.get("path", "")).lower().endswith((".log", ".txt", ".log.gz", ".txt.gz"))
    ]
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
