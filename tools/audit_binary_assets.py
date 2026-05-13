#!/usr/bin/env python3
"""Deterministic binary/prebuilt asset auditor for the porting pipeline."""

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
    "01_raw_records/binary_asset_records.csv",
    "01_raw_records/file_change_records.jsonl",
    "01_raw_records/dirty_file_records.jsonl",
]

OUTPUT_FILES = [
    "01_raw_records/binary_asset_records.csv",
    "04_knowledge_base/binary_asset_index.md",
    "04_knowledge_base/binary_risk_report.md",
]

BINARY_EXTS = {
    ".a",
    ".bin",
    ".cmd",
    ".dll",
    ".elf",
    ".exe",
    ".hcb",
    ".img",
    ".jar",
    ".ko",
    ".o",
    ".so",
    ".zip",
    ".gz",
    ".xz",
    ".lz4",
    ".tar",
    ".bz2",
}


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists() or path.stat().st_size == 0:
        return []
    with path.open(encoding="utf-8", errors="ignore", newline="") as f:
        return list(csv.DictReader(f))


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


def suffix(path: str) -> str:
    return Path(path or "").suffix.lower()


def file_type(path: str) -> str:
    ext = suffix(path)
    lower = (path or "").lower()
    if ext:
        return ext.lstrip(".")
    if "prebuilt" in lower:
        return "prebuilt"
    return "unknown"


def guess_arch(path: str) -> str:
    lower = (path or "").lower()
    if "riscv64" in lower:
        return "riscv64"
    if "riscv" in lower or "risc-v" in lower:
        return "riscv"
    if "aarch64" in lower or "arm64" in lower:
        return "arm64"
    if re.search(r"(^|[/_.-])arm(v7|v8|32)?($|[/_.-])", lower):
        return "arm"
    if "x86_64" in lower or "amd64" in lower:
        return "x86_64"
    if re.search(r"(^|[/_.-])x86($|[/_.-])", lower):
        return "x86"
    return "unknown"


def possible_usage(path: str) -> str:
    lower = (path or "").lower()
    ext = suffix(path)
    if "toolchain" in lower or "clang" in lower or "gcc" in lower or "rustc" in lower:
        return "build_time_toolchain"
    if ext == ".ko":
        return "kernel_module"
    if ext in {".so", ".dll"}:
        return "runtime_library"
    if ext in {".bin", ".img", ".elf"} or any(token in lower for token in ("firmware", "spl", "uboot", "u-boot")):
        return "boot_or_firmware"
    if ext == ".hcb":
        return "hdf_generated_config"
    if ext in {".zip", ".gz", ".xz", ".lz4", ".tar", ".bz2"}:
        return "archive_payload"
    if ext in {".o", ".a", ".cmd"}:
        return "build_output_or_static_link"
    return "unknown"


def runtime_dependency(path: str, usage: str) -> str:
    if usage in {"runtime_library", "kernel_module", "boot_or_firmware", "hdf_generated_config"}:
        return "yes"
    if usage in {"build_time_toolchain", "build_output_or_static_link"}:
        return "build_time"
    return "unknown"


def risk_for(row: dict[str, Any]) -> tuple[str, str]:
    path = str(row.get("path") or row.get("file_path") or "")
    lower = path.lower()
    source_kind = str(row.get("source_kind") or "")
    if "dirty_workspace" in source_kind:
        return "unknown_requires_review", "unknown_requires_review"
    if "prebuilt" in lower or suffix(path) in BINARY_EXTS:
        return "unknown_requires_review", "unknown_requires_review"
    return "unknown", "unknown"


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
    kb = out / "04_knowledge_base"
    kb.mkdir(parents=True, exist_ok=True)

    rows = read_csv(raw / "binary_asset_records.csv")
    file_changes = read_jsonl(raw / "file_change_records.jsonl")
    dirty_files = read_jsonl(raw / "dirty_file_records.jsonl")

    existing_paths = {str(row.get("path") or "") for row in rows}
    for source_name, source_rows in [("file_change", file_changes), ("dirty_workspace", dirty_files)]:
        for item in source_rows:
            path = str(item.get("workspace_path") or "")
            rel = str(item.get("path") or item.get("file_path") or "")
            if not path and item.get("repo_path") and rel:
                path = f"{item.get('repo_path')}/{rel}"
            if not path or path in existing_paths:
                continue
            lower = path.lower()
            if suffix(path) not in BINARY_EXTS and "prebuilt" not in lower and "firmware" not in lower:
                continue
            rows.append(
                {
                    "evidence_id": f"binary_asset:derived:{source_name}:{path}",
                    "record_id": f"binary_asset:derived:{source_name}:{path}",
                    "repo_path": item.get("repo_path", ""),
                    "repo_name": item.get("repo_name", ""),
                    "classification": item.get("classification", ""),
                    "origin_type": item.get("origin_type", ""),
                    "source_kind": source_name,
                    "commit_hash": item.get("commit_hash") or item.get("head_revision") or "",
                    "commit": item.get("commit") or item.get("commit_hash") or item.get("head_revision") or "",
                    "path": path,
                    "file_path": rel,
                    "change_type": item.get("change_type") or item.get("xy_status") or "",
                    "change_status": item.get("change_status") or item.get("xy_status") or "",
                    "size_bytes": item.get("size_bytes") or item.get("blob_size") or "",
                    "sha256": item.get("sha256") or item.get("blob_sha256") or "",
                    "evidence_source": item.get("diff_path") or "",
                    "analysis_note": f"classification={item.get('classification', '')}; source=derived_{source_name}",
                }
            )
            existing_paths.add(path)

    for row in rows:
        path = str(row.get("path") or row.get("file_path") or "")
        row["path"] = path
        row["file_type"] = row.get("file_type") or file_type(path)
        row["size"] = row.get("size") or row.get("size_bytes") or row.get("blob_size") or ""
        row["size_bytes"] = row.get("size_bytes") or row.get("size") or ""
        row["architecture"] = row.get("architecture") or guess_arch(path)
        usage = row.get("possible_usage") or possible_usage(path)
        row["possible_usage"] = usage
        row["source_commit"] = row.get("source_commit") or row.get("commit_hash") or row.get("commit") or ""
        row["introduced_by"] = row.get("introduced_by") or row.get("source_kind") or row.get("origin_type") or ""
        license_risk, redistribution_risk = risk_for(row)
        row["license_risk"] = row.get("license_risk") or license_risk
        row["redistribution_risk"] = row.get("redistribution_risk") or redistribution_risk
        row["runtime_dependency"] = row.get("runtime_dependency") or runtime_dependency(path, usage)
        row["analysis_note"] = row.get("analysis_note") or "classification=unknown; source=binary_asset_auditor"

    fields = [
        "evidence_id",
        "record_id",
        "repo_path",
        "repo_name",
        "classification",
        "origin_type",
        "source_kind",
        "commit_hash",
        "commit",
        "source_commit",
        "introduced_by",
        "path",
        "file_path",
        "change_type",
        "change_status",
        "file_type",
        "size",
        "size_bytes",
        "sha256",
        "architecture",
        "possible_usage",
        "license_risk",
        "redistribution_risk",
        "runtime_dependency",
        "evidence_source",
        "analysis_note",
    ]
    write_csv(raw / "binary_asset_records.csv", rows, fields)

    by_usage = Counter(str(row.get("possible_usage") or "unknown") for row in rows)
    by_arch = Counter(str(row.get("architecture") or "unknown") for row in rows)
    by_repo = Counter(str(row.get("repo_path") or "unknown") for row in rows)
    missing_hash = [row for row in rows if not row.get("sha256")]
    risky = [
        row
        for row in rows
        if str(row.get("license_risk") or "").endswith("requires_review")
        or str(row.get("redistribution_risk") or "").endswith("requires_review")
    ]

    (kb / "binary_asset_index.md").write_text(
        "\n".join(
            [
                "# Binary Asset Index",
                "",
                markdown_table(
                    ["Metric", "Count"],
                    [
                        ["binary/prebuilt records", len(rows)],
                        ["records missing sha256", len(missing_hash)],
                        ["records requiring license/redistribution review", len(risky)],
                    ],
                ),
                "",
                "## By Usage",
                "",
                markdown_table(["Usage", "Count"], [[key, value] for key, value in by_usage.most_common()]),
                "",
                "## By Architecture",
                "",
                markdown_table(["Architecture", "Count"], [[key, value] for key, value in by_arch.most_common()]),
                "",
                "## Top Repositories",
                "",
                markdown_table(["Repo", "Count"], [[key, value] for key, value in by_repo.most_common(30)]),
                "",
                "## Sample Assets",
                "",
                markdown_table(
                    ["Repo", "Path", "Usage", "Arch", "SHA256"],
                    [
                        [
                            row.get("repo_path", ""),
                            row.get("path", ""),
                            row.get("possible_usage", ""),
                            row.get("architecture", ""),
                            str(row.get("sha256") or "")[:16],
                        ]
                        for row in rows[:80]
                    ],
                ),
                "",
            ]
        ),
        encoding="utf-8",
    )
    (kb / "binary_risk_report.md").write_text(
        "\n".join(
            [
                "# Binary Risk Report",
                "",
                "Binary and prebuilt records require provenance review before reuse in another OpenHarmony board/SoC port.",
                "",
                "## Review Summary",
                "",
                markdown_table(
                    ["Risk Bucket", "Count"],
                    [
                        ["missing sha256", len(missing_hash)],
                        ["license or redistribution unknown/requires review", len(risky)],
                        ["runtime dependency yes", sum(1 for row in rows if row.get("runtime_dependency") == "yes")],
                        ["build-time only", sum(1 for row in rows if row.get("runtime_dependency") == "build_time")],
                    ],
                ),
                "",
                "## Highest Priority Review Items",
                "",
                markdown_table(
                    ["Repo", "Path", "Usage", "Runtime", "Risk"],
                    [
                        [
                            row.get("repo_path", ""),
                            row.get("path", ""),
                            row.get("possible_usage", ""),
                            row.get("runtime_dependency", ""),
                            f"{row.get('license_risk', '')}/{row.get('redistribution_risk', '')}",
                        ]
                        for row in (risky[:80] or rows[:40])
                    ],
                ),
                "",
            ]
        ),
        encoding="utf-8",
    )

    result = {
        "stage": "aux_binary_asset_auditor",
        "status": "passed",
        "summary": f"Audited {len(rows)} binary/prebuilt records; {len(risky)} require provenance review and {len(missing_hash)} lack sha256.",
        "input_files_read": [f"porting_knowledge_output/{rel}" for rel in INPUT_FILES if (out / rel).exists()],
        "output_files_written": [f"porting_knowledge_output/{rel}" for rel in OUTPUT_FILES],
        "blocking_issues": [],
        "non_blocking_issues": [
            "License and redistribution risks are conservative classifications derived from path/type evidence and require human provenance review."
        ],
        "next_stage_inputs": [
            "porting_knowledge_output/01_raw_records/binary_asset_records.csv",
            "porting_knowledge_output/04_knowledge_base/binary_asset_index.md",
            "porting_knowledge_output/04_knowledge_base/binary_risk_report.md",
        ],
    }
    if args.stage_result:
        Path(args.stage_result).write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
