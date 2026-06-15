#!/usr/bin/env python3
"""Run a small xDevice probe and generate structured summaries."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent


def run(argv: list[str]) -> int:
    print("+", " ".join(argv))
    return subprocess.run(argv).returncode


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite-dir", type=Path)
    parser.add_argument("--windows-suite-dir")
    parser.add_argument("--suite-name", required=True)
    parser.add_argument("--module")
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--baseline")
    parser.add_argument("--stage-module-only", action="store_true")
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
    rc = run(run_argv)

    collect_dir = args.out_dir / "reports"
    run([sys.executable, str(SCRIPT_DIR / "collect_reports.py"), "--runner-dir", str(runner_dir), "--out-dir", str(collect_dir)])
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
