#!/usr/bin/env python3
"""Run small replay evals for log-signature coverage."""

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path

try:
    import yaml
except Exception:  # pragma: no cover
    yaml = None

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import log_slice  # noqa: E402


def load_yaml(path):
    if yaml is None:
        raise RuntimeError("PyYAML is required for replay_eval/run_eval.py")
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8", errors="replace")) or {}
    return data if isinstance(data, dict) else {}


def dump_data(data):
    if yaml is not None:
        return yaml.safe_dump(data, allow_unicode=True, sort_keys=False)
    return json.dumps(data, indent=2, ensure_ascii=False) + "\n"


def find_signatures(case_dir, case):
    taxonomy = case.get("taxonomy")
    taxonomy_path = (case_dir / taxonomy).resolve() if taxonomy else None
    signatures = log_slice.compile_signatures(str(taxonomy_path) if taxonomy_path else None)
    found = set()
    evidence = []
    for raw_log in case.get("logs", []):
        path = Path(raw_log)
        if not path.is_absolute():
            path = (case_dir / raw_log).resolve()
        if not path.exists():
            evidence.append({"log": str(path), "missing": True})
            continue
        for line_no, raw_line in enumerate(path.open("rb"), 1):
            text = raw_line.decode("utf-8", errors="replace")
            for sig, regex in signatures:
                if regex.search(text):
                    found.add(sig["id"])
                    evidence.append(
                        {
                            "log": str(path),
                            "line": line_no,
                            "signature_id": sig["id"],
                            "text": text.strip()[:240],
                        }
                    )
    return sorted(found), evidence


def run_cases(cases_root):
    root = Path(cases_root)
    results = []
    for case_file in sorted(root.glob("*/case.yaml")):
        case_dir = case_file.parent
        case = load_yaml(case_file)
        expected = set(case.get("expected_signatures", []))
        found, evidence = find_signatures(case_dir, case)
        found_set = set(found)
        missing = sorted(expected - found_set)
        unexpected = sorted(found_set - expected)
        results.append(
            {
                "case_id": case.get("case_id", case_dir.name),
                "case_file": str(case_file),
                "passed": not missing,
                "expected_signatures": sorted(expected),
                "found_signatures": found,
                "missing_signatures": missing,
                "unexpected_signatures": unexpected,
                "evidence": evidence[:50],
            }
        )
    return {
        "created_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "cases_root": str(root),
        "case_count": len(results),
        "passed_count": sum(1 for item in results if item["passed"]),
        "failed_count": sum(1 for item in results if not item["passed"]),
        "results": results,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases-root", required=True)
    parser.add_argument("--out")
    args = parser.parse_args()
    result = run_cases(args.cases_root)
    text = dump_data(result)
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)
    return 1 if result["failed_count"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
