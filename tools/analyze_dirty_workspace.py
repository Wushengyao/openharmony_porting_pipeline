#!/usr/bin/env python3
"""Deterministic dirty-workspace analyzer for the porting pipeline."""

from __future__ import annotations

import argparse
import csv
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


INPUT_FILES = [
    "00_config/task_profile.yaml",
    "01_raw_records/repo_status.raw.txt",
    "01_raw_records/dirty_repo_records.csv",
    "01_raw_records/dirty_file_records.jsonl",
    "01_raw_records/untracked_file_records.csv",
]

OUTPUT_FILES = [
    "01_raw_records/dirty_repo_records.csv",
    "01_raw_records/dirty_file_records.jsonl",
    "01_raw_records/untracked_file_records.csv",
    "03_semantic_analysis/dirty_workspace_analysis.md",
]


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
                pass
    return rows


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists() or path.stat().st_size == 0:
        return []
    with path.open(encoding="utf-8", errors="ignore", newline="") as f:
        return list(csv.DictReader(f))


def write_csv(path: Path, rows: list[dict[str, Any]], preferred_fields: list[str]) -> None:
    fields = list(preferred_fields)
    seen = set(fields)
    for row in rows:
        for key in row:
            if key not in seen:
                fields.append(key)
                seen.add(key)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in fields})


def classify_dirty(path: str, path_type: str = "") -> str:
    lower = (path or "").lower()
    suffix = Path(path or "").suffix.lower()
    if "prebuilt" in lower or "toolchain" in lower or "clang" in lower or "gcc" in lower:
        return "prebuilt_import"
    if any(part in lower for part in ("/out/", "/build/", "/obj/", "/gen/", "/target/")) or lower.startswith(("out/", "build/")):
        return "build_output"
    if suffix in {".o", ".a", ".cmd", ".ko", ".so", ".bin", ".img", ".hcb", ".zip", ".gz", ".xz", ".lz4", ".tar"}:
        return "binary" if suffix not in {".hcb", ".cmd", ".o"} else "generated"
    if suffix in {".c", ".cc", ".cpp", ".cxx", ".h", ".hpp", ".java", ".js", ".ts", ".py", ".rs", ".go", ".sh", ".S".lower()}:
        return "source"
    if suffix in {".gn", ".gni", ".json", ".xml", ".yaml", ".yml", ".mk", ".ini", ".cfg", ".conf", ".hcs", ".dts", ".dtsi"}:
        return "config"
    if path_type == "directory":
        return "unknown_directory"
    return "unknown"


def markdown_table(headers: list[str], rows: list[list[Any]]) -> str:
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join(["---"] * len(headers)) + " |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(str(cell) for cell in row) + " |")
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--stage-result")
    args = ap.parse_args()
    out = Path(args.out)
    raw = out / "01_raw_records"
    sem = out / "03_semantic_analysis"
    sem.mkdir(parents=True, exist_ok=True)

    dirty_repos = read_csv(raw / "dirty_repo_records.csv")
    dirty_files = read_jsonl(raw / "dirty_file_records.jsonl")
    untracked = read_csv(raw / "untracked_file_records.csv")

    for row in dirty_files:
        row["dirty_content_class"] = classify_dirty(str(row.get("path") or row.get("file_path") or ""), str(row.get("path_type") or ""))
    for row in untracked:
        row["dirty_content_class"] = classify_dirty(str(row.get("path") or row.get("file_path") or ""), str(row.get("path_type") or ""))

    counts_by_repo: dict[str, dict[str, int]] = defaultdict(lambda: {"modified": 0, "untracked": 0, "total": 0})
    for row in dirty_files:
        repo = str(row.get("repo_path") or "unknown")
        counts_by_repo[repo]["total"] += 1
        if str(row.get("xy_status") or "").startswith("??"):
            counts_by_repo[repo]["untracked"] += 1
        else:
            counts_by_repo[repo]["modified"] += 1
    seen_repos = set()
    for row in dirty_repos:
        repo = str(row.get("repo_path") or "unknown")
        seen_repos.add(repo)
        counts = counts_by_repo[repo]
        row["tracked_dirty_count"] = counts["modified"]
        row["modified_file_count"] = counts["modified"]
        row["untracked_file_count"] = counts["untracked"]
    for repo, counts in counts_by_repo.items():
        if repo in seen_repos:
            continue
        dirty_repos.append(
            {
                "evidence_id": f"dirty_repo:{repo}",
                "record_id": f"dirty_repo:{repo}",
                "repo_path": repo,
                "origin_type": "dirty_workspace",
                "tracked_dirty_count": counts["modified"],
                "modified_file_count": counts["modified"],
                "untracked_file_count": counts["untracked"],
            }
        )

    write_jsonl(raw / "dirty_file_records.jsonl", dirty_files)
    write_csv(
        raw / "untracked_file_records.csv",
        untracked,
        [
            "evidence_id",
            "record_id",
            "repo_path",
            "repo_name",
            "classification",
            "head_revision",
            "origin_type",
            "path",
            "file_path",
            "workspace_path",
            "path_type",
            "dirty_content_class",
            "size_bytes",
            "sha256",
            "is_binary_or_prebuilt",
            "evidence_source",
        ],
    )
    write_csv(
        raw / "dirty_repo_records.csv",
        dirty_repos,
        [
            "evidence_id",
            "record_id",
            "repo_path",
            "repo_name",
            "classification",
            "head_revision",
            "current_branch",
            "origin_type",
            "tracked_dirty_count",
            "modified_file_count",
            "untracked_file_count",
            "diff_path",
            "extracted_at",
        ],
    )

    class_counts = Counter(str(row.get("dirty_content_class") or "unknown") for row in dirty_files)
    repo_counts = Counter(str(row.get("repo_path") or "unknown") for row in dirty_files)
    type_counts = Counter(str(row.get("path_type") or "unknown") for row in dirty_files)
    untracked_dirs = [row for row in untracked if str(row.get("path_type") or "") == "directory"]

    repo_rows = []
    for repo, counts in sorted(counts_by_repo.items(), key=lambda item: (-item[1]["total"], item[0]))[:30]:
        repo_rows.append([repo, counts["modified"], counts["untracked"], counts["total"]])

    report = [
        "# Dirty Workspace Analysis",
        "",
        "Dirty workspace records are treated as local work-in-progress evidence and are not merged into committed history.",
        "",
        "## Summary",
        "",
        markdown_table(
            ["Metric", "Count"],
            [
                ["dirty repositories", len(dirty_repos)],
                ["dirty file records", len(dirty_files)],
                ["untracked records", len(untracked)],
                ["untracked directory records", len(untracked_dirs)],
            ],
        ),
        "",
        "## Content Classes",
        "",
        markdown_table(["Class", "Count"], [[key, value] for key, value in class_counts.most_common()]),
        "",
        "## Path Types",
        "",
        markdown_table(["Path Type", "Count"], [[key, value] for key, value in type_counts.most_common()]),
        "",
        "## Repositories With Dirty Evidence",
        "",
        markdown_table(["Repo", "Modified", "Untracked", "Total"], repo_rows),
        "",
        "## Bounded Untracked Directories",
        "",
        markdown_table(
            ["Repo", "Path"],
            [[row.get("repo_path", ""), row.get("path", "")] for row in untracked_dirs[:80]],
        ),
        "",
    ]
    (sem / "dirty_workspace_analysis.md").write_text("\n".join(report), encoding="utf-8")

    result = {
        "stage": "aux_dirty_workspace",
        "status": "passed",
        "summary": (
            f"Classified {len(dirty_files)} dirty file records across {len(repo_counts)} repos; "
            f"{len(untracked_dirs)} untracked directories remain bounded."
        ),
        "input_files_read": [f"porting_knowledge_output/{rel}" for rel in INPUT_FILES if (out / rel).exists()],
        "output_files_written": [f"porting_knowledge_output/{rel}" for rel in OUTPUT_FILES],
        "blocking_issues": [],
        "non_blocking_issues": [],
        "next_stage_inputs": [
            "porting_knowledge_output/01_raw_records/dirty_repo_records.csv",
            "porting_knowledge_output/01_raw_records/dirty_file_records.jsonl",
            "porting_knowledge_output/01_raw_records/untracked_file_records.csv",
            "porting_knowledge_output/03_semantic_analysis/dirty_workspace_analysis.md",
        ],
    }
    if args.stage_result:
        Path(args.stage_result).write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
