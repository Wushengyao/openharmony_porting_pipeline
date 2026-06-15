#!/usr/bin/env python3
"""Shared helpers for modular xDevice runner scripts."""

from __future__ import annotations

import json
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

try:
    import yaml
except Exception:  # pragma: no cover
    yaml = None


COUNT_KEYS = [
    "modules",
    "run_modules",
    "total",
    "passed",
    "failed",
    "error",
    "timeout",
    "blocked",
    "ignored",
    "skipped",
    "unavailable",
]

FAILURE_STATUSES = {"failed", "error", "timeout"}
BLOCKED_STATUSES = {"blocked", "disable", "disabled"}


def dump_data(data: Any) -> str:
    if yaml is not None:
        return yaml.safe_dump(data, allow_unicode=True, sort_keys=False)
    return json.dumps(data, indent=2, ensure_ascii=False) + "\n"


def write_data(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dump_data(data), encoding="utf-8")


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def load_data(path: Path) -> Any:
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() in {".yaml", ".yml"} and yaml is not None:
        return yaml.safe_load(text)
    return json.loads(text)


def run_command(argv: list[str], timeout: int | None = None) -> dict[str, Any]:
    proc = subprocess.run(argv, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout)
    return {
        "argv": argv,
        "returncode": proc.returncode,
        "stdout": proc.stdout,
        "stderr": proc.stderr,
    }


def parse_summary_line(text: str) -> dict[str, Any]:
    summary: dict[str, Any] = {"summary_found": False, "raw_summary_line": ""}
    for key in COUNT_KEYS:
        summary[key] = None
    for line in text.splitlines():
        if "Test Summary:" not in line:
            continue
        summary["summary_found"] = True
        summary["raw_summary_line"] = line
        for key in ["modules", "run modules", "total", "passed", "failed", "blocked", "ignored", "unavailable"]:
            match = re.search(rf"{re.escape(key)}:\s*(\d+)", line)
            if match:
                summary[key.replace(" ", "_")] = int(match.group(1))
    return summary


def normalize_status(value: str | None) -> str:
    if not value:
        return "unknown"
    normalized = value.strip().lower()
    aliases = {
        "pass": "passed",
        "passed": "passed",
        "success": "passed",
        "ok": "passed",
        "fail": "failed",
        "failed": "failed",
        "failure": "failed",
        "error": "error",
        "timeout": "timeout",
        "blocked": "blocked",
        "block": "blocked",
        "disable": "blocked",
        "disabled": "blocked",
        "skip": "skipped",
        "skipped": "skipped",
        "ignored": "ignored",
        "ignore": "ignored",
        "unavailable": "unavailable",
    }
    return aliases.get(normalized, normalized)


def normalize_case_status(attrs: dict[str, str], child_tags: set[str]) -> str:
    status = normalize_status(
        attrs.get("status")
        or attrs.get("verdict")
        or attrs.get("outcome")
    )
    message = (attrs.get("message") or attrs.get("msg") or "").strip().lower()
    if status in BLOCKED_STATUSES or "mark blocked" in message:
        return "blocked"
    if status in {"skipped", "ignored", "unavailable"}:
        return status

    result = attrs.get("result")
    if result is not None:
        normalized_result = result.strip().lower()
        if normalized_result in {"true", "pass", "passed", "success", "ok"}:
            return "passed"
        if normalized_result in {"false", "fail", "failed", "failure"}:
            return "failed"

    if status == "run":
        status = "unknown"
    if status == "unknown":
        if "failure" in child_tags:
            return "failed"
        if "error" in child_tags:
            return "error"
        if "skipped" in child_tags:
            return "skipped"
        return "passed"
    return status


def xml_attr_int(attrs: dict[str, str], *names: str) -> int:
    for name in names:
        if name in attrs:
            try:
                return int(attrs[name])
            except ValueError:
                continue
    return 0


def parse_xml_report(path: Path) -> dict[str, Any]:
    result: dict[str, Any] = {
        "path": str(path),
        "parsed": False,
        "counts": {key: 0 for key in COUNT_KEYS},
        "cases": [],
        "errors": [],
    }
    try:
        tree = ET.parse(path)
    except ET.ParseError as exc:
        result["errors"].append(str(exc))
        return result
    root = tree.getroot()
    result["parsed"] = True
    attrs = dict(root.attrib)
    counts = result["counts"]
    counts["total"] += xml_attr_int(attrs, "total", "tests", "testcases")
    counts["passed"] += xml_attr_int(attrs, "passed", "pass")
    counts["failed"] += xml_attr_int(attrs, "failed", "fail", "failures")
    counts["error"] += xml_attr_int(attrs, "error", "errors")
    counts["timeout"] += xml_attr_int(attrs, "timeout", "timeouts")
    counts["blocked"] += xml_attr_int(attrs, "blocked", "block", "disabled", "disable")
    counts["skipped"] += xml_attr_int(attrs, "skipped", "skip")
    counts["ignored"] += xml_attr_int(attrs, "ignored", "ignore")
    counts["unavailable"] += xml_attr_int(attrs, "unavailable")

    for elem in root.iter():
        tag = elem.tag.rsplit("}", 1)[-1].lower()
        if tag not in {"testcase", "case", "test"}:
            continue
        attrs = dict(elem.attrib)
        name = attrs.get("name") or attrs.get("test") or attrs.get("classname") or ""
        classname = attrs.get("classname") or ""
        child_tags = {child.tag.rsplit("}", 1)[-1].lower() for child in elem}
        status = normalize_case_status(attrs, child_tags)
        result["cases"].append({"name": name, "classname": classname, "status": status})

    if result["cases"]:
        case_counts = {key: 0 for key in COUNT_KEYS}
        case_counts["total"] = len(result["cases"])
        for case in result["cases"]:
            status = case["status"]
            if status in case_counts:
                case_counts[status] += 1
            elif status == "passed":
                case_counts["passed"] += 1
            else:
                case_counts["failed"] += 1
        if any(counts.values()):
            for key in counts:
                counts[key] = max(counts[key], case_counts[key])
        else:
            counts.update(case_counts)
    return result


def merge_counts(items: list[dict[str, int]]) -> dict[str, int]:
    merged = {key: 0 for key in COUNT_KEYS}
    for item in items:
        for key in merged:
            value = item.get(key)
            if isinstance(value, int):
                merged[key] += value
    return merged


def derive_status(counts: dict[str, int]) -> str:
    if counts.get("failed", 0) or counts.get("error", 0) or counts.get("timeout", 0):
        return "failed"
    if counts.get("blocked", 0) or counts.get("unavailable", 0):
        return "blocked_or_unavailable"
    if counts.get("total", 0) and counts.get("passed", 0) >= counts.get("total", 0):
        return "passed"
    # xDevice may report the same gtest skip both as suite-level ignored and
    # testcase-level skipped. Treat them as one non-failure bucket for status.
    non_failure_total = counts.get("passed", 0) + max(counts.get("ignored", 0), counts.get("skipped", 0))
    if counts.get("total", 0) and non_failure_total >= counts.get("total", 0):
        return "passed"
    if counts.get("passed", 0):
        return "partial"
    return "unknown"


def ensure_script_dir_on_path() -> None:
    script_dir = Path(__file__).resolve().parent
    if str(script_dir) not in sys.path:
        sys.path.insert(0, str(script_dir))
