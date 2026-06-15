#!/usr/bin/env python3
"""Maintain a device job ledger for flash, reboot, serial, HDC, and smoke work."""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any

try:
    import yaml
except Exception:  # pragma: no cover
    yaml = None


def now() -> str:
    return datetime.utcnow().isoformat(timespec="seconds") + "Z"


def dump_data(data: Any) -> str:
    if yaml is not None:
        return yaml.safe_dump(data, allow_unicode=True, sort_keys=False)
    return json.dumps(data, indent=2, ensure_ascii=False) + "\n"


def load_data(path: Path) -> Any:
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() in {".yaml", ".yml"} and yaml is not None:
        return yaml.safe_load(text)
    return json.loads(text)


def write_data(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dump_data(data), encoding="utf-8")


def command_init(args: argparse.Namespace) -> int:
    ledger = {
        "ledger_id": args.ledger_id,
        "device_id": args.device_id,
        "profile": args.profile,
        "created_at": now(),
        "updated_at": now(),
        "jobs": [],
    }
    write_data(args.out, ledger)
    print(args.out)
    return 0


def command_append(args: argparse.Namespace) -> int:
    ledger = load_data(args.ledger)
    job = {
        "job_id": args.job_id,
        "operation": args.operation,
        "status": args.status,
        "command": args.command,
        "started_at": args.started_at,
        "ended_at": args.ended_at,
        "image_sha256": args.image_sha256,
        "artifacts": args.artifact or [],
        "evidence_refs": args.evidence_ref or [],
        "notes": args.notes,
    }
    ledger.setdefault("jobs", []).append(job)
    ledger["updated_at"] = now()
    write_data(args.ledger, ledger)
    print(args.ledger)
    return 0


def command_summarize(args: argparse.Namespace) -> int:
    ledger = load_data(args.ledger)
    jobs = ledger.get("jobs", [])
    by_status: dict[str, int] = {}
    for job in jobs:
        status = str(job.get("status", "unknown"))
        by_status[status] = by_status.get(status, 0) + 1
    summary = {
        "ledger": str(args.ledger),
        "device_id": ledger.get("device_id", ""),
        "profile": ledger.get("profile", ""),
        "job_count": len(jobs),
        "by_status": by_status,
        "last_job": jobs[-1] if jobs else None,
    }
    write_data(args.out, summary)
    print(args.out)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    init = sub.add_parser("init")
    init.add_argument("--out", type=Path, required=True)
    init.add_argument("--ledger-id", default="device-job-ledger")
    init.add_argument("--device-id", default="default")
    init.add_argument("--profile", default="")
    init.set_defaults(func=command_init)

    append = sub.add_parser("append")
    append.add_argument("--ledger", type=Path, required=True)
    append.add_argument("--job-id", required=True)
    append.add_argument("--operation", required=True)
    append.add_argument("--status", required=True)
    append.add_argument("--command", required=True)
    append.add_argument("--started-at", default="")
    append.add_argument("--ended-at", default="")
    append.add_argument("--image-sha256", default="")
    append.add_argument("--artifact", action="append")
    append.add_argument("--evidence-ref", action="append")
    append.add_argument("--notes", default="")
    append.set_defaults(func=command_append)

    summarize = sub.add_parser("summarize")
    summarize.add_argument("--ledger", type=Path, required=True)
    summarize.add_argument("--out", type=Path, required=True)
    summarize.set_defaults(func=command_summarize)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
