#!/usr/bin/env python3
"""Run an OHJSUnit xDevice module by class batches.

This is useful for large ACTS OHJSUnit HAPs where a full module run may exit
early and xDevice then marks the remaining classes as missed/blocked.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_RUNNER = SCRIPT_DIR / "run_xdevice_probe.py"


def safe_name(value: str, limit: int = 96) -> str:
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", value).strip("_")
    return safe[:limit] or "batch"


def batched(values: list[str], size: int) -> list[list[str]]:
    return [values[index : index + size] for index in range(0, len(values), size)]


def read_classes(args: argparse.Namespace) -> list[str]:
    classes: list[str] = []
    if args.classes:
        classes.extend(item.strip() for item in args.classes.split(",") if item.strip())
    if args.class_list_file:
        for line in args.class_list_file.read_text(encoding="utf-8").splitlines():
            item = line.strip()
            if item and not item.startswith("#"):
                classes.append(item)
    seen: set[str] = set()
    ordered: list[str] = []
    skip = set(args.skip_class or [])
    for item in classes:
        if item in seen or item in skip:
            continue
        seen.add(item)
        ordered.append(item)
    return ordered


def runner_argv(args: argparse.Namespace, batch: list[str], out_dir: Path, no_install: bool) -> list[str]:
    argv = [
        sys.executable,
        str(args.runner),
        "--suite-name",
        args.suite_name,
        "--module",
        args.module,
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
    for class_name in batch:
        argv.extend(["--ohjsunit-class", class_name])
    argv.append("--")
    if no_install:
        argv.append("--no-install")
    return argv


def read_summary(out_dir: Path) -> dict[str, Any]:
    path = out_dir / "summary" / "test_summary.json"
    if not path.exists():
        return {"status": "missing_summary"}
    return json.loads(path.read_text(encoding="utf-8"))


def summary_counts(summary: dict[str, Any]) -> dict[str, Any]:
    runner_summary = summary.get("runner_summary") or {}
    if runner_summary.get("summary_found"):
        return runner_summary
    return summary.get("xml_summary", {}).get("counts") or {}


def run_one(args: argparse.Namespace, index: int, batch: list[str]) -> dict[str, Any]:
    name = f"batch_{index:03d}_{safe_name('_'.join(batch))}"
    out_dir = args.out_dir / name
    out_dir.mkdir(parents=True, exist_ok=True)

    if args.dry_run:
        argv = runner_argv(args, batch, out_dir, no_install=args.prefer_no_install)
        (out_dir / "command.json").write_text(
            json.dumps({"argv": argv, "classes": batch, "no_install": args.prefer_no_install, "dry_run": True}, indent=2) + "\n",
            encoding="utf-8",
        )
        return {
            "classes": batch,
            "status": "planned",
            "attempts": [
                {
                    "out_dir": str(out_dir),
                    "returncode": None,
                    "no_install": args.prefer_no_install,
                    "summary": {"status": "planned"},
                }
            ],
            "selected": {
                "out_dir": str(out_dir),
                "returncode": None,
                "no_install": args.prefer_no_install,
                "summary": {"status": "planned"},
            },
        }

    attempts: list[dict[str, Any]] = []
    for attempt_index, no_install in enumerate([args.prefer_no_install, False], 1):
        if attempt_index == 2 and not args.prefer_no_install:
            break
        attempt_dir = out_dir if attempt_index == 1 else args.out_dir / f"{name}_retry_install"
        attempt_dir.mkdir(parents=True, exist_ok=True)
        argv = runner_argv(args, batch, attempt_dir, no_install=no_install)
        (attempt_dir / "command.json").write_text(
            json.dumps({"argv": argv, "classes": batch, "no_install": no_install}, indent=2) + "\n",
            encoding="utf-8",
        )
        print("+", " ".join(argv), flush=True)
        proc = subprocess.run(argv)
        summary = read_summary(attempt_dir)
        attempt = {
            "out_dir": str(attempt_dir),
            "returncode": proc.returncode,
            "no_install": no_install,
            "summary": summary,
        }
        attempts.append(attempt)
        if proc.returncode == 0 and summary.get("status") == "passed":
            return {"classes": batch, "status": "passed", "attempts": attempts, "selected": attempt}
        if not no_install:
            break
        print(f"batch {index:03d} failed with no-install; retrying with install", flush=True)
    selected = attempts[-1]
    return {"classes": batch, "status": selected["summary"].get("status", "failed"), "attempts": attempts, "selected": selected}


def aggregate(results: list[dict[str, Any]]) -> dict[str, Any]:
    totals = {
        "total": 0,
        "passed": 0,
        "failed": 0,
        "blocked": 0,
        "ignored": 0,
        "unavailable": 0,
    }
    failures: list[dict[str, Any]] = []
    planned_count = 0
    for result in results:
        summary = result["selected"].get("summary", {})
        counts = summary_counts(summary)
        for key in totals:
            value = counts.get(key)
            if isinstance(value, int):
                totals[key] += value
        if result.get("status") == "planned":
            planned_count += 1
        elif result.get("status") != "passed":
            failures.append({
                "classes": result.get("classes", []),
                "status": result.get("status"),
                "out_dir": result["selected"].get("out_dir"),
                "summary": summary,
            })
    status = "planned" if planned_count == len(results) else "passed" if not failures else "failed"
    return {
        "status": status,
        "batch_count": len(results),
        "totals": totals,
        "failures": failures,
        "results": results,
    }


def write_markdown(path: Path, payload: dict[str, Any]) -> None:
    lines = [
        "# OHJSUnit Class Batch Summary",
        "",
        f"- status: {payload['status']}",
        f"- batch_count: {payload['batch_count']}",
        f"- totals: {payload['totals']}",
        "",
        "## Batches",
    ]
    for item in payload["results"]:
        selected = item["selected"]
        summary = selected.get("summary", {})
        counts = summary_counts(summary)
        lines.append(
            f"- {item['status']}: {','.join(item['classes'])} "
            f"counts={counts} out={selected.get('out_dir')}"
        )
    if payload["failures"]:
        lines.extend(["", "## Failures"])
        for item in payload["failures"]:
            lines.append(f"- {item['status']}: {','.join(item['classes'])} out={item['out_dir']}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite-dir", type=Path)
    parser.add_argument("--windows-suite-dir")
    parser.add_argument("--suite-name", required=True)
    parser.add_argument("--module", required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--baseline", type=Path)
    parser.add_argument("--classes")
    parser.add_argument("--class-list-file", type=Path)
    parser.add_argument("--skip-class", action="append")
    parser.add_argument("--batch-size", type=int, default=3)
    parser.add_argument("--prefer-no-install", action="store_true")
    parser.add_argument("--stage-module-only", action="store_true")
    parser.add_argument("--runner", type=Path, default=DEFAULT_RUNNER)
    parser.add_argument("--dry-run", action="store_true", help="Write batch command plans without invoking xDevice.")
    args = parser.parse_args()

    if not args.suite_dir and not args.windows_suite_dir:
        parser.error("one of --suite-dir or --windows-suite-dir is required")
    if args.batch_size <= 0:
        parser.error("--batch-size must be positive")

    classes = read_classes(args)
    if not classes:
        parser.error("no classes provided")
    args.out_dir.mkdir(parents=True, exist_ok=True)
    (args.out_dir / "class_list.txt").write_text("\n".join(classes) + "\n", encoding="utf-8")

    results = []
    for index, batch in enumerate(batched(classes, args.batch_size), 1):
        results.append(run_one(args, index, batch))

    payload = aggregate(results)
    (args.out_dir / "batch_summary.json").write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    write_markdown(args.out_dir / "batch_summary.md", payload)
    return 0 if payload["status"] in {"passed", "planned"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
