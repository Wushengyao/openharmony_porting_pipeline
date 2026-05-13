#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
from datetime import datetime
import json
import re
import sys
from pathlib import Path
from typing import Any


def log(level: str, msg: str) -> None:
    ts = datetime.now().astimezone().strftime("%Y-%m-%dT%H:%M:%S%z")
    print(f"[{ts}] [{level}] {msg}", file=sys.stderr)


def fail(msg: str) -> None:
    log("BLOCKED", msg)
    sys.exit(1)


def warn(msg: str) -> None:
    log("WARN", msg)


def require_file(path: Path) -> None:
    log("CHECK", f"require non-empty file: {path}")
    if not path.exists():
        fail(f"Missing required file: {path}")
    if path.is_file() and path.stat().st_size == 0:
        fail(f"Empty required file: {path}")
    if path.is_file():
        log("OK", f"file present: {path} ({path.stat().st_size} bytes)")


def require_exists(path: Path) -> None:
    log("CHECK", f"require path exists: {path}")
    if not path.exists():
        fail(f"Missing required path: {path}")
    log("OK", f"path present: {path}")


def require_dir(path: Path) -> None:
    log("CHECK", f"require directory: {path}")
    if not path.exists() or not path.is_dir():
        fail(f"Missing required directory: {path}")
    log("OK", f"directory present: {path}")


def require_nonempty_dir(path: Path) -> None:
    require_dir(path)
    entries = list(path.iterdir())
    if not entries:
        fail(f"Empty required directory: {path}")
    log("OK", f"directory non-empty: {path} ({len(entries)} entries)")


def count_jsonl(path: Path) -> int:
    if not path.exists():
        return 0
    with path.open("r", encoding="utf-8", errors="ignore") as f:
        return sum(1 for line in f if line.strip())


def count_csv_rows(path: Path) -> int:
    if not path.exists() or path.stat().st_size == 0:
        return 0
    with path.open("r", encoding="utf-8", errors="ignore", newline="") as f:
        try:
            return max(0, sum(1 for _ in csv.reader(f)) - 1)
        except Exception:
            return 0


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
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


def load_stage_result(path: Path) -> dict[str, Any]:
    require_file(path)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        fail(f"Stage result is not JSON: {path}: {e}")
    log("INFO", f"stage result loaded: stage={data.get('stage')} status={data.get('status')} outputs={len(data.get('output_files_written') or [])}")
    if data.get("status") == "blocked":
        fail(f"Stage reported blocked: {data.get('blocking_issues')}")
    return data


def extract_case_evidence(text: str) -> tuple[list[str], list[str]]:
    commits = [x.strip() for x in re.findall(r"commit_hash:\s*([^\n\r]+)", text)]
    files = [x.strip() for x in re.findall(r"file_path:\s*([^\n\r]+)", text)]
    return commits, files


def validate_case_evidence(out: Path) -> None:
    commits_path = out / "01_raw_records/commit_records.jsonl"
    files_path = out / "01_raw_records/file_change_records.jsonl"
    dirty_files_path = out / "01_raw_records/dirty_file_records.jsonl"
    commit_hashes: set[str] = set()
    file_keys: set[str] = set()

    for obj in read_jsonl(commits_path):
        h = obj.get("commit_hash") or obj.get("hash") or obj.get("commit")
        if h:
            h = str(h)
            commit_hashes.update([h, h[:12], h[:8]])
    for p in [files_path, dirty_files_path]:
        for obj in read_jsonl(p):
            fp = obj.get("file_path") or obj.get("path")
            rp = obj.get("repo_path") or obj.get("repo") or ""
            if fp:
                fp = str(fp)
                file_keys.add(fp)
                file_keys.add(f"{rp}/{fp}".strip("/"))

    cases_dir = out / "04_knowledge_base/cases"
    require_nonempty_dir(cases_dir)
    log("INFO", f"case evidence index: commit_markers={len(commit_hashes)} file_markers={len(file_keys)}")

    weak: list[str] = []
    required_sections = ["Problem", "Root Cause", "Fix", "Reusable Rule", "Applicability", "Non-Applicability", "Verification", "Risks", "Confidence"]
    banned_phrases = [
        "claims in this case are limited to the evidence block above",
        "area carries",
        "main theme:",
    ]
    for case in cases_dir.glob("*.md"):
        text = case.read_text(encoding="utf-8", errors="ignore")
        lower = text.lower()
        commits, files = extract_case_evidence(text)
        if len(text) < 1200:
            weak.append(f"{case.name}: too short ({len(text)} chars)")
        for section in required_sections:
            if section.lower() not in lower:
                weak.append(f"{case.name}: missing section {section}")
        for phrase in banned_phrases:
            if phrase in lower:
                weak.append(f"{case.name}: banned template phrase {phrase}")
        if not commits or not any(c in commit_hashes or c[:12] in commit_hashes or c[:8] in commit_hashes for c in commits):
            weak.append(f"{case.name}: commit evidence absent from commit_records")
        if not files:
            weak.append(f"{case.name}: missing file_path evidence")
        elif all(Path(p).name == ".gitattributes" for p in files):
            weak.append(f"{case.name}: .gitattributes-only evidence")
        if "force sync sdk code" in lower and "non-applicability" not in lower:
            weak.append(f"{case.name}: force-sync evidence promoted as reusable case")
        # Coarse title/evidence semantic checks.
        title = case.name.lower()
        evidence_text = " ".join([title, lower, *files]).lower()
        checks = [
            (["hdf", "audio"], ["hdf", "audio", "codec", "dai", "dma", "hcs", "hcb", "speaker"]),
            (["wifi", "wpa"], ["wifi", "wpa", "supplicant", "libnl", "dhcpcd", "bk7236", "wireless"]),
            (["boot", "firmware"], ["boot", "brandy", "u-boot", "uboot", "spl", "arisc", "dsp", "fex", ".bin", ".dts", ".dtsi"]),
        ]
        for title_needles, evidence_needles in checks:
            if any(n in title for n in title_needles) and not any(n in evidence_text for n in evidence_needles):
                weak.append(f"{case.name}: title/evidence mismatch for {title_needles}")
    if weak:
        fail("Case quality/evidence failures: " + "; ".join(weak[:20]))


def require_text_quality(path: Path, min_chars: int, required_terms: list[str]) -> None:
    require_file(path)
    text = path.read_text(encoding="utf-8", errors="ignore")
    if len(text) < min_chars:
        fail(f"{path.name} is too short: {len(text)} < {min_chars}")
    missing = [term for term in required_terms if term.lower() not in text.lower()]
    if missing:
        fail(f"{path.name} missing required terms/sections: {missing}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workspace", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--stage", required=True)
    ap.add_argument("--stage-result", required=True)
    args = ap.parse_args()

    out = Path(args.out)
    stage = args.stage
    workspace = Path(args.workspace)
    log("INFO", f"validate start: stage={stage} workspace={workspace} out={out}")
    load_stage_result(Path(args.stage_result))

    if stage == "00_scope_classifier":
        require_file(out / "00_config/task_profile.yaml")
        require_file(out / "00_config/scope_classification_report.md")

    elif stage == "01_repo_baseline_extractor":
        require_file(out / "00_config/repo_revision_map.csv")
        require_file(out / "01_raw_records/repo_list.csv")
        require_file(out / "01_raw_records/repo_status.raw.txt")

    elif stage == "02_raw_record_extractor":
        require_file(out / "01_raw_records/commit_records.jsonl")
        require_file(out / "01_raw_records/file_change_records.jsonl")
        require_file(out / "01_raw_records/binary_asset_records.csv")
        require_file(out / "01_raw_records/dirty_repo_records.csv")
        require_exists(out / "01_raw_records/dirty_file_records.jsonl")
        require_file(out / "01_raw_records/untracked_file_records.csv")
        require_dir(out / "01_raw_records/diffs")
        require_file(out / "03_semantic_analysis/evidence_index.jsonl")
        if count_jsonl(out / "01_raw_records/commit_records.jsonl") == 0:
            fail("commit_records.jsonl has no records")
        if count_jsonl(out / "01_raw_records/file_change_records.jsonl") == 0:
            fail("file_change_records.jsonl has no records")

    elif stage == "aux_dirty_workspace":
        require_file(out / "01_raw_records/dirty_repo_records.csv")
        require_exists(out / "01_raw_records/dirty_file_records.jsonl")
        require_file(out / "01_raw_records/untracked_file_records.csv")
        require_file(out / "03_semantic_analysis/dirty_workspace_analysis.md")

    elif stage == "aux_binary_asset_auditor":
        require_file(out / "01_raw_records/binary_asset_records.csv")
        require_file(out / "04_knowledge_base/binary_asset_index.md")
        require_file(out / "04_knowledge_base/binary_risk_report.md")

    elif stage == "03_statistics_qc":
        require_file(out / "02_statistics/statistics_summary.json")
        require_file(out / "02_statistics/statistics_summary.md")
        require_file(out / "02_statistics/qc_report.md")
        try:
            stats = json.loads((out / "02_statistics/statistics_summary.json").read_text(encoding="utf-8"))
        except Exception as e:
            fail(f"statistics_summary.json invalid: {e}")
        actual_commits = count_jsonl(out / "01_raw_records/commit_records.jsonl")
        actual_files = count_jsonl(out / "01_raw_records/file_change_records.jsonl")
        actual_bin = count_csv_rows(out / "01_raw_records/binary_asset_records.csv")
        if stats.get("commit_records_count") != actual_commits:
            fail(f"commit count mismatch: stats={stats.get('commit_records_count')} actual={actual_commits}")
        if stats.get("file_change_records_count") != actual_files:
            fail(f"file change count mismatch: stats={stats.get('file_change_records_count')} actual={actual_files}")
        if "binary_asset_records_count" in stats and stats.get("binary_asset_records_count") != actual_bin:
            fail(f"binary asset count mismatch: stats={stats.get('binary_asset_records_count')} actual={actual_bin}")

    elif stage == "04_semantic_analyzer":
        require_file(out / "03_semantic_analysis/commit_analysis.jsonl")
        require_nonempty_dir(out / "03_semantic_analysis/repo_analysis")
        require_nonempty_dir(out / "03_semantic_analysis/subsystem_analysis")
        require_file(out / "03_semantic_analysis/risk_items.md")
        require_file(out / "03_semantic_analysis/workaround_items.md")
        # If deterministic candidate files exist, they must be non-empty when candidate commits exist.
        candidate_path = out / "03_semantic_analysis/_llm_inputs/semantic_candidate_commits.jsonl"
        if candidate_path.exists():
            log("INFO", f"semantic candidate records={count_jsonl(candidate_path)}")

    elif stage == "05_case_kb_builder":
        require_nonempty_dir(out / "04_knowledge_base/cases")
        require_file(out / "04_knowledge_base/board_soc_porting_rules.md")
        require_file(out / "04_knowledge_base/path_module_index.md")
        require_file(out / "04_knowledge_base/workaround_items.md")
        validate_case_evidence(out)

    elif stage == "06_skill_generator":
        require_text_quality(out / "05_skill_output/generated_skill.md", 5000, ["Applicability", "Non-Applicability", "Evidence", "Quality", "Failure", "Examples", "Anti-Examples", "ARM", "RISC-V", "heterogeneous"])
        require_text_quality(out / "05_skill_output/agent_runbook.md", 1500, ["Start", "Evidence", "Validation", "Failure"])
        require_text_quality(out / "05_skill_output/next_porting_task_template.md", 1200, ["Target", "Inputs", "Scenario", "Risk", "Daily"])
        require_text_quality(out / "05_skill_output/quality_checklist.md", 1200, ["Scope", "Raw", "Statistics", "Semantic", "Cases", "Audit"])

    elif stage == "07_final_auditor":
        require_file(out / "06_audit/final_audit_report.md")
        require_file(out / "06_audit/blocking_issues.md")
        require_file(out / "06_audit/non_blocking_issues.md")
        require_file(out / "06_audit/artifact_manifest.json")
        blocking_text = (out / "06_audit/blocking_issues.md").read_text(encoding="utf-8", errors="ignore").strip()
        if "- None" not in blocking_text and len(blocking_text.splitlines()) > 2:
            fail("final auditor reported blocking issues")

    else:
        fail(f"Unknown stage: {stage}")

    log("INFO", f"validate complete: stage={stage}")
    print(f"[OK] {stage}")


if __name__ == "__main__":
    main()
