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


def clean_marker(value: str) -> str:
    value = value.split("#", 1)[0].strip()
    return value.strip("`'\", ")


def extract_case_evidence(text: str) -> tuple[list[str], list[dict[str, Any]]]:
    commits: list[str] = []
    files: list[dict[str, Any]] = []
    current_repo = ""
    for raw_line in text.splitlines():
        line = raw_line.strip()
        line = re.sub(r"^[-*]\s+", "", line)
        repo_match = re.match(r"repo_path:\s*([^\n\r]+)", line)
        if repo_match:
            current_repo = clean_marker(repo_match.group(1))
            continue
        commit_match = re.match(r"commit_hash:\s*([^\n\r]+)", line)
        if commit_match:
            commits.append(clean_marker(commit_match.group(1)))
            continue
        file_match = re.match(r"file_path:\s*([^\n\r]+)", line)
        if file_match:
            file_path = clean_marker(file_match.group(1))
            candidates = [file_path]
            if current_repo and not file_path.startswith(f"{current_repo}/"):
                candidates.append(f"{current_repo}/{file_path}".strip("/"))
            files.append({"file_path": file_path, "repo_path": current_repo, "candidates": candidates})
    return commits, files


def extract_body_file_refs(text: str) -> set[str]:
    refs: set[str] = set()
    path_re = re.compile(r"(?<![\w./-])(?:[A-Za-z0-9_.+-]+/){1,}[A-Za-z0-9_.+-]+")
    ignored_prefixes = (
        "01_raw_records/diffs/",
        "04_knowledge_base/",
        "05_skill_output/",
        "06_audit/",
        "porting_knowledge_output/",
    )
    for match in path_re.finditer(text):
        ref = match.group(0).strip("`'\",.)]")
        if ref in {"o/.cmd", "a/.cmd", "so/.cmd"}:
            continue
        if ref.startswith(ignored_prefixes):
            continue
        name = Path(ref).name
        if "." not in name and name not in {"BUILD.gn", "BoardConfig.mk"}:
            continue
        refs.add(ref)
    return refs


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
        if "validator evidence" in lower:
            weak.append(f"{case.name}: uses secondary Validator Evidence block instead of the canonical evidence schema")
        if "evidence:" not in lower or "commits:" not in lower or "files:" not in lower:
            weak.append(f"{case.name}: missing canonical evidence/commits/files schema")
        for section in required_sections:
            if section.lower() not in lower:
                weak.append(f"{case.name}: missing section {section}")
        for phrase in banned_phrases:
            if phrase in lower:
                weak.append(f"{case.name}: banned template phrase {phrase}")
        missing_commits = [c for c in commits if c not in commit_hashes and c[:12] not in commit_hashes and c[:8] not in commit_hashes]
        if not commits:
            weak.append(f"{case.name}: commit evidence absent from commit_records")
        elif missing_commits:
            weak.append(f"{case.name}: unresolved commit_hash values: {missing_commits[:3]}")
        missing_files = [
            f["file_path"]
            for f in files
            if not any(candidate in file_keys for candidate in f["candidates"])
        ]
        if not files:
            weak.append(f"{case.name}: missing file_path evidence")
        elif missing_files:
            weak.append(f"{case.name}: unresolved file_path values: {missing_files[:3]}")
        elif all(Path(f["file_path"]).name == ".gitattributes" for f in files):
            weak.append(f"{case.name}: .gitattributes-only evidence")
        unsupported_body_refs = sorted(
            ref
            for ref in extract_body_file_refs(text)
            if ref not in file_keys
        )
        if unsupported_body_refs:
            weak.append(f"{case.name}: unsupported body file references: {unsupported_body_refs[:5]}")
        if "force sync sdk code" in lower and "non-applicability" not in lower:
            weak.append(f"{case.name}: force-sync evidence promoted as reusable case")
        # Coarse title/evidence semantic checks.
        title = case.name.lower()
        evidence_file_text = " ".join(f["file_path"] for f in files)
        evidence_text = " ".join([title, lower, evidence_file_text]).lower()
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


def validate_semantic_outputs(out: Path) -> None:
    commit_analysis = out / "03_semantic_analysis/commit_analysis.jsonl"
    subsystem_dir = out / "03_semantic_analysis/subsystem_analysis"
    generic_names = {
        "board_soc_porting_scope.md",
        "bootloader_packaging_scope.md",
        "kernel_scope.md",
        "openharmony_common.md",
    }
    feature_files = [
        path for path in subsystem_dir.glob("*.md")
        if path.name not in generic_names
    ]
    if count_jsonl(commit_analysis) > 0 and len(feature_files) < 3:
        fail(
            "subsystem_analysis lacks feature-level files; expected at least three files beyond coarse classification buckets"
        )
    noisy_candidates: list[str] = []
    for obj in read_jsonl(commit_analysis):
        subject = str(obj.get("subject") or "").lower()
        files: list[str] = []
        for item in obj.get("evidence_files") or []:
            if isinstance(item, dict):
                files.append(str(item.get("file_path") or item.get("path") or ""))
            else:
                files.append(str(item))
        files = [fp for fp in files if fp]
        gitattributes_only = bool(files) and all(Path(fp).name == ".gitattributes" for fp in files)
        force_sync = "force sync sdk code" in subject or "force-sync" in subject
        if obj.get("is_case_candidate") and (force_sync or gitattributes_only or obj.get("origin_type") == "initial_import"):
            noisy_candidates.append(str(obj.get("commit_hash") or obj.get("commit_evidence_id")))
    if noisy_candidates:
        fail(f"noise commits marked as case candidates: {noisy_candidates[:5]}")


def validate_success_logs(out: Path) -> None:
    result_dir = out / "_stage_results"
    log_dir = out / "_codex_stage_logs"
    bad: list[str] = []
    if not result_dir.exists() or not log_dir.exists():
        return
    for result_path in result_dir.glob("*.json"):
        try:
            data = json.loads(result_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if data.get("status") != "passed":
            continue
        validation_log = log_dir / f"{result_path.stem}.validation.log"
        if validation_log.exists():
            text = validation_log.read_text(encoding="utf-8", errors="ignore")
            if "[BLOCKED]" in text or "validation failed" in text:
                bad.append(validation_log.name)
    if bad:
        fail(f"canonical validation logs contain failed attempts for passed stages: {bad[:8]}")


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
        validate_semantic_outputs(out)
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
        validate_success_logs(out)

    else:
        fail(f"Unknown stage: {stage}")

    log("INFO", f"validate complete: stage={stage}")
    print(f"[OK] {stage}")


if __name__ == "__main__":
    main()
