#!/usr/bin/env python3
"""Run native HATS binaries on an OpenHarmony device through oh-auto.

The runner intentionally wraps the existing oh_autoctl.py CLI instead of
talking to the service directly. This keeps one device-operation path and
produces the same evidence files used during manual MusePaper2 validation:
artifact ids, push/chmod/run/pull JSON, run status TSV, and result summaries.
"""

from __future__ import annotations

import argparse
import json
import re
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_OH_AUTOCTL = SCRIPT_DIR / "oh_autoctl.py"


def parse_filter(values: list[str]) -> dict[str, str]:
    filters: dict[str, str] = {}
    for value in values:
        if "=" not in value:
            raise ValueError(f"--filter must be BINARY=FILTER, got: {value}")
        binary, gtest_filter = value.split("=", 1)
        binary = binary.strip()
        if not binary:
            raise ValueError(f"--filter has empty binary name: {value}")
        filters[binary] = gtest_filter.strip()
    return filters


def run_tool(args: argparse.Namespace, argv: list[str]) -> subprocess.CompletedProcess[str]:
    command = [sys.executable, str(args.oh_autoctl)]
    if args.base_url:
        command.extend(["--base-url", args.base_url])
    if args.device_id:
        command.extend(["--device-id", args.device_id])
    command.extend(argv)
    return subprocess.run(command, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def write_json_or_raw(path: Path, proc: subprocess.CompletedProcess[str]) -> tuple[Any | None, bool]:
    text = proc.stdout
    parsed: Any | None = None
    ok = False
    if text.strip():
        try:
            parsed = json.loads(text)
            ok = True
        except json.JSONDecodeError:
            parsed = None
    if ok:
        path.write_text(json.dumps(parsed, indent=2, ensure_ascii=False) + "\n")
    else:
        raw = {
            "returncode": proc.returncode,
            "stdout": proc.stdout,
            "stderr": proc.stderr,
        }
        path.write_text(json.dumps(raw, indent=2, ensure_ascii=False) + "\n")
    return parsed, ok


def status_line(path: Path, binary: str, phase: str, status: str, note: str = "") -> None:
    with path.open("a") as stream:
        stream.write(f"{binary}\t{phase}\t{status}\t{note}\n")


def connect_args(args: argparse.Namespace) -> list[str]:
    result: list[str] = []
    if args.connect_channel:
        result.extend(["--connect-channel", args.connect_channel])
    if args.connect_target:
        result.extend(["--connect-target", args.connect_target])
    if args.connect_baudrate:
        result.extend(["--connect-baudrate", str(args.connect_baudrate)])
    return result


def shell_command(args: argparse.Namespace, command: str, output: Path, timeout: float) -> tuple[Any | None, bool, int]:
    proc = run_tool(
        args,
        [
            "shell",
            "--wait",
            *connect_args(args),
            "--command-timeout-sec",
            str(timeout),
            command,
        ],
    )
    parsed, parsed_ok = write_json_or_raw(output, proc)
    return parsed, parsed_ok, proc.returncode


def upload(args: argparse.Namespace, binary_path: Path, output: Path) -> tuple[str | None, int]:
    proc = run_tool(args, ["upload", str(binary_path), "--id-only"])
    artifact_id = proc.stdout.strip()
    if proc.returncode == 0 and artifact_id:
        output.write_text(artifact_id + "\n")
        return artifact_id, 0
    output.write_text(
        json.dumps(
            {
                "returncode": proc.returncode,
                "stdout": proc.stdout,
                "stderr": proc.stderr,
            },
            indent=2,
            ensure_ascii=False,
        )
        + "\n"
    )
    return None, proc.returncode


def push(args: argparse.Namespace, artifact_id: str, remote_path: str, output: Path) -> tuple[Any | None, bool, int]:
    proc = run_tool(
        args,
        [
            "push",
            remote_path,
            "--artifact-id",
            artifact_id,
            "--wait",
            *connect_args(args),
            "--command-timeout-sec",
            str(args.push_timeout_sec),
        ],
    )
    parsed, parsed_ok = write_json_or_raw(output, proc)
    return parsed, parsed_ok, proc.returncode


def pull(args: argparse.Namespace, remote_path: str, filename: str, output: Path) -> tuple[Any | None, bool, int]:
    proc = run_tool(
        args,
        [
            "pull",
            remote_path,
            "--filename",
            filename,
            "--wait",
            *connect_args(args),
            "--command-timeout-sec",
            str(args.pull_timeout_sec),
        ],
    )
    parsed, parsed_ok = write_json_or_raw(output, proc)
    return parsed, parsed_ok, proc.returncode


def job_status(parsed: Any | None) -> str:
    if not isinstance(parsed, dict):
        return "unknown"
    job = parsed.get("job") if isinstance(parsed.get("job"), dict) else parsed
    if isinstance(job, dict):
        return str(job.get("status", "unknown"))
    return "unknown"


def job_id(parsed: Any | None) -> str:
    if not isinstance(parsed, dict):
        return ""
    job = parsed.get("job") if isinstance(parsed.get("job"), dict) else parsed
    if isinstance(job, dict):
        return str(job.get("job_id", ""))
    return ""


def stdout_text(parsed: Any | None) -> str:
    if not isinstance(parsed, dict):
        return ""
    value = parsed.get("stdout")
    if isinstance(value, str):
        return value
    job = parsed.get("job")
    if isinstance(job, dict) and isinstance(job.get("stdout"), str):
        return job["stdout"]
    return ""


def parse_gtest(stdout: str) -> dict[str, int | None]:
    total: int | None = None
    passed = 0
    failed = 0
    skipped = 0
    match = re.search(r"\[\s*PASSED\s*\]\s*(\d+)\s+tests?\.", stdout)
    if match:
        passed = int(match.group(1))
    match = re.search(r"\[\s*FAILED\s*\]\s*(\d+)\s+tests?", stdout)
    if match:
        failed = int(match.group(1))
    match = re.search(r"\[\s*SKIPPED\s*\]\s*(\d+)\s+tests?", stdout)
    if match:
        skipped = int(match.group(1))
    match = re.search(r"\[==========\]\s*(\d+)\s+tests? from", stdout)
    if match:
        total = int(match.group(1))
    return {
        "total": total,
        "passed": passed,
        "failed": failed,
        "skipped": skipped,
    }


def normalize_filter(raw_filter: str) -> str:
    if not raw_filter:
        return ""
    if raw_filter.startswith("--gtest_filter="):
        return raw_filter
    return f"--gtest_filter={raw_filter}"


def run_cleanup(args: argparse.Namespace, out_dir: Path, when: str) -> None:
    if not args.cleanup_path:
        return
    paths = " ".join(shlex.quote(path) for path in args.cleanup_path)
    command = f"rm -rf {paths}"
    shell_command(args, command, out_dir / f"cleanup_{when}.json", args.command_timeout_sec)


def run_one(args: argparse.Namespace, binary: str, filters: dict[str, str], status_tsv: Path) -> dict[str, Any]:
    if Path(binary).name != binary:
        raise ValueError(f"binary name must not contain a path: {binary}")

    binary_path = args.binary_dir / binary
    if not binary_path.is_file():
        raise FileNotFoundError(f"missing binary: {binary_path}")

    remote_binary = f"{args.remote_dir.rstrip('/')}/{binary}"
    remote_xml = f"{args.remote_dir.rstrip('/')}/{binary}_{args.iteration_tag}.xml"
    xml_filename = f"{binary}_{args.iteration_tag}.xml"

    artifact_id, rc = upload(args, binary_path, args.out / f"{binary}_artifact_id.txt")
    if rc != 0 or not artifact_id:
        status_line(status_tsv, binary, "upload", "fail", str(rc))
        return {
            "binary": binary,
            "job_status": "upload_failed",
            "total": None,
            "passed": 0,
            "failed": 0,
            "skipped": 0,
            "filter": "",
            "job_id": "",
        }
    status_line(status_tsv, binary, "upload", "ok", artifact_id)

    parsed, _, rc = push(args, artifact_id, remote_binary, args.out / f"{binary}_push.json")
    if rc != 0 or job_status(parsed) != "succeeded":
        status_line(status_tsv, binary, "push", "fail", job_status(parsed))
        return {
            "binary": binary,
            "job_status": job_status(parsed),
            "total": None,
            "passed": 0,
            "failed": 0,
            "skipped": 0,
            "filter": "",
            "job_id": job_id(parsed),
        }
    status_line(status_tsv, binary, "push", "ok")

    parsed, _, rc = shell_command(
        args,
        f"chmod 755 {shlex.quote(remote_binary)}",
        args.out / f"{binary}_chmod.json",
        args.command_timeout_sec,
    )
    if rc != 0 or job_status(parsed) != "succeeded":
        status_line(status_tsv, binary, "chmod", "fail", job_status(parsed))
        return {
            "binary": binary,
            "job_status": job_status(parsed),
            "total": None,
            "passed": 0,
            "failed": 0,
            "skipped": 0,
            "filter": "",
            "job_id": job_id(parsed),
        }
    status_line(status_tsv, binary, "chmod", "ok")

    raw_filter = filters.get(binary, "")
    filter_arg = normalize_filter(raw_filter)
    args_for_device = []
    if filter_arg:
        args_for_device.append(shlex.quote(filter_arg))
    args_for_device.append(shlex.quote(f"--gtest_output=xml:{remote_xml}"))
    run_command = (
        f"cd {shlex.quote(args.remote_dir)} && "
        f"./{shlex.quote(binary)} {' '.join(args_for_device)}"
    )
    parsed, _, rc = shell_command(args, run_command, args.out / f"{binary}_run.json", args.run_timeout_sec)
    run_state = job_status(parsed)
    status_line(status_tsv, binary, "run", "ok" if rc == 0 else "fail", raw_filter)

    pull_parsed, _, pull_rc = pull(args, remote_xml, xml_filename, args.out / f"{binary}_pull_xml.json")
    status_line(
        status_tsv,
        binary,
        "pull_xml",
        "ok" if pull_rc == 0 and job_status(pull_parsed) == "succeeded" else "fail",
        job_status(pull_parsed),
    )

    gtest = parse_gtest(stdout_text(parsed))
    return {
        "binary": binary,
        "job_status": run_state,
        "total": gtest["total"],
        "passed": gtest["passed"],
        "failed": gtest["failed"],
        "skipped": gtest["skipped"],
        "filter": raw_filter,
        "job_id": job_id(parsed),
        "pull_job_status": job_status(pull_parsed),
        "pull_job_id": job_id(pull_parsed),
    }


def write_summary(out_dir: Path, rows: list[dict[str, Any]]) -> dict[str, Any]:
    summary = {
        "total_binaries": len(rows),
        "passed_binaries": sum(
            1
            for row in rows
            if row.get("job_status") == "succeeded" and int(row.get("failed") or 0) == 0
        ),
        "total_tests": sum(int(row.get("total") or 0) for row in rows),
        "passed_tests": sum(int(row.get("passed") or 0) for row in rows),
        "failed_tests": sum(int(row.get("failed") or 0) for row in rows),
        "skipped_tests": sum(int(row.get("skipped") or 0) for row in rows),
        "rows": rows,
    }
    (out_dir / "hats_native_result_summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False) + "\n"
    )
    with (out_dir / "hats_native_result_summary.tsv").open("w") as stream:
        stream.write("binary\tjob_status\ttotal\tpassed\tfailed\tskipped\tfilter\tjob_id\n")
        for row in rows:
            stream.write(
                f"{row.get('binary')}\t{row.get('job_status')}\t"
                f"{row.get('total')}\t{row.get('passed')}\t{row.get('failed')}\t"
                f"{row.get('skipped')}\t{row.get('filter')}\t{row.get('job_id')}\n"
            )
    return summary


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary-dir", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--iteration-tag", required=True)
    parser.add_argument("--oh-autoctl", type=Path, default=DEFAULT_OH_AUTOCTL)
    parser.add_argument("--base-url")
    parser.add_argument("--device-id", default="default")
    parser.add_argument("--connect-channel", default="usb", choices=["usb", "tcp", "uart"])
    parser.add_argument("--connect-target", default="0123456789ABCDEF")
    parser.add_argument("--connect-baudrate", type=int)
    parser.add_argument("--remote-dir", default="/data/local/tmp")
    parser.add_argument("--push-timeout-sec", type=float, default=120)
    parser.add_argument("--pull-timeout-sec", type=float, default=60)
    parser.add_argument("--command-timeout-sec", type=float, default=60)
    parser.add_argument("--run-timeout-sec", type=float, default=180)
    parser.add_argument(
        "--filter",
        action="append",
        default=[],
        help="Per-binary gtest filter, in the form BINARY=FILTER or BINARY=--gtest_filter=FILTER.",
    )
    parser.add_argument(
        "--cleanup-path",
        action="append",
        default=[],
        help="Device path to rm -rf before and after the run. Repeat for multiple paths.",
    )
    parser.add_argument("--allow-test-failures", action="store_true")
    parser.add_argument("binaries", nargs="+")
    args = parser.parse_args(argv)
    args.binary_dir = args.binary_dir.resolve()
    args.out = args.out.resolve()
    args.oh_autoctl = args.oh_autoctl.resolve()
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    args.out.mkdir(parents=True, exist_ok=True)
    filters = parse_filter(args.filter)

    (args.out / "hats_native_run_order.txt").write_text("\n".join(args.binaries) + "\n")
    status_tsv = args.out / "hats_native_run_status.tsv"
    status_tsv.write_text("binary\tphase\tstatus\tnote\n")

    run_cleanup(args, args.out, "before")
    rows = []
    for binary in args.binaries:
        print(f"===== {binary} =====", flush=True)
        try:
            rows.append(run_one(args, binary, filters, status_tsv))
        except Exception as exc:  # noqa: BLE001 - keep evidence and continue.
            status_line(status_tsv, binary, "exception", "fail", str(exc))
            rows.append(
                {
                    "binary": binary,
                    "job_status": "runner_exception",
                    "total": None,
                    "passed": 0,
                    "failed": 1,
                    "skipped": 0,
                    "filter": filters.get(binary, ""),
                    "job_id": "",
                    "error": str(exc),
                }
            )
    run_cleanup(args, args.out, "after")

    summary = write_summary(args.out, rows)
    print(json.dumps(summary, indent=2, ensure_ascii=False))

    if args.allow_test_failures:
        return 0
    if summary["failed_tests"] or summary["passed_binaries"] != summary["total_binaries"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
