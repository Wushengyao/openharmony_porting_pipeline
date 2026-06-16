#!/usr/bin/env python3
"""Run xDevice modules sequentially and keep resumable long-run state.

This runner is intended for long ACTS/HATS/SSTS/DCTS sweeps where the device
must have a single foreground owner for many hours. It wraps run_xdevice_probe.py
per module, writes state after every module, and lets other agents analyze only
the files it has already produced.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_RUNNER = SCRIPT_DIR / "run_xdevice_probe.py"
COUNT_KEYS = ["total", "passed", "failed", "error", "timeout", "blocked", "ignored", "skipped", "unavailable"]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def safe_name(value: str, limit: int = 96) -> str:
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", value).strip("_")
    return safe[:limit] or "module"


def read_modules(args: argparse.Namespace) -> list[str]:
    modules: list[str] = []
    if args.modules:
        modules.extend(item.strip() for item in args.modules.split(",") if item.strip())
    if args.module_list_file:
        for line in args.module_list_file.read_text(encoding="utf-8").splitlines():
            item = line.strip()
            if item and not item.startswith("#"):
                modules.append(item.split()[0])
    if args.discover_testcases:
        if not args.suite_dir:
            raise SystemExit("--discover-testcases requires --suite-dir")
        testcases = args.suite_dir / "testcases"
        modules.extend(path.stem for path in sorted(testcases.glob("*.json")))

    skip = set(args.skip_module or [])
    seen: set[str] = set()
    ordered: list[str] = []
    for module in modules:
        if module in seen or module in skip:
            continue
        if args.module_prefix and not module.startswith(args.module_prefix):
            continue
        seen.add(module)
        ordered.append(module)
    if args.max_modules is not None:
        ordered = ordered[: args.max_modules]
    return ordered


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def counts_from_summary(summary: dict[str, Any]) -> dict[str, int]:
    runner_summary = summary.get("runner_summary") or {}
    if isinstance(runner_summary, dict) and runner_summary.get("summary_found"):
        return {key: runner_summary.get(key, 0) or 0 for key in COUNT_KEYS}
    xml_counts = ((summary.get("xml_summary") or {}).get("counts") or {})
    if isinstance(xml_counts, dict):
        return {key: xml_counts.get(key, 0) or 0 for key in COUNT_KEYS}
    return {key: 0 for key in COUNT_KEYS}


def aggregate_results(results: list[dict[str, Any]], total_modules: int, dry_run: bool) -> dict[str, Any]:
    totals = {key: 0 for key in COUNT_KEYS}
    failures: list[dict[str, Any]] = []
    passed = 0
    planned = 0
    for result in results:
        status = result.get("status")
        previous_passed_skip = status == "skipped" and result.get("skip_reason") == "previous_passed"
        if status == "planned":
            planned += 1
        if status == "passed" or previous_passed_skip:
            passed += 1
        if status not in {"passed", "planned", "skipped"}:
            failures.append({
                "module": result.get("module"),
                "status": status,
                "out_dir": result.get("out_dir"),
                "returncode": result.get("returncode"),
                "counts": result.get("counts", {}),
            })
        for key, value in (result.get("counts") or {}).items():
            if key in totals and isinstance(value, int):
                totals[key] += value
    if dry_run:
        status = "planned"
    elif failures:
        status = "failed"
    elif passed == total_modules and total_modules:
        status = "passed"
    else:
        status = "running"
    return {
        "status": status,
        "module_count": total_modules,
        "completed_count": len([item for item in results if item.get("status") != "skipped"]),
        "passed_count": passed,
        "planned_count": planned,
        "totals": totals,
        "failures": failures,
    }


def load_existing_results(out_dir: Path) -> dict[str, dict[str, Any]]:
    state = read_json(out_dir / "state.json")
    results = state.get("results") if isinstance(state, dict) else None
    if not isinstance(results, list):
        return {}
    by_module: dict[str, dict[str, Any]] = {}
    for item in results:
        module = item.get("module") if isinstance(item, dict) else None
        if isinstance(module, str):
            by_module[module] = item
    return by_module


def runner_argv(args: argparse.Namespace, module: str, out_dir: Path, runner_args: list[str]) -> list[str]:
    argv = [
        sys.executable,
        str(args.runner),
        "--suite-name",
        args.suite_name,
        "--module",
        module,
        "--out-dir",
        str(out_dir),
    ]
    if args.suite_dir:
        argv.extend(["--suite-dir", str(args.suite_dir)])
    if args.windows_suite_dir:
        argv.extend(["--windows-suite-dir", args.windows_suite_dir])
    if args.baseline:
        argv.extend(["--baseline", str(args.baseline)])
    if args.stage_module_only:
        argv.append("--stage-module-only")
    if args.probe_dry_run:
        argv.append("--dry-run")
    if runner_args:
        argv.append("--")
        argv.extend(runner_args)
    return argv


def write_state(args: argparse.Namespace, modules: list[str], results: list[dict[str, Any]], dry_run: bool) -> dict[str, Any]:
    payload = {
        "suite_name": args.suite_name,
        "suite_dir": str(args.suite_dir) if args.suite_dir else None,
        "windows_suite_dir": args.windows_suite_dir,
        "stage_module_only": args.stage_module_only,
        "started_at": args.started_at,
        "updated_at": utc_now(),
        "modules": modules,
        "summary": aggregate_results(results, len(modules), dry_run),
        "results": results,
    }
    write_json(args.out_dir / "state.json", payload)
    write_markdown(args.out_dir / "queue_summary.md", payload)
    return payload


def write_markdown(path: Path, payload: dict[str, Any]) -> None:
    summary = payload["summary"]
    lines = [
        "# xDevice Module Queue Summary",
        "",
        f"- status: {summary['status']}",
        f"- suite: {payload['suite_name']}",
        f"- module_count: {summary['module_count']}",
        f"- completed_count: {summary['completed_count']}",
        f"- passed_count: {summary['passed_count']}",
        f"- totals: {summary['totals']}",
        "",
        "## Modules",
    ]
    for item in payload["results"]:
        lines.append(
            f"- {item.get('status')}: {item.get('module')} "
            f"counts={item.get('counts', {})} out={item.get('out_dir')}"
        )
    if summary["failures"]:
        lines.extend(["", "## Failures"])
        for item in summary["failures"]:
            lines.append(f"- {item['status']}: {item['module']} counts={item['counts']} out={item['out_dir']}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run_one(args: argparse.Namespace, index: int, module: str, runner_args: list[str], dry_run: bool) -> dict[str, Any]:
    out_dir = args.out_dir / f"module_{index:04d}_{safe_name(module)}"
    out_dir.mkdir(parents=True, exist_ok=True)
    argv = runner_argv(args, module, out_dir, runner_args)
    write_json(out_dir / "command.json", {"argv": argv, "module": module, "dry_run": dry_run or args.probe_dry_run})
    if dry_run:
        return {
            "module": module,
            "status": "planned",
            "returncode": None,
            "out_dir": str(out_dir),
            "started_at": None,
            "finished_at": None,
            "counts": {key: 0 for key in COUNT_KEYS},
        }

    started = utc_now()
    print("+", " ".join(argv), flush=True)
    proc = subprocess.run(argv)
    finished = utc_now()
    summary = read_json(out_dir / "summary" / "test_summary.json")
    counts = counts_from_summary(summary)
    status = summary.get("status") if isinstance(summary, dict) else "missing_summary"
    if proc.returncode != 0 and status == "passed":
        status = "runner_failed_after_pass"
    return {
        "module": module,
        "status": status or "unknown",
        "returncode": proc.returncode,
        "out_dir": str(out_dir),
        "started_at": started,
        "finished_at": finished,
        "counts": counts,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite-dir", type=Path)
    parser.add_argument("--windows-suite-dir")
    parser.add_argument("--suite-name", required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--baseline", type=Path)
    parser.add_argument("--modules", help="Comma-separated module names.")
    parser.add_argument("--module-list-file", type=Path)
    parser.add_argument("--discover-testcases", action="store_true", help="Use every JSON stem under <suite-dir>/testcases as a module.")
    parser.add_argument("--module-prefix", help="Optional prefix filter when discovering modules.")
    parser.add_argument("--skip-module", action="append")
    parser.add_argument("--max-modules", type=int)
    parser.add_argument("--stage-module-only", action="store_true")
    parser.add_argument("--runner", type=Path, default=DEFAULT_RUNNER)
    parser.add_argument("--resume", action="store_true", help="Skip modules that already passed in state.json.")
    parser.add_argument("--rerun-passed", action="store_true", help="With --resume, rerun previously passed modules too.")
    parser.add_argument("--stop-on-failure", action="store_true")
    parser.add_argument("--dry-run", action="store_true", help="Write queue plans only; do not invoke xDevice.")
    parser.add_argument("--probe-dry-run", action="store_true", help="Invoke run_xdevice_probe.py --dry-run per module.")
    parser.add_argument("runner_args", nargs=argparse.REMAINDER)
    args = parser.parse_args()

    if not args.suite_dir and not args.windows_suite_dir:
        parser.error("one of --suite-dir or --windows-suite-dir is required")
    args.out_dir.mkdir(parents=True, exist_ok=True)
    args.started_at = utc_now()
    runner_args = args.runner_args
    if runner_args and runner_args[0] == "--":
        runner_args = runner_args[1:]

    modules = read_modules(args)
    if not modules:
        parser.error("no modules provided")

    existing = load_existing_results(args.out_dir) if args.resume else {}
    results: list[dict[str, Any]] = []
    for index, module in enumerate(modules, 1):
        previous = existing.get(module)
        if previous and previous.get("status") == "passed" and not args.rerun_passed:
            skipped = dict(previous)
            skipped["status"] = "skipped"
            skipped["skip_reason"] = "previous_passed"
            results.append(skipped)
            write_state(args, modules, results, dry_run=args.dry_run)
            continue
        result = run_one(args, index, module, runner_args, dry_run=args.dry_run)
        results.append(result)
        write_state(args, modules, results, dry_run=args.dry_run)
        if args.stop_on_failure and result.get("status") != "passed" and not args.dry_run:
            break

    payload = write_state(args, modules, results, dry_run=args.dry_run)
    return 0 if payload["summary"]["status"] in {"passed", "planned"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
