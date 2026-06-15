#!/usr/bin/env python3
"""Rig-controller abstraction for power, USB, serial, and reconnect actions."""

from __future__ import annotations

import argparse
import json
import subprocess
import time
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


def load_config(path: Path | None) -> dict[str, Any]:
    if not path:
        return {}
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() in {".yaml", ".yml"} and yaml is not None:
        return yaml.safe_load(text) or {}
    return json.loads(text)


def write_result(args: argparse.Namespace, payload: dict[str, Any]) -> None:
    text = dump_data(payload)
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(text, encoding="utf-8")
    else:
        print(text, end="")


def dry_run(action: str, _config: dict[str, Any], args: argparse.Namespace) -> dict[str, Any]:
    return {"ok": True, "dry_run": True, "action": action, "duration_sec": args.duration_sec}


def command_backend(action: str, config: dict[str, Any], _args: argparse.Namespace) -> dict[str, Any]:
    commands = config.get("commands", {})
    command = commands.get(action)
    if not command:
        return {"ok": False, "error": f"no command configured for {action}"}
    proc = subprocess.run(command, shell=True, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return {"ok": proc.returncode == 0, "returncode": proc.returncode, "stdout": proc.stdout, "stderr": proc.stderr}


def serial_dtr_rts_backend(action: str, config: dict[str, Any], args: argparse.Namespace) -> dict[str, Any]:
    try:
        import serial  # type: ignore[import-not-found]
    except Exception as exc:
        return {"ok": False, "error": f"pyserial unavailable: {exc}"}
    port = config.get("port") or args.port
    baudrate = int(config.get("baudrate") or args.baudrate)
    if not port:
        return {"ok": False, "error": "serial port is required for serial-dtr-rts backend"}
    with serial.Serial(port=port, baudrate=baudrate, timeout=1) as ser:
        if action in {"serial-reopen", "usb-replug"}:
            ser.close()
            time.sleep(args.duration_sec)
            ser.open()
            return {"ok": True, "port": port, "action": action}
        if action in {"short-press-power", "long-press-power", "power-off", "power-on"}:
            ser.setDTR(False)
            ser.setRTS(False)
            time.sleep(args.duration_sec)
            ser.setDTR(True)
            ser.setRTS(True)
            return {"ok": True, "port": port, "action": action}
    return {"ok": False, "error": f"unsupported action for serial-dtr-rts: {action}"}


def run_action(action: str, args: argparse.Namespace) -> dict[str, Any]:
    config = load_config(args.config)
    if args.backend == "dry-run":
        result = dry_run(action, config, args)
    elif args.backend == "command":
        result = command_backend(action, config, args)
    elif args.backend == "serial-dtr-rts":
        result = serial_dtr_rts_backend(action, config, args)
    else:
        result = {"ok": False, "error": f"unknown backend: {args.backend}"}
    return {
        "created_at": now(),
        "backend": args.backend,
        "action": action,
        "config": str(args.config or ""),
        "result": result,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=[
        "status",
        "power-off",
        "power-on",
        "short-press-power",
        "long-press-power",
        "usb-replug",
        "serial-reopen",
        "hdc-reconnect",
    ])
    parser.add_argument("--backend", default="dry-run", choices=["dry-run", "command", "serial-dtr-rts"])
    parser.add_argument("--config", type=Path)
    parser.add_argument("--out")
    parser.add_argument("--duration-sec", type=float, default=2.0)
    parser.add_argument("--port", default="")
    parser.add_argument("--baudrate", default=115200)
    args = parser.parse_args()

    payload = run_action(args.action, args)
    write_result(args, payload)
    return 0 if payload["result"].get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
