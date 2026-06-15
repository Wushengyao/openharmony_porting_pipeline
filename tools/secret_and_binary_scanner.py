#!/usr/bin/env python3
"""Scan changed files for accidental secrets and binary assets."""

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

try:
    import yaml
except Exception:  # pragma: no cover
    yaml = None


SECRET_PATTERNS = [
    ("private_key", re.compile(r"-----BEGIN (RSA |DSA |EC |OPENSSH )?PRIVATE KEY-----")),
    ("aws_access_key", re.compile(r"AKIA[0-9A-Z]{16}")),
    ("generic_token_assignment", re.compile(r"(?i)\b(token|secret|password|passwd|api_key)\b\s*[:=]\s*['\"]?[^'\"\s]{8,}")),
    ("wifi_password_assignment", re.compile(r"(?i)\b(wifi|ssid|psk).*(password|passwd|psk)\b\s*[:=]")),
]

BINARY_SUFFIXES = {
    ".bin",
    ".fw",
    ".img",
    ".ko",
    ".so",
    ".a",
    ".o",
    ".zip",
    ".tar",
    ".gz",
    ".7z",
    ".rar",
    ".apk",
    ".hap",
}


def dump_data(data):
    if yaml is not None:
        return yaml.safe_dump(data, allow_unicode=True, sort_keys=False)
    return json.dumps(data, indent=2, ensure_ascii=False) + "\n"


def changed_paths(repo):
    out = subprocess.check_output(
        ["git", "-C", str(repo), "status", "--porcelain"],
        text=True,
        errors="replace",
    )
    paths = []
    for line in out.splitlines():
        if not line:
            continue
        value = line[3:]
        if " -> " in value:
            value = value.split(" -> ", 1)[1]
        paths.append(Path(repo) / value)
    return paths


def is_binary(path):
    try:
        data = path.read_bytes()[:8192]
    except Exception:
        return False
    return b"\0" in data


def redact(line):
    line = re.sub(r"([:=]\s*)['\"]?[^'\"\s]+", r"\1<redacted>", line)
    if len(line) > 160:
        line = line[:157] + "..."
    return line


def scan_file(path, large_file_bytes):
    findings = []
    if not path.exists() or not path.is_file():
        return findings
    size = path.stat().st_size
    suffix = path.suffix.lower()
    binary = is_binary(path)
    if binary or suffix in BINARY_SUFFIXES:
        findings.append(
            {
                "kind": "binary_asset",
                "severity": "P1",
                "path": str(path),
                "size": size,
                "reason": "binary content or binary-like suffix",
            }
        )
    if size >= large_file_bytes:
        findings.append(
            {
                "kind": "large_file",
                "severity": "P2",
                "path": str(path),
                "size": size,
                "reason": "file exceeds large-file threshold",
            }
        )
    if binary:
        return findings
    try:
        with path.open("r", encoding="utf-8", errors="replace") as f:
            for line_no, line in enumerate(f, 1):
                for pattern_id, pattern in SECRET_PATTERNS:
                    if pattern.search(line):
                        findings.append(
                            {
                                "kind": "secret_pattern",
                                "severity": "P0",
                                "path": str(path),
                                "line": line_no,
                                "pattern": pattern_id,
                                "redacted": redact(line.strip()),
                            }
                        )
    except Exception as exc:
        findings.append(
            {
                "kind": "scan_error",
                "severity": "P3",
                "path": str(path),
                "reason": str(exc),
            }
        )
    return findings


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", help="scan changed and untracked files in repo")
    parser.add_argument("--path", action="append", help="specific path to scan")
    parser.add_argument("--large-file-bytes", type=int, default=5 * 1024 * 1024)
    parser.add_argument("--out")
    parser.add_argument("--fail-on-findings", action="store_true")
    args = parser.parse_args()

    targets = []
    if args.repo:
        targets.extend(changed_paths(args.repo))
    if args.path:
        targets.extend(Path(p) for p in args.path)
    if not targets:
        parser.error("provide --repo or --path")

    findings = []
    for target in sorted(set(Path(os.path.abspath(str(p))) for p in targets)):
        findings.extend(scan_file(target, args.large_file_bytes))

    result = {
        "created_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "target_count": len(targets),
        "finding_count": len(findings),
        "has_blocking_findings": any(f["severity"] in {"P0", "P1"} for f in findings),
        "findings": findings,
    }
    text = dump_data(result)
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)
    if args.fail_on_findings and result["has_blocking_findings"]:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
