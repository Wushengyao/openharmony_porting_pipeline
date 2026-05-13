#!/usr/bin/env python3
"""Final audit for OpenHarmony porting pipeline outputs.

This auditor checks both structural consistency and common semantic failure modes
observed in T113/RuyiOS test runs: template cases, force-sync/.gitattributes
cases, ARM/RISC-V scope contradiction, tiny support files, and title/evidence
mismatches.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
from pathlib import Path
from typing import Any


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def count_jsonl(path: Path) -> int:
    if not path.exists():
        return 0
    return sum(1 for line in path.read_text(encoding="utf-8", errors="ignore").splitlines() if line.strip())


def count_csv(path: Path) -> int:
    if not path.exists() or path.stat().st_size == 0:
        return 0
    with path.open(encoding="utf-8", errors="ignore", newline="") as f:
        return max(0, sum(1 for _ in csv.reader(f)) - 1)


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows = []
    if not path.exists():
        return rows
    with path.open(encoding="utf-8", errors="ignore") as f:
        for line in f:
            if not line.strip():
                continue
            try:
                rows.append(json.loads(line))
            except Exception:
                continue
    return rows


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="ignore") if path.exists() else ""


def extract_case_evidence(text: str) -> tuple[list[str], list[str], list[str]]:
    commits = re.findall(r"commit_hash:\s*([^\n\r]+)", text)
    files = re.findall(r"file_path:\s*([^\n\r]+)", text)
    bins = re.findall(r"sha256:\s*([^\n\r]+)", text)
    return [x.strip() for x in commits], [x.strip() for x in files], [x.strip() for x in bins]


def all_gitattributes(paths: list[str]) -> bool:
    vals = [p for p in paths if p]
    return bool(vals) and all(Path(p).name == ".gitattributes" for p in vals)


def evidence_matches_theme(case_name: str, text: str, evidence_files: list[str]) -> tuple[bool, str]:
    lower_name = case_name.lower()
    combined = " ".join([text, *evidence_files]).lower()
    checks = [
        (["hdf", "audio"], ["hdf", "audio", "codec", "dai", "dma", "hcs", "hcb", "speaker"]),
        (["wifi", "wpa"], ["wifi", "wpa", "supplicant", "libnl", "dhcpcd", "bk7236", "wireless"]),
        (["boot", "firmware", "spl"], ["boot", "brandy", "u-boot", "uboot", "spl", "arisc", "dsp", "fex", ".bin", ".dts", ".dtsi"]),
        (["product", "board", "soc"], ["product", "vendor", "device/board", "device/soc", "config.json", "bundle.json"]),
    ]
    for title_needles, evidence_needles in checks:
        if any(n in lower_name for n in title_needles):
            if not any(n in combined for n in evidence_needles):
                return False, f"title/theme {title_needles} has no matching evidence needles {evidence_needles}"
    return True, ""


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--stage-result")
    args = ap.parse_args()
    out = Path(args.out)
    audit_dir = out / "06_audit"
    audit_dir.mkdir(parents=True, exist_ok=True)
    blocking: list[str] = []
    non_blocking: list[str] = []

    stats_path = out / "02_statistics/statistics_summary.json"
    if not stats_path.exists():
        blocking.append("missing statistics_summary.json")
        stats = {}
    else:
        try:
            stats = json.loads(stats_path.read_text(encoding="utf-8"))
        except Exception as exc:
            blocking.append(f"invalid statistics_summary.json: {exc}")
            stats = {}

    actual = {
        "commit_records_count": count_jsonl(out / "01_raw_records/commit_records.jsonl"),
        "file_change_records_count": count_jsonl(out / "01_raw_records/file_change_records.jsonl"),
        "binary_asset_records_count": count_csv(out / "01_raw_records/binary_asset_records.csv"),
        "dirty_file_records_count": count_jsonl(out / "01_raw_records/dirty_file_records.jsonl"),
    }
    for key, value in actual.items():
        if key in stats and stats.get(key) != value:
            blocking.append(f"{key} mismatch: stats={stats.get(key)} actual={value}")

    required = [
        "00_config/task_profile.yaml",
        "02_statistics/statistics_summary.json",
        "03_semantic_analysis/commit_analysis.jsonl",
        "03_semantic_analysis/risk_items.md",
        "04_knowledge_base/board_soc_porting_rules.md",
        "05_skill_output/generated_skill.md",
        "05_skill_output/agent_runbook.md",
        "05_skill_output/next_porting_task_template.md",
        "05_skill_output/quality_checklist.md",
    ]
    for item in required:
        path = out / item
        if not path.exists() or path.stat().st_size == 0:
            blocking.append(f"missing or empty artifact: {item}")

    repo_dir = out / "03_semantic_analysis/repo_analysis"
    subsystem_dir = out / "03_semantic_analysis/subsystem_analysis"
    if not repo_dir.exists() or not any(repo_dir.glob("*.md")):
        blocking.append("repo_analysis directory is empty")
    if not subsystem_dir.exists() or not any(subsystem_dir.glob("*.md")):
        blocking.append("subsystem_analysis directory is empty")

    task_profile = read_text(out / "00_config/task_profile.yaml").lower()
    generated_skill = read_text(out / "05_skill_output/generated_skill.md")
    skill_lower = generated_skill.lower()
    if "treat_riscv_as_primary_arch" in task_profile and "false" in task_profile:
        risky_phrases = [
            "t113 is riscv-primary",
            "t113 r-i-s-c-v primary",
            "risc-v is the openharmony runtime architecture for t113",
            "openharmony runs on riscv" ,
        ]
        for phrase in risky_phrases:
            if phrase in skill_lower.replace("‑", "-"):
                blocking.append(f"generated Skill appears to contradict ARM-primary T113 profile: {phrase}")

    for file_rel, min_len, headings in [
        ("05_skill_output/generated_skill.md", 5000, ["Applicability", "Evidence", "Quality", "Failure", "Examples", "Anti-Examples"]),
        ("05_skill_output/agent_runbook.md", 1500, ["Start", "Evidence", "Validation", "Failure"]),
        ("05_skill_output/next_porting_task_template.md", 1200, ["Target", "Inputs", "Scenario", "Risk", "Daily"]),
        ("05_skill_output/quality_checklist.md", 1200, ["Scope", "Raw", "Statistics", "Semantic", "Cases", "Audit"]),
    ]:
        text = read_text(out / file_rel)
        if len(text) < min_len:
            blocking.append(f"{file_rel} is too short: {len(text)} < {min_len}")
        for heading in headings:
            if heading.lower() not in text.lower():
                blocking.append(f"{file_rel} missing required section/concept: {heading}")

    commit_rows = read_jsonl(out / "01_raw_records/commit_records.jsonl")
    file_rows = read_jsonl(out / "01_raw_records/file_change_records.jsonl")
    dirty_rows = read_jsonl(out / "01_raw_records/dirty_file_records.jsonl")
    commit_hashes = set()
    for row in commit_rows:
        h = row.get("commit_hash") or row.get("hash") or row.get("commit")
        if h:
            commit_hashes.add(str(h))
            commit_hashes.add(str(h)[:12])
            commit_hashes.add(str(h)[:8])
    known_files = set()
    for row in [*file_rows, *dirty_rows]:
        fp = row.get("file_path") or row.get("path")
        rp = row.get("repo_path") or row.get("repo") or ""
        if fp:
            known_files.add(str(fp))
            known_files.add(f"{rp}/{fp}".strip("/"))

    cases = sorted((out / "04_knowledge_base/cases").glob("*.md"))
    if not cases:
        blocking.append("no cases generated")
    banned_template_phrases = [
        "claims in this case are limited to the evidence block above",
        "area carries",
        "main theme:",
    ]
    required_case_sections = ["Problem", "Root Cause", "Fix", "Reusable Rule", "Applicability", "Non-Applicability", "Verification", "Risks", "Confidence"]
    for case in cases:
        text = read_text(case)
        lower = text.lower()
        commits, files, bins = extract_case_evidence(text)
        if len(text) < 1200:
            blocking.append(f"case too short/template-like: {case.name} ({len(text)} chars)")
        for phrase in banned_template_phrases:
            if phrase in lower:
                blocking.append(f"case contains banned template phrase: {case.name}: {phrase}")
        for section in required_case_sections:
            if section.lower() not in lower:
                blocking.append(f"case missing section {section}: {case.name}")
        if not commits:
            blocking.append(f"case lacks commit evidence: {case.name}")
        else:
            if not any(c in commit_hashes or c[:12] in commit_hashes or c[:8] in commit_hashes for c in commits):
                blocking.append(f"case commit evidence not found in commit_records: {case.name}")
        if not files:
            blocking.append(f"case lacks file evidence: {case.name}")
        elif all_gitattributes(files):
            blocking.append(f"case evidence is .gitattributes-only: {case.name}")
        if "force sync sdk code" in lower and "rejected" not in lower and "non-applicability" not in lower:
            blocking.append(f"force-sync evidence promoted as reusable case: {case.name}")
        ok, reason = evidence_matches_theme(case.name, text, files)
        if not ok:
            blocking.append(f"case title/evidence mismatch: {case.name}: {reason}")

    # Binary record schema sanity.
    binary_path = out / "01_raw_records/binary_asset_records.csv"
    if binary_path.exists() and binary_path.stat().st_size > 0:
        with binary_path.open(encoding="utf-8", errors="ignore", newline="") as f:
            reader = csv.DictReader(f)
            headers = set(reader.fieldnames or [])
            if "sha256" not in headers:
                blocking.append("binary_asset_records.csv missing sha256 column")
            if not ({"path", "file_path"} & headers):
                blocking.append("binary_asset_records.csv missing path/file_path column")
            if "repo_path" not in headers:
                non_blocking.append("binary_asset_records.csv has no explicit repo_path; repo derivation will be heuristic")
            if "evidence_id" not in headers:
                non_blocking.append("binary_asset_records.csv has no explicit evidence_id; binary case validation is weaker")

    files_manifest = []
    hash_max_bytes = 50 * 1024 * 1024
    for path in sorted(out.rglob("*")):
        if path.is_file():
            size = path.stat().st_size
            if size <= hash_max_bytes:
                try:
                    digest = sha256(path)
                    hash_status = "sha256"
                except Exception:
                    digest = "unreadable"
                    hash_status = "error"
            else:
                digest = "skipped_large_file"
                hash_status = f"skipped_gt_{hash_max_bytes}_bytes"
            files_manifest.append({
                "path": str(path.relative_to(out)),
                "size": size,
                "sha256": digest,
                "hash_status": hash_status,
            })
    (audit_dir / "artifact_manifest.json").write_text(json.dumps({"files": files_manifest}, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    report_lines = [
        "# Final Audit Report",
        "",
        f"- Files in manifest: {len(files_manifest)}",
        f"- Blocking issues: {len(blocking)}",
        f"- Non-blocking issues: {len(non_blocking)}",
        "- Statistics checked against raw records.",
        "- Cases checked for visible evidence, section completeness, sync/noise leakage, and title/evidence consistency.",
        "- Generated Skill support files checked for minimum content and required sections.",
        "",
        "## Blocking Issues",
    ]
    report_lines.extend([f"- {item}" for item in blocking] if blocking else ["- None"])
    report_lines.extend(["", "## Non-Blocking Issues"])
    report_lines.extend([f"- {item}" for item in non_blocking] if non_blocking else ["- None"])
    report_lines.extend(["", "## Recommendation", "accept" if not blocking else "rerun_failed_stages", ""])
    (audit_dir / "final_audit_report.md").write_text("\n".join(report_lines), encoding="utf-8")
    (audit_dir / "blocking_issues.md").write_text(
        "# Blocking Issues\n\n" + ("\n".join(f"- {item}" for item in blocking) if blocking else "- None") + "\n",
        encoding="utf-8",
    )
    (audit_dir / "non_blocking_issues.md").write_text(
        "# Non-Blocking Issues\n\n" + ("\n".join(f"- {item}" for item in non_blocking) if non_blocking else "- None") + "\n",
        encoding="utf-8",
    )
    result = {
        "stage": "07_final_auditor",
        "status": "blocked" if blocking else "passed",
        "summary": f"Final audit completed with {len(blocking)} blocking and {len(non_blocking)} non-blocking issues.",
        "blocking_issue_count": len(blocking),
        "non_blocking_issue_count": len(non_blocking),
        "blocking_issues": blocking,
        "non_blocking_issues": non_blocking,
        "output_files_written": [
            "06_audit/final_audit_report.md",
            "06_audit/blocking_issues.md",
            "06_audit/non_blocking_issues.md",
            "06_audit/artifact_manifest.json",
        ],
        "recommendation": "rerun_failed_stages" if blocking else "accept",
    }
    if args.stage_result:
        Path(args.stage_result).write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
