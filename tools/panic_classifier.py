#!/usr/bin/env python3
"""Classify serial/HDC logs for panic, watchdog, bootloop, and recovery states."""

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


PATTERNS = [
    ("kernel_panic", "P0", re.compile(r"(Kernel panic|end Kernel panic|not syncing|sysrq triggered crash)", re.I)),
    ("watchdog_or_lockup", "P0", re.compile(r"(watchdog|hard LOCKUP|soft lockup|RCU stall|hung task)", re.I)),
    ("bootloop_or_reboot", "P0", re.compile(r"(Restarting system|reboot: Restarting|init:.*reboot)", re.I)),
    ("hdc_offline", "P1", re.compile(r"(No any connected target|ExecuteCommand need connect-key|Offline)", re.I)),
    ("hdf_failure", "P1", re.compile(r"(HDF|hdf).*(failed|fail|error|bind failed|start failed|load failed)", re.I)),
    ("permission_denial", "P1", re.compile(r"(avc: denied|Permission denied|SELinux)", re.I)),
    ("ui_or_app_crash", "P2", re.compile(r"(FATAL EXCEPTION|Ability.*crash|appspawn.*failed|process.*died)", re.I)),
]


def dump_data(data):
    if yaml is not None:
        return yaml.safe_dump(data, allow_unicode=True, sort_keys=False)
    return json.dumps(data, indent=2, ensure_ascii=False) + "\n"


def classify(path, max_hits):
    hits = []
    p = Path(path)
    with p.open("rb") as f:
        for line_no, raw in enumerate(f, 1):
            text = raw.decode("utf-8", errors="replace").rstrip()
            for pattern_id, severity, regex in PATTERNS:
                if regex.search(text):
                    hits.append(
                        {
                            "id": pattern_id,
                            "severity": severity,
                            "line": line_no,
                            "text": text[:300],
                        }
                    )
                    break
            if len(hits) >= max_hits:
                break
    severity_order = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}
    top = min((hit["severity"] for hit in hits), key=lambda x: severity_order[x]) if hits else "P3"
    classes = sorted({hit["id"] for hit in hits})
    return {
        "created_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "log": str(p),
        "highest_severity": top,
        "classification": classes[0] if len(classes) == 1 else ("multiple" if classes else "no_match"),
        "hit_count": len(hits),
        "hits": hits,
        "recovery_recommendation": recovery_recommendation(classes),
    }


def recovery_recommendation(classes):
    class_set = set(classes)
    if {"kernel_panic", "watchdog_or_lockup", "bootloop_or_reboot"} & class_set:
        return "stop unattended flashing loop; preserve serial excerpt and require recovery plan"
    if "hdc_offline" in class_set:
        return "query device job and wait/reconnect before resubmitting any operation"
    if "hdf_failure" in class_set:
        return "route to runtime-hdf-reviewer with HDF/init evidence"
    return "no automatic recovery recommendation"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--log", required=True)
    parser.add_argument("--out")
    parser.add_argument("--max-hits", type=int, default=80)
    args = parser.parse_args()
    result = classify(args.log, args.max_hits)
    text = dump_data(result)
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
