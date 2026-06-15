#!/usr/bin/env python3
"""Build a compact evidence pack from OpenHarmony raw artifacts."""

import argparse
import hashlib
import json
import re
import subprocess
from datetime import datetime
from pathlib import Path

try:
    import yaml
except Exception:  # pragma: no cover - fallback for minimal hosts
    yaml = None


ERROR_PATTERNS = [
    re.compile(r"(\berror:|\bFAILED:|ninja: build stopped)", re.I),
    re.compile(r"(Kernel panic|end Kernel panic|not syncing)", re.I),
    re.compile(r"(HDF|hdf).*(failed|fail|error|bind failed|start failed|load failed)", re.I),
    re.compile(r"(undefined reference to|multiple definition of|ld\.lld: error)", re.I),
    re.compile(r"(No such file or directory|No rule to make target|missing and no known rule)", re.I),
]

SUCCESS_PATTERNS = [
    re.compile(r"build\s+success", re.I),
    re.compile(r"=+\s*build\s+successful\s*=+", re.I),
    re.compile(r"\bjob_status\b.*\bsucceeded\b", re.I),
]


def dump_data(data):
    if yaml is not None:
        return yaml.safe_dump(data, allow_unicode=True, sort_keys=False)
    return json.dumps(data, indent=2, ensure_ascii=False) + "\n"


def write_data(path, data):
    path.write_text(dump_data(data), encoding="utf-8")


def sha256_file(path):
    if not path:
        return ""
    p = Path(path)
    if not p.exists() or not p.is_file():
        return ""
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def file_record(path, kind):
    p = Path(path)
    record = {"path": str(p), "kind": kind}
    if p.exists() and p.is_file():
        record["sha256"] = sha256_file(p)
        record["notes"] = "size=%d" % p.stat().st_size
    return record


def git_rev(path):
    if not path:
        return ""
    try:
        out = subprocess.check_output(
            ["git", "-C", str(path), "rev-parse", "HEAD"],
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=10,
        )
        return out.strip()
    except Exception:
        return ""


def collect_error_lines(paths, max_hits):
    hits = []
    for raw in paths:
        if not raw:
            continue
        p = Path(raw)
        if not p.exists() or not p.is_file():
            continue
        with p.open("rb") as f:
            for line_no, raw_line in enumerate(f, 1):
                text = raw_line.decode("utf-8", errors="replace").rstrip()
                if any(pattern.search(text) for pattern in ERROR_PATTERNS):
                    hits.append({"path": str(p), "line": line_no, "text": text[:300]})
                    if len(hits) >= max_hits:
                        return hits
    return hits


def summarize_log(path, kind, max_hits=20):
    if not path:
        return {"kind": kind, "path": "", "status": "not_provided", "top_errors": [], "success_markers": []}
    p = Path(path)
    if not p.exists() or not p.is_file():
        return {"kind": kind, "path": str(p), "status": "missing", "top_errors": [], "success_markers": []}
    top_errors = []
    success_markers = []
    with p.open("rb") as f:
        for line_no, raw_line in enumerate(f, 1):
            text = raw_line.decode("utf-8", errors="replace").rstrip()
            if len(top_errors) < max_hits and any(pattern.search(text) for pattern in ERROR_PATTERNS):
                top_errors.append({"line": line_no, "text": text[:300]})
            if len(success_markers) < max_hits and any(pattern.search(text) for pattern in SUCCESS_PATTERNS):
                success_markers.append({"line": line_no, "text": text[:300]})
    if top_errors:
        status = "failed_or_needs_triage"
    elif success_markers:
        status = "passed_by_success_marker"
    else:
        status = "unknown"
    return {
        "kind": kind,
        "path": str(p),
        "sha256": sha256_file(p),
        "status": status,
        "top_errors": top_errors,
        "success_markers": success_markers,
    }


def write_excerpt(src, dst, max_lines=240):
    if not src:
        dst.write_text("# not provided\n", encoding="utf-8")
        return False
    p = Path(src)
    if not p.exists() or not p.is_file():
        dst.write_text("# missing: %s\n" % src, encoding="utf-8")
        return False

    lines = p.read_bytes().splitlines()
    interesting = []
    matcher = re.compile(
        r"(Kernel panic|watchdog|bootloop|HDF|hdf|fatal|error|failed|Offline|No any connected target)",
        re.I,
    )
    for idx, raw in enumerate(lines):
        text = raw.decode("utf-8", errors="replace")
        if matcher.search(text):
            start = max(0, idx - 5)
            end = min(len(lines), idx + 6)
            interesting.extend(range(start, end))
    if interesting:
        wanted = sorted(set(interesting))[:max_lines]
    else:
        start = max(0, len(lines) - max_lines)
        wanted = list(range(start, len(lines)))

    out = ["# source: %s\n" % p]
    for idx in wanted:
        out.append("%8d: %s\n" % (idx + 1, lines[idx].decode("utf-8", errors="replace")))
    dst.write_text("".join(out), encoding="utf-8", errors="replace")
    return True


def summarize_test_reports(root):
    if not root:
        return {"status": "not_run", "report_root": "", "xml_files": 0}
    p = Path(root)
    if not p.exists():
        return {"status": "missing", "report_root": str(p), "xml_files": 0}
    xml_files = list(p.rglob("*.xml"))
    html_files = list(p.rglob("*.html"))
    log_files = list(p.rglob("*.log"))
    return {
        "status": "collected",
        "report_root": str(p),
        "xml_files": len(xml_files),
        "html_files": len(html_files),
        "log_files": len(log_files),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--job-id", required=True)
    parser.add_argument("--iteration", type=int, default=0)
    parser.add_argument("--board", default="unknown")
    parser.add_argument("--os-version", default="unknown")
    parser.add_argument("--arch", default="unknown")
    parser.add_argument("--source-root")
    parser.add_argument("--source-revision", default="")
    parser.add_argument("--patch-revision", default="")
    parser.add_argument("--image")
    parser.add_argument("--build-log")
    parser.add_argument("--package-log")
    parser.add_argument("--serial-log")
    parser.add_argument("--hdc-log")
    parser.add_argument("--diff-file")
    parser.add_argument("--test-report-root")
    parser.add_argument("--panic-summary")
    parser.add_argument("--recovery-plan")
    parser.add_argument("--device-job-ledger")
    parser.add_argument("--build-command", default="")
    parser.add_argument("--package-command", default="")
    parser.add_argument("--flash-job-id", default="")
    parser.add_argument("--hats-or-xts-run-id", default="")
    parser.add_argument("--raw-artifact-root", default="")
    parser.add_argument("--created-by", default="evidence_pack_builder.py")
    parser.add_argument("--max-error-hits", type=int, default=80)
    args = parser.parse_args()

    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)

    top_hits = collect_error_lines(
        [args.build_log, args.package_log, args.serial_log, args.hdc_log],
        args.max_error_hits,
    )

    log_summaries = [
        summarize_log(args.build_log, "build_log"),
        summarize_log(args.package_log, "package_log"),
    ]
    if any(item["status"] == "failed_or_needs_triage" for item in log_summaries):
        summary_status = "failed_or_partial"
    elif any(item["status"] == "passed_by_success_marker" for item in log_summaries):
        summary_status = "passed_by_success_marker"
    else:
        summary_status = "unknown"
    build_summary = {
        "status": summary_status,
        "build_log": str(args.build_log or ""),
        "package_log": str(args.package_log or ""),
        "build_log_sha256": sha256_file(args.build_log),
        "package_log_sha256": sha256_file(args.package_log),
        "log_summaries": log_summaries,
        "top_error_count": len(top_hits),
        "top_errors": top_hits[:20],
    }
    write_data(out / "build_summary.yaml", build_summary)

    test_summary = summarize_test_reports(args.test_report_root)
    write_data(out / "test_summary.yaml", test_summary)

    device_state = {
        "status": "unknown",
        "serial_log": str(args.serial_log or ""),
        "hdc_log": str(args.hdc_log or ""),
        "serial_excerpt": "serial_excerpt.log",
        "hdc_excerpt": "hdc_excerpt.log",
        "panic_summary": str(args.panic_summary or ""),
        "recovery_plan": str(args.recovery_plan or ""),
        "device_job_ledger": str(args.device_job_ledger or ""),
    }
    write_data(out / "device_state.yaml", device_state)
    write_excerpt(args.serial_log, out / "serial_excerpt.log")
    write_excerpt(args.hdc_log, out / "hdc_excerpt.log")

    if args.diff_file and Path(args.diff_file).exists():
        diff_text = Path(args.diff_file).read_text(encoding="utf-8", errors="replace")
        (out / "diff_summary.md").write_text(
            "# Diff Summary\n\nSource: `%s`\n\n```diff\n%s\n```\n"
            % (args.diff_file, diff_text[:20000]),
            encoding="utf-8",
        )
    else:
        (out / "diff_summary.md").write_text(
            "# Diff Summary\n\nNo diff file provided.\n", encoding="utf-8"
        )

    top_lines = ["# Top Errors", ""]
    if not top_hits:
        top_lines.append("- No signature hits in provided logs.")
    for hit in top_hits[:50]:
        top_lines.append("- `%s:%s` %s" % (hit["path"], hit["line"], hit["text"].replace("`", "'")))
    (out / "top_errors.md").write_text("\n".join(top_lines) + "\n", encoding="utf-8")

    raw_artifacts = []
    for path, kind in [
        (args.image, "image"),
        (args.build_log, "build_log"),
        (args.package_log, "package_log"),
        (args.serial_log, "serial_log"),
        (args.hdc_log, "hdc_log"),
        (args.diff_file, "diff"),
        (args.panic_summary, "panic_summary"),
        (args.recovery_plan, "recovery_plan"),
        (args.device_job_ledger, "device_job_ledger"),
    ]:
        if path:
            raw_artifacts.append(file_record(path, kind))
    links = ["# Raw Artifacts", ""]
    if not raw_artifacts:
        links.append("- No raw artifacts provided.")
    for item in raw_artifacts:
        links.append("- `%s` kind=%s sha256=%s" % (item["path"], item["kind"], item.get("sha256", "")))
    (out / "links_to_raw_artifacts.md").write_text("\n".join(links) + "\n", encoding="utf-8")

    source_revision = args.source_revision or git_rev(args.source_root)
    manifest = {
        "job_id": args.job_id,
        "iteration": args.iteration,
        "board": args.board,
        "os_version": args.os_version,
        "arch": args.arch,
        "image_sha256": sha256_file(args.image),
        "source_revision": source_revision,
        "patch_revision": args.patch_revision,
        "build_command": args.build_command,
        "package_command": args.package_command,
        "flash_job_id": args.flash_job_id,
        "hats_or_xts_run_id": args.hats_or_xts_run_id,
        "raw_artifact_root": args.raw_artifact_root or str(out),
        "created_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "created_by": args.created_by,
        "files": {
            "build_summary": "build_summary.yaml",
            "test_summary": "test_summary.yaml",
            "device_state": "device_state.yaml",
            "diff_summary": "diff_summary.md",
            "top_errors": "top_errors.md",
            "serial_excerpt": "serial_excerpt.log",
            "hdc_excerpt": "hdc_excerpt.log",
            "links_to_raw_artifacts": "links_to_raw_artifacts.md",
        },
        "screenshots": [],
        "raw_artifacts": raw_artifacts,
        "known_debts": [],
    }
    if args.panic_summary:
        manifest["files"]["panic_summary"] = str(args.panic_summary)
    if args.recovery_plan:
        manifest["files"]["recovery_plan"] = str(args.recovery_plan)
    if args.device_job_ledger:
        manifest["files"]["device_job_ledger"] = str(args.device_job_ledger)
    write_data(out / "manifest.yaml", manifest)
    print(str(out / "manifest.yaml"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
