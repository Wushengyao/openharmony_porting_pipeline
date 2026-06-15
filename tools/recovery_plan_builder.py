#!/usr/bin/env python3
"""Build a structured recovery plan from panic classification and device state."""

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


def action(order: int, name: str, allowed: bool, notes: str, backend: str = "", command: str = "") -> dict[str, Any]:
    return {
        "order": order,
        "action": name,
        "backend": backend,
        "command": command,
        "allowed_unattended": allowed,
        "notes": notes,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--panic-summary", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--plan-id", default="")
    parser.add_argument("--allow-physical", action="store_true")
    parser.add_argument("--preferred-rig-backend", default="dry-run")
    parser.add_argument("--evidence-ref", action="append", default=[])
    args = parser.parse_args()

    summary = load_data(args.panic_summary)
    classes = set(summary.get("classification", "").split(",")) if isinstance(summary.get("classification"), str) else set()
    for hit in summary.get("hits", []):
        if isinstance(hit, dict) and hit.get("id"):
            classes.add(str(hit["id"]))
    classification = summary.get("classification", "unknown")
    severity = summary.get("highest_severity", "unknown")
    actions = [
        action(1, "preserve_logs", True, "Copy serial/HDC excerpts and panic summary into the active evidence pack."),
        action(2, "query_device_jobs", True, "Run oh_autoctl.py status and diagnose-jobs before resubmitting flash or reboot."),
    ]
    blocked = []

    if classes & {"kernel_panic", "watchdog_or_lockup", "bootloop_or_reboot"}:
        actions.append(
            action(
                3,
                "try_reboot_fastboot_via_hdc_or_serial",
                True,
                "Use HDC or serial reboot fastboot only if a channel is responsive.",
                command="oh_autoctl.py shell 'reboot fastboot' or oh_autoctl.py serial 'reboot fastboot'",
            )
        )
        actions.append(
            action(
                4,
                "physical_recovery",
                args.allow_physical,
                "Use rig-controller only when hardware backend is configured and this action is explicitly allowed.",
                backend=args.preferred_rig_backend,
                command=f"rig_controller.py long-press-power --backend {args.preferred_rig_backend}",
            )
        )
        if not args.allow_physical:
            blocked.append("physical recovery is not allowed for this plan")
    elif "hdc_offline" in classes:
        actions.append(
            action(3, "wait_connected", True, "Run bounded wait-connected before declaring the board lost.")
        )
    elif "hdf_failure" in classes:
        actions.append(
            action(3, "runtime_hdf_review", True, "Route logs to runtime-hdf-reviewer; do not power-cycle to hide service errors.")
        )
    else:
        actions.append(action(3, "no_recovery_action", True, "No severe recovery signature was detected."))

    plan = {
        "plan_id": args.plan_id or "recovery-" + datetime.utcnow().strftime("%Y%m%d%H%M%S"),
        "created_at": now(),
        "trigger": str(summary.get("log", "")),
        "classification": classification,
        "highest_severity": severity,
        "evidence_refs": args.evidence_ref or [str(args.panic_summary)],
        "actions": actions,
        "blocked_conditions": blocked,
    }
    write_data(args.out, plan)
    print(args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
