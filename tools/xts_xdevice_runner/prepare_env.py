#!/usr/bin/env python3
"""Check xDevice suite, oh-auto, Python, and HDC prerequisites."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
from common import run_command, write_json  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    default_sn = os.getenv("OH_XDEVICE_SN") or os.getenv("OH_AUTO_HDC_TARGET") or os.getenv("OH_AUTO_CONNECT_TARGET") or ""
    parser.add_argument("--suite-dir", type=Path)
    parser.add_argument("--windows-suite-dir")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--sn", default=default_sn)
    parser.add_argument("--oh-autoctl", type=Path, default=SCRIPT_DIR.parent / "oh_autoctl.py")
    parser.add_argument("--base-url")
    parser.add_argument("--device-id")
    parser.add_argument("--strict", action="store_true")
    args = parser.parse_args()

    checks: list[dict[str, object]] = []

    def add(name: str, ok: bool, detail: object) -> None:
        checks.append({"name": name, "ok": ok, "detail": detail})

    add("python", True, {"executable": sys.executable, "version": sys.version.split()[0]})

    if args.suite_dir:
        suite = args.suite_dir
        add("suite_dir_exists", suite.is_dir(), str(suite))
        for rel in ["config/user_config.xml", "testcases", "tools"]:
            target = suite / rel
            add(f"suite_has_{rel}", target.exists(), str(target))
    else:
        add("windows_suite_dir_provided", bool(args.windows_suite_dir), args.windows_suite_dir or "")

    if args.oh_autoctl.exists():
        cmd_base = [sys.executable, str(args.oh_autoctl)]
        if args.base_url:
            cmd_base.extend(["--base-url", args.base_url])
        if args.device_id:
            cmd_base.extend(["--device-id", args.device_id])
        for command in ["capabilities", "status"]:
            proc = run_command(cmd_base + [command], timeout=30)
            add(f"oh_auto_{command}", proc["returncode"] == 0, proc)
    else:
        add("oh_autoctl_exists", False, str(args.oh_autoctl))

    result = {
        "status": "passed" if all(item["ok"] for item in checks) else "failed_or_partial",
        "sn": args.sn,
        "base_url": args.base_url or os.environ.get("OH_AUTO_BASE_URL", ""),
        "device_id": args.device_id or os.environ.get("OH_AUTO_DEVICE_ID", ""),
        "checks": checks,
    }
    write_json(args.out, result)
    print(args.out)
    if args.strict and result["status"] != "passed":
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
