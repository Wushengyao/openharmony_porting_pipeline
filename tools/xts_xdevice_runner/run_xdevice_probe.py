#!/usr/bin/env python3
"""Run a small xDevice probe and generate structured summaries."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_OH_AUTOCTL = SCRIPT_DIR.parent / "oh_autoctl.py"


def run(argv: list[str]) -> int:
    print("+", " ".join(argv))
    return subprocess.run(argv).returncode


def run_capture(argv: list[str], out_path: Path) -> int:
    print("+", " ".join(argv))
    proc = subprocess.run(argv, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(proc.stdout + proc.stderr, encoding="utf-8")
    return proc.returncode


def oh_auto_shell_args(args: argparse.Namespace, command: str) -> list[str]:
    argv = [
        sys.executable,
        str(args.oh_autoctl),
        "shell",
        command,
        "--wait",
        "--command-timeout-sec",
        str(args.appfreeze_filter_command_timeout_sec),
    ]
    if args.appfreeze_filter_connect_channel:
        argv.extend(["--connect-channel", args.appfreeze_filter_connect_channel])
    if args.appfreeze_filter_connect_target:
        argv.extend(["--connect-target", args.appfreeze_filter_connect_target])
    if args.appfreeze_filter_connect_baudrate:
        argv.extend(["--connect-baudrate", str(args.appfreeze_filter_connect_baudrate)])
    return argv


def set_appfreeze_filter(args: argparse.Namespace) -> int:
    evidence_dir = args.out_dir / "device_params"
    get_cmd = "param get hiviewdfx.appfreeze.filter_bundle_name"
    set_cmd = f"param set hiviewdfx.appfreeze.filter_bundle_name {args.appfreeze_filter_bundle}; {get_cmd}"
    rc = run_capture(
        oh_auto_shell_args(args, get_cmd),
        evidence_dir / "appfreeze_filter_before.json",
    )
    if rc != 0:
        return rc
    return run_capture(
        oh_auto_shell_args(args, set_cmd),
        evidence_dir / "appfreeze_filter_set.json",
    )


def clear_appfreeze_filter(args: argparse.Namespace) -> int:
    evidence_dir = args.out_dir / "device_params"
    clear_cmd = 'param set hiviewdfx.appfreeze.filter_bundle_name ""; param get hiviewdfx.appfreeze.filter_bundle_name'
    return run_capture(
        oh_auto_shell_args(args, clear_cmd),
        evidence_dir / "appfreeze_filter_clear.json",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite-dir", type=Path)
    parser.add_argument("--windows-suite-dir")
    parser.add_argument("--suite-name", required=True)
    parser.add_argument("--module")
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--baseline")
    parser.add_argument("--stage-module-only", action="store_true")
    parser.add_argument(
        "--appfreeze-filter-bundle",
        help=(
            "Set hiviewdfx.appfreeze.filter_bundle_name for the duration of the "
            "xDevice run, then clear it in a finally step. Useful for slow "
            "OHJSUnit ACTS modules that otherwise trigger THREAD_BLOCK_6S."
        ),
    )
    parser.add_argument("--oh-autoctl", type=Path, default=DEFAULT_OH_AUTOCTL)
    parser.add_argument("--appfreeze-filter-connect-channel", choices=["usb", "tcp", "uart"])
    parser.add_argument("--appfreeze-filter-connect-target")
    parser.add_argument("--appfreeze-filter-connect-baudrate", type=int)
    parser.add_argument("--appfreeze-filter-command-timeout-sec", type=float, default=60)
    parser.add_argument("runner_args", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    runner_args = args.runner_args
    if runner_args and runner_args[0] == "--":
        runner_args = runner_args[1:]

    args.out_dir.mkdir(parents=True, exist_ok=True)
    prepare = args.out_dir / "prepare_env.json"
    prep_argv = [sys.executable, str(SCRIPT_DIR / "prepare_env.py"), "--out", str(prepare)]
    if args.suite_dir:
        prep_argv.extend(["--suite-dir", str(args.suite_dir)])
    if args.windows_suite_dir:
        prep_argv.extend(["--windows-suite-dir", args.windows_suite_dir])
    run(prep_argv)

    runner_dir = args.out_dir / "runner"
    run_argv = [
        sys.executable,
        str(SCRIPT_DIR / "run_suite.py"),
        "--out",
        str(runner_dir),
        "--suite-name",
        args.suite_name,
    ]
    if args.suite_dir:
        run_argv.extend(["--suite-dir", str(args.suite_dir)])
    if args.windows_suite_dir:
        run_argv.extend(["--windows-suite-dir", args.windows_suite_dir])
    if args.module:
        run_argv.extend(["--module", args.module])
    if args.stage_module_only:
        run_argv.append("--stage-module-only")
    run_argv.extend(runner_args)
    if args.appfreeze_filter_bundle:
        set_rc = set_appfreeze_filter(args)
        if set_rc != 0:
            clear_appfreeze_filter(args)
            return set_rc
        try:
            rc = run(run_argv)
        finally:
            clear_appfreeze_filter(args)
    else:
        rc = run(run_argv)

    collect_dir = args.out_dir / "reports"
    run(
        [
            sys.executable,
            str(SCRIPT_DIR / "collect_reports.py"),
            "--runner-dir",
            str(runner_dir),
            "--out-dir",
            str(collect_dir),
            "--pull-text-from-runner",
        ]
    )
    parsed = args.out_dir / "parsed_xml.json"
    if (collect_dir / "reports").exists():
        run([sys.executable, str(SCRIPT_DIR / "parse_xml.py"), "--report-root", str(collect_dir / "reports"), "--out", str(parsed)])
    summary_dir = args.out_dir / "summary"
    summary_args = [
        sys.executable,
        str(SCRIPT_DIR / "summarize.py"),
        "--runner-dir",
        str(runner_dir),
        "--out-dir",
        str(summary_dir),
        "--suite-name",
        args.suite_name,
    ]
    if parsed.exists():
        summary_args.extend(["--parsed-xml", str(parsed)])
    if args.module:
        summary_args.extend(["--module", args.module])
    run(summary_args)

    if args.baseline:
        run(
            [
                sys.executable,
                str(SCRIPT_DIR / "compare_baseline.py"),
                "--current",
                str(summary_dir / "test_summary.yaml"),
                "--baseline",
                args.baseline,
                "--out",
                str(args.out_dir / "regression_matrix.yaml"),
            ]
        )
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
