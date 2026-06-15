#!/usr/bin/env python3
"""Run an xDevice suite through the existing oh-auto backed runner."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
LEGACY_RUNNER = SCRIPT_DIR.parent / "oh_xts_xdevice_runner.py"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite-dir", type=Path)
    parser.add_argument("--windows-suite-dir")
    parser.add_argument("--suite-name")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--run-id")
    parser.add_argument("--stage-root")
    parser.add_argument("--sn")
    parser.add_argument("--module")
    parser.add_argument("--report-name")
    parser.add_argument("--resource-dir")
    parser.add_argument("--tools-dir", type=Path)
    parser.add_argument("--extra", action="append", default=[])
    parser.add_argument("--stdin-line", action="append", default=[])
    parser.add_argument("--windows-python")
    parser.add_argument("--hdc-path")
    parser.add_argument("--oh-autoctl", type=Path)
    parser.add_argument("--base-url")
    parser.add_argument("--device-id")
    parser.add_argument("--command-timeout-sec")
    parser.add_argument("--upload-timeout-sec")
    parser.add_argument("--native-test-timeout-ms")
    parser.add_argument("--no-install", action="store_true")
    parser.add_argument("--stage-module-only", action="store_true")
    args = parser.parse_args()

    argv = [sys.executable, str(LEGACY_RUNNER), "--out", str(args.out)]
    for name in [
        "suite_dir",
        "windows_suite_dir",
        "suite_name",
        "run_id",
        "stage_root",
        "sn",
        "module",
        "report_name",
        "resource_dir",
        "windows_python",
        "hdc_path",
        "oh_autoctl",
        "base_url",
        "device_id",
        "command_timeout_sec",
        "upload_timeout_sec",
        "native_test_timeout_ms",
    ]:
        value = getattr(args, name)
        if value is not None:
            argv.extend(["--" + name.replace("_", "-"), str(value)])
    if args.tools_dir is not None:
        argv.extend(["--tools-dir", str(args.tools_dir)])
    for extra in args.extra:
        argv.extend(["--extra", extra])
    for stdin_line in args.stdin_line:
        argv.extend(["--stdin-line", stdin_line])
    if args.no_install:
        argv.append("--no-install")
    if args.stage_module_only:
        argv.append("--stage-module-only")

    proc = subprocess.run(argv)
    return proc.returncode


if __name__ == "__main__":
    raise SystemExit(main())
