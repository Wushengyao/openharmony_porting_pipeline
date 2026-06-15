#!/usr/bin/env python3
"""Scan diffs for high-risk OpenHarmony porting changes."""

import argparse
import fnmatch
import json
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

try:
    import yaml
except Exception:  # pragma: no cover
    yaml = None


DEFAULT_PATTERNS = [
    "kernel/**",
    "drivers/hdf_core/**",
    "base/startup/init/**",
    "base/security/**",
    "device/**/boot/**",
    "device/**/firmware/**",
    "vendor/**/hdf_config/**",
    "vendor/**/etc/init/**",
    "vendor/**/*.bin",
    "vendor/**/*.fw",
    "vendor/**/*.img",
    "vendor/**/*.ko",
    "vendor/**/*.so",
]

DEFAULT_MARKERS = [
    "deleted file mode",
    "Binary files",
    "GIT binary patch",
    "reboot fastboot",
    "setenforce",
    "chmod 777",
]


def load_yaml(path):
    if not path or not Path(path).exists() or yaml is None:
        return {}
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8", errors="replace")) or {}
    return data if isinstance(data, dict) else {}


def dump_data(data):
    if yaml is not None:
        return yaml.safe_dump(data, allow_unicode=True, sort_keys=False)
    return json.dumps(data, indent=2, ensure_ascii=False) + "\n"


def run_git_diff(repo, cached):
    cmd = ["git", "-C", str(repo), "diff", "--binary", "--no-ext-diff"]
    if cached:
        cmd.insert(4, "--cached")
    return subprocess.check_output(cmd, text=True, errors="replace")


def extract_paths(diff_text):
    paths = set()
    for line in diff_text.splitlines():
        if line.startswith("diff --git "):
            parts = line.split()
            for token in parts[2:4]:
                if token.startswith("a/") or token.startswith("b/"):
                    paths.add(token[2:])
        elif line.startswith("+++ b/") or line.startswith("--- a/"):
            paths.add(line[6:])
        elif re.match(r"^[AMDRC]\d*\t", line):
            parts = line.split("\t")
            if len(parts) >= 2:
                paths.add(parts[-1])
    return sorted(p for p in paths if p and p != "/dev/null")


def path_matches(path, pattern):
    return fnmatch.fnmatch(path, pattern) or fnmatch.fnmatch("/" + path, pattern)


def scan(diff_text, policy, approval):
    patterns = policy.get("high_risk_path_patterns") or DEFAULT_PATTERNS
    markers = policy.get("high_risk_diff_markers") or DEFAULT_MARKERS
    paths = extract_paths(diff_text)
    items = []

    for path in paths:
        for pattern in patterns:
            if path_matches(path, pattern):
                items.append(
                    {
                        "kind": "path",
                        "severity": "P1",
                        "path": path,
                        "pattern": pattern,
                        "reason": "matches high-risk path pattern",
                    }
                )
                break

    lower_diff = diff_text.lower()
    for marker in markers:
        if marker.lower() in lower_diff:
            items.append(
                {
                    "kind": "marker",
                    "severity": "P1",
                    "marker": marker,
                    "reason": "matches high-risk diff marker",
                }
            )

    has_approval = bool(approval and Path(approval).exists())
    high_risk = bool(items)
    return {
        "created_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "risk_level": "P1" if high_risk else "P3",
        "high_risk": high_risk,
        "requires_main_agent_approval": high_risk,
        "approval_record": str(approval or ""),
        "approval_record_present": has_approval,
        "allowed_for_build_flash": (not high_risk) or has_approval,
        "changed_paths": paths,
        "items": items,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--diff-file")
    source.add_argument("--repo")
    parser.add_argument("--cached", action="store_true", help="scan git staged diff")
    parser.add_argument("--policy", default="policies/risk_policy.yaml")
    parser.add_argument("--approval")
    parser.add_argument("--out")
    parser.add_argument("--fail-on-risk", action="store_true")
    args = parser.parse_args()

    if args.diff_file:
        diff_text = Path(args.diff_file).read_text(encoding="utf-8", errors="replace")
    else:
        diff_text = run_git_diff(args.repo, args.cached)
    policy = load_yaml(args.policy)
    result = scan(diff_text, policy, args.approval)
    text = dump_data(result)
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)
    if args.fail_on_risk and result["high_risk"] and not result["approval_record_present"]:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
