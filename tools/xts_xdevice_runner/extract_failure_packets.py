#!/usr/bin/env python3
"""Extract compact failure packets from xDevice probe or queue outputs."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any


FAIL_KEYS = ["failed", "error", "timeout", "blocked", "unavailable"]


def safe_name(value: str, limit: int = 96) -> str:
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", value).strip("_")
    return safe[:limit] or "module"


def read_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def counts_from_summary(summary: dict[str, Any]) -> dict[str, int]:
    runner_summary = summary.get("runner_summary") or {}
    if isinstance(runner_summary, dict) and runner_summary.get("summary_found"):
        return {key: runner_summary.get(key, 0) or 0 for key in ["total", "passed", *FAIL_KEYS, "ignored", "skipped"]}
    xml_counts = ((summary.get("xml_summary") or {}).get("counts") or {})
    if isinstance(xml_counts, dict):
        return {key: xml_counts.get(key, 0) or 0 for key in ["total", "passed", *FAIL_KEYS, "ignored", "skipped"]}
    return {key: 0 for key in ["total", "passed", *FAIL_KEYS, "ignored", "skipped"]}


def has_failure(summary: dict[str, Any]) -> bool:
    if summary.get("status") not in {None, "", "passed"}:
        return True
    counts = counts_from_summary(summary)
    return any(counts.get(key, 0) for key in FAIL_KEYS)


def module_from_summary(summary: dict[str, Any], summary_path: Path) -> str:
    module = summary.get("module")
    if isinstance(module, str) and module:
        return module
    parent = summary_path.parent.parent.name
    match = re.match(r"module_\d+_(.+)", parent)
    return match.group(1) if match else parent


def failure_cases(summary: dict[str, Any], limit: int) -> list[dict[str, Any]]:
    xml_summary = summary.get("xml_summary") or {}
    failures = xml_summary.get("failures") if isinstance(xml_summary, dict) else None
    if isinstance(failures, list):
        return failures[:limit]
    return []


def find_related_logs(run_dir: Path) -> list[str]:
    candidates = []
    for rel in [
        "reports/reports/log",
        "reports/reports/task_log.log",
        "reports/reports/summary.ini",
        "runner/xdevice_run.json",
        "runner/xdevice_summary.json",
    ]:
        path = run_dir / rel
        if path.exists():
            candidates.append(str(path))
    return candidates


def build_packet(summary_path: Path, case_limit: int) -> dict[str, Any]:
    run_dir = summary_path.parent.parent
    summary = read_json(summary_path)
    module = module_from_summary(summary, summary_path)
    return {
        "module": module,
        "status": summary.get("status", "unknown"),
        "run_dir": str(run_dir),
        "summary_path": str(summary_path),
        "counts": counts_from_summary(summary),
        "failures": failure_cases(summary, case_limit),
        "related_logs": find_related_logs(run_dir),
    }


def write_packet_md(path: Path, packet: dict[str, Any]) -> None:
    lines = [
        f"# xDevice Failure Packet: {packet['module']}",
        "",
        f"- status: {packet['status']}",
        f"- run_dir: {packet['run_dir']}",
        f"- summary: {packet['summary_path']}",
        f"- counts: {packet['counts']}",
        "",
        "## Related Logs",
    ]
    for item in packet["related_logs"]:
        lines.append(f"- {item}")
    lines.extend(["", "## Failure Cases"])
    if packet["failures"]:
        for item in packet["failures"]:
            lines.append(f"- {item.get('classname', '')}#{item.get('name', '')}: {item.get('status')}")
    else:
        lines.append("- No per-case failure list was available; inspect XML and module logs.")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path)
    parser.add_argument("--case-limit", type=int, default=50)
    args = parser.parse_args()

    out_dir = args.out_dir or (args.run_root / "triage_packets")
    out_dir.mkdir(parents=True, exist_ok=True)
    summaries = sorted(args.run_root.rglob("summary/test_summary.json"))
    packets = []
    passed = 0
    for summary_path in summaries:
        summary = read_json(summary_path)
        if has_failure(summary):
            packet = build_packet(summary_path, args.case_limit)
            packets.append(packet)
            stem = safe_name(packet["module"])
            write_json(out_dir / f"{stem}.json", packet)
            write_packet_md(out_dir / f"{stem}.md", packet)
        else:
            passed += 1

    aggregate = {
        "run_root": str(args.run_root),
        "summary_count": len(summaries),
        "passed_summary_count": passed,
        "failure_packet_count": len(packets),
        "packets": packets,
    }
    write_json(out_dir / "failure_packets.json", aggregate)
    lines = [
        "# xDevice Failure Packet Index",
        "",
        f"- run_root: {args.run_root}",
        f"- summary_count: {len(summaries)}",
        f"- passed_summary_count: {passed}",
        f"- failure_packet_count: {len(packets)}",
        "",
        "## Packets",
    ]
    if packets:
        for packet in packets:
            lines.append(f"- {packet['status']}: {packet['module']} counts={packet['counts']} run={packet['run_dir']}")
    else:
        lines.append("- No failure packets generated.")
    (out_dir / "failure_packets.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(out_dir / "failure_packets.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
