#!/usr/bin/env python3
"""Stage and run an OpenHarmony xDevice suite through the Windows oh-auto host."""

from __future__ import annotations

import argparse
import base64
import json
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_OH_AUTOCTL = SCRIPT_DIR / "oh_autoctl.py"
DEFAULT_WINDOWS_PYTHON = (
    r"C:\Users\sheng\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
)
DEFAULT_HDC = r"D:\ohos_toolchains\hdc.exe"


def write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def run_oh_auto(args: argparse.Namespace, argv: list[str]) -> subprocess.CompletedProcess[str]:
    command = [sys.executable, str(args.oh_autoctl)]
    if args.base_url:
        command.extend(["--base-url", args.base_url])
    if args.device_id:
        command.extend(["--device-id", args.device_id])
    command.extend(argv)
    return subprocess.run(command, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def write_proc(path: Path, proc: subprocess.CompletedProcess[str]) -> Any | None:
    payload: Any
    parsed: Any | None = None
    if proc.stdout.strip():
        try:
            parsed = json.loads(proc.stdout)
            payload = parsed
        except json.JSONDecodeError:
            payload = {"returncode": proc.returncode, "stdout": proc.stdout, "stderr": proc.stderr}
    else:
        payload = {"returncode": proc.returncode, "stdout": proc.stdout, "stderr": proc.stderr}
    write_json(path, payload)
    return parsed


def ps_quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def powershell(script: str) -> str:
    encoded = base64.b64encode(script.encode("utf-16le")).decode("ascii")
    return f"powershell -NoProfile -ExecutionPolicy Bypass -EncodedCommand {encoded}"


def win_basename(path: str) -> str:
    return path.rstrip("\\/").replace("/", "\\").rsplit("\\", 1)[-1]


def win_parent(path: str) -> str:
    normalized = path.rstrip("\\/").replace("/", "\\")
    if "\\" not in normalized:
        return "."
    return normalized.rsplit("\\", 1)[0]


def admin_shell(args: argparse.Namespace, script: str, name: str, timeout: float | None = None) -> Any | None:
    proc = run_oh_auto(
        args,
        [
            "admin-shell",
            "--command-timeout-sec",
            str(timeout or args.command_timeout_sec),
            powershell(script),
        ],
    )
    parsed = write_proc(args.out / f"{name}.json", proc)
    if proc.returncode != 0:
        raise RuntimeError(f"admin-shell {name} failed: {proc.stderr or proc.stdout}")
    if isinstance(parsed, dict) and not parsed.get("ok", False):
        raise RuntimeError(f"admin-shell {name} returned ok=false")
    return parsed


def safe_testcase_name(value: str) -> str | None:
    normalized = value.replace("\\", "/")
    if not normalized or "/" in normalized or normalized in {".", ".."}:
        return None
    return normalized


def collect_strings(payload: Any) -> list[str]:
    strings: list[str] = []
    if isinstance(payload, str):
        strings.append(payload)
    elif isinstance(payload, list):
        for item in payload:
            strings.extend(collect_strings(item))
    elif isinstance(payload, dict):
        for item in payload.values():
            strings.extend(collect_strings(item))
    return strings


def collect_module_testcases(suite_dir: Path, module: str) -> list[Path]:
    testcase_dir = suite_dir / "testcases"
    candidates = [module, f"{module}.hap", f"{module}.hsp", f"{module}.json", f"{module}.moduleInfo"]
    module_json = testcase_dir / f"{module}.json"
    if module_json.exists():
        try:
            candidates.extend(collect_strings(json.loads(module_json.read_text(encoding="utf-8"))))
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"failed to parse module json: {module_json}") from exc

    selected: set[Path] = set()
    for candidate in candidates:
        name = safe_testcase_name(candidate)
        if not name:
            continue
        path = testcase_dir / name
        if path.is_file():
            selected.add(path)
    if not selected:
        raise FileNotFoundError(f"no testcase files found for module: {module}")
    return sorted(selected)


def copy_optional_file(src: Path, dst: Path) -> None:
    if src.is_file():
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)


def make_module_staging_dir(args: argparse.Namespace, suite_dir: Path) -> Path:
    if not args.module:
        raise ValueError("--stage-module-only requires --module")
    stage_parent = args.out / "_module_stage"
    stage_dir = stage_parent / suite_dir.name
    if stage_parent.exists():
        shutil.rmtree(stage_parent)
    stage_dir.mkdir(parents=True)

    shutil.copytree(suite_dir / "config", stage_dir / "config")
    shutil.copytree(suite_dir / "tools", stage_dir / "tools")
    copy_optional_file(suite_dir / "run.sh", stage_dir / "run.sh")
    copy_optional_file(suite_dir / "run.bat", stage_dir / "run.bat")

    testcase_dst = stage_dir / "testcases"
    testcase_dst.mkdir()
    staged_testcases: list[str] = []
    for src in collect_module_testcases(suite_dir, args.module):
        shutil.copy2(src, testcase_dst / src.name)
        staged_testcases.append(src.name)

    args.module_staged_testcases = staged_testcases
    write_json(
        args.out / "module_staging_manifest.json",
        {
            "suite_dir": str(suite_dir),
            "module": args.module,
            "stage_dir": str(stage_dir),
            "testcases": staged_testcases,
        },
    )
    return stage_dir


def make_zip(args: argparse.Namespace) -> Path:
    suite_dir = args.suite_dir.resolve()
    if not suite_dir.is_dir():
        raise FileNotFoundError(f"suite dir not found: {suite_dir}")
    required = ["config/user_config.xml", "testcases", "tools"]
    missing = [item for item in required if not (suite_dir / item).exists()]
    if missing:
        raise FileNotFoundError(f"suite dir is missing xDevice entries: {', '.join(missing)}")
    zip_root = suite_dir.parent
    zip_dir = suite_dir
    if args.stage_module_only:
        zip_dir = make_module_staging_dir(args, suite_dir)
        zip_root = zip_dir.parent
    zip_base = args.out / f"{suite_dir.name}_{args.run_id}"
    zip_path = zip_base.with_suffix(".zip")
    if zip_path.exists():
        zip_path.unlink()
    shutil.make_archive(str(zip_base), "zip", root_dir=zip_root, base_dir=zip_dir.name)
    return zip_path


def upload_and_promote(args: argparse.Namespace, zip_path: Path, win_zip: str) -> str:
    proc = run_oh_auto(args, ["--timeout-sec", str(args.upload_timeout_sec), "upload", str(zip_path), "--id-only"])
    artifact_id = proc.stdout.strip()
    (args.out / "suite_zip_upload.txt").write_text(
        artifact_id if proc.returncode == 0 else json.dumps(
            {"returncode": proc.returncode, "stdout": proc.stdout, "stderr": proc.stderr},
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    if proc.returncode != 0 or not artifact_id:
        raise RuntimeError("suite zip upload failed")
    proc = run_oh_auto(
        args,
        [
            "--timeout-sec",
            str(args.upload_timeout_sec),
            "promote-artifact",
            artifact_id,
            "--dest",
            win_zip,
        ],
    )
    write_proc(args.out / "suite_zip_promote.json", proc)
    if proc.returncode != 0:
        raise RuntimeError("suite zip promote failed")
    return artifact_id


def suite_windows_paths(args: argparse.Namespace, suite_name: str) -> tuple[str, str]:
    if args.windows_suite_dir:
        suite_dir = args.windows_suite_dir.rstrip("\\/")
        run_root = win_parent(suite_dir)
        return run_root, suite_dir
    run_root = args.stage_root.rstrip("\\/") + "\\" + args.run_id
    suite_dir = run_root + "\\" + suite_name
    return run_root, suite_dir


def build_run_command(args: argparse.Namespace, suite_name: str, suite_dir: str) -> str:
    py = ps_quote(args.windows_python)
    sn = ps_quote(args.sn)
    config = ps_quote(suite_dir + r"\config\user_config.xml")
    tcpath = ps_quote(suite_dir + r"\testcases")
    report = ps_quote(args.report_name)
    parts = [
        f"& {py} -m xdevice run",
    ]
    if args.module:
        parts.append(f"-l {ps_quote(args.module)}")
    else:
        parts.append(ps_quote(suite_name))
    parts.extend([f"-sn {sn}", f"-c {config}", f"-tcpath {tcpath}", f"-rp {report}"])
    if args.resource_dir:
        parts.append(f"-respath {ps_quote(args.resource_dir)}")
    if args.extra:
        parts.extend(args.extra)
    return " ".join(parts)


def summarize_xdevice(args: argparse.Namespace, parsed: Any | None) -> None:
    stdout = parsed.get("stdout", "") if isinstance(parsed, dict) else ""
    summary = {
        "summary_found": False,
        "modules": None,
        "run_modules": None,
        "total": None,
        "passed": None,
        "failed": None,
        "blocked": None,
        "ignored": None,
        "unavailable": None,
        "raw_summary_line": "",
    }
    for line in stdout.splitlines():
        if "Test Summary:" not in line:
            continue
        summary["summary_found"] = True
        summary["raw_summary_line"] = line
        for key in ["modules", "run modules", "total", "passed", "failed", "blocked", "ignored", "unavailable"]:
            match = re.search(rf"{re.escape(key)}:\s*(\d+)", line)
            if match:
                summary[key.replace(" ", "_")] = int(match.group(1))
    write_json(args.out / "xdevice_summary.json", summary)
    if not summary["summary_found"] and ("[ERROR]" in stdout or "ERROR]" in stdout):
        raise RuntimeError("xDevice run did not produce Test Summary and logged an error")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite-dir", type=Path, help="Linux-side generated suite root, e.g. out/musepaper2/suites/hats")
    parser.add_argument("--windows-suite-dir", help="Already-staged Windows suite root; skips zip upload/extract")
    parser.add_argument("--suite-name", help="Suite command name; defaults to suite directory name")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--run-id", default=time.strftime("xts_%Y%m%d_%H%M%S"))
    parser.add_argument("--stage-root", default=r"F:\images\PortingTest\6.1\xts_runs")
    parser.add_argument("--sn", default="0123456789ABCDEF")
    parser.add_argument("--module", help="Single module for a first probe, e.g. HatsGetcwdTest")
    parser.add_argument("--report-name", default=None)
    parser.add_argument("--resource-dir", help="Windows resource directory passed to xDevice -respath")
    parser.add_argument("--extra", action="append", default=[], help="Raw extra argument for xDevice")
    parser.add_argument("--windows-python", default=DEFAULT_WINDOWS_PYTHON)
    parser.add_argument("--hdc-path", default=DEFAULT_HDC)
    parser.add_argument("--oh-autoctl", type=Path, default=DEFAULT_OH_AUTOCTL)
    parser.add_argument("--base-url")
    parser.add_argument("--device-id")
    parser.add_argument("--command-timeout-sec", type=float, default=900)
    parser.add_argument("--upload-timeout-sec", type=float, default=1200)
    parser.add_argument("--no-install", action="store_true", help="Do not pip install xDevice tarballs")
    parser.add_argument(
        "--stage-module-only",
        action="store_true",
        help="Stage only config/tools/run scripts and testcase files referenced by --module",
    )
    args = parser.parse_args()

    args.out.mkdir(parents=True, exist_ok=True)
    if not args.suite_dir and not args.windows_suite_dir:
        parser.error("one of --suite-dir or --windows-suite-dir is required")

    suite_name = args.suite_name
    if not suite_name:
        suite_name = win_basename(args.windows_suite_dir) if args.windows_suite_dir else args.suite_dir.name
    if args.report_name is None:
        args.report_name = "reports_" + (args.module or suite_name) + "_" + args.run_id

    run_root, suite_dir = suite_windows_paths(args, suite_name)
    manifest = {
        "run_id": args.run_id,
        "suite_name": suite_name,
        "linux_suite_dir": str(args.suite_dir) if args.suite_dir else "",
        "windows_run_root": run_root,
        "windows_suite_dir": suite_dir,
        "sn": args.sn,
        "module": args.module or "",
        "report_name": args.report_name,
        "resource_dir": args.resource_dir or "",
        "windows_python": args.windows_python,
        "hdc_path": args.hdc_path,
    }
    write_json(args.out / "xts_xdevice_manifest.json", manifest)

    admin_shell(
        args,
        f"& {ps_quote(args.windows_python)} --version; & {ps_quote(args.hdc_path)} list targets",
        "probe_python_hdc",
        60,
    )

    if args.suite_dir:
        zip_path = make_zip(args)
        manifest["suite_zip"] = str(zip_path)
        manifest["suite_zip_bytes"] = zip_path.stat().st_size
        manifest["stage_module_only"] = args.stage_module_only
        manifest["staged_testcases"] = getattr(args, "module_staged_testcases", [])
        write_json(args.out / "xts_xdevice_manifest.json", manifest)
        win_zip = run_root + "\\" + zip_path.name
        upload_and_promote(args, zip_path, win_zip)
        extract_script = (
            f"$ErrorActionPreference='Stop'; "
            f"New-Item -ItemType Directory -Force -Path {ps_quote(run_root)} | Out-Null; "
            f"Remove-Item -Recurse -Force -ErrorAction SilentlyContinue {ps_quote(suite_dir)}; "
            f"Expand-Archive -Force -Path {ps_quote(win_zip)} -DestinationPath {ps_quote(run_root)}; "
            f"Get-ChildItem -Path {ps_quote(suite_dir)} | Select-Object -First 20 | Out-String"
        )
        admin_shell(args, extract_script, "stage_extract", args.command_timeout_sec)

    if not args.no_install:
        install_script = (
            f"$ErrorActionPreference='Stop'; Set-Location {ps_quote(suite_dir)}; "
            f"& {ps_quote(args.windows_python)} -m pip install --user "
            ".\\tools\\xdevice-0.0.0.tar.gz "
            ".\\tools\\xdevice_devicetest-0.0.0.tar.gz "
            ".\\tools\\xdevice_ohos-0.0.0.tar.gz"
        )
        admin_shell(args, install_script, "pip_install_xdevice", args.command_timeout_sec)

    run_script = (
        f"$ErrorActionPreference='Continue'; Set-Location {ps_quote(suite_dir)}; "
        f"{build_run_command(args, suite_name, suite_dir)}"
    )
    xdevice_result = admin_shell(args, run_script, "xdevice_run", args.command_timeout_sec)
    summarize_xdevice(args, xdevice_result)

    report_script = (
        f"$report = Join-Path {ps_quote(suite_dir)} 'reports'; "
        f"if (Test-Path $report) {{ Get-ChildItem -Recurse -File $report | "
        "Select-Object FullName,Length,LastWriteTime | ConvertTo-Json -Depth 3 }"
    )
    admin_shell(args, report_script, "report_file_list", 120)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
