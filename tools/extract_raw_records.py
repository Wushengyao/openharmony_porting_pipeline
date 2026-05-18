#!/usr/bin/env python3
"""Deterministic raw-record extractor for the OpenHarmony porting pipeline."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import shutil
import subprocess
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


MAX_HASH_BYTES = 128 * 1024 * 1024
MAX_BLOB_INFO_FILES_PER_COMMIT = 1000

BINARY_EXTS = {
    ".a",
    ".bin",
    ".bmp",
    ".bz2",
    ".cmd",
    ".class",
    ".dat",
    ".dll",
    ".elf",
    ".exe",
    ".gif",
    ".gz",
    ".hcb",
    ".img",
    ".jar",
    ".jpeg",
    ".jpg",
    ".ko",
    ".lz4",
    ".o",
    ".otf",
    ".png",
    ".so",
    ".tar",
    ".ttf",
    ".webp",
    ".woff",
    ".woff2",
    ".xz",
    ".zip",
}

BINARY_MARKERS = (
    "prebuilt",
    "prebuilts",
    "toolchain",
    "gcc",
    "clang",
    "rustc",
    "node_modules",
    "firmware",
    "fw",
    "spl",
    "uboot",
    "u-boot",
)

INPUT_FILES = [
    "00_config/task_profile.yaml",
    "00_config/repo_revision_map.csv",
    "01_raw_records/repo_list.csv",
    "01_raw_records/repo_status.raw.txt",
]

OUTPUT_FILES = [
    "01_raw_records/commit_records.jsonl",
    "01_raw_records/file_change_records.jsonl",
    "01_raw_records/binary_asset_records.csv",
    "01_raw_records/dirty_repo_records.csv",
    "01_raw_records/dirty_file_records.jsonl",
    "01_raw_records/untracked_file_records.csv",
    "01_raw_records/diffs",
    "03_semantic_analysis/evidence_index.jsonl",
]


def log(message: str) -> None:
    print(f"[extract_raw_records] {message}", file=sys.stderr)


def run_git(root: Path, repo: str, args: list[str], text: bool = True) -> subprocess.CompletedProcess[Any]:
    kwargs: dict[str, Any] = {
        "stdout": subprocess.PIPE,
        "stderr": subprocess.PIPE,
        "text": text,
        "check": False,
    }
    if text:
        kwargs.update({"encoding": "utf-8", "errors": "replace"})
    return subprocess.run(["git", "-C", str(root / repo), *args], **kwargs)


def run_git_to_file(root: Path, repo: str, args: list[str], path: Path) -> subprocess.CompletedProcess[str]:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as handle:
        return subprocess.run(
            ["git", "-C", str(root / repo), *args],
            stdout=handle,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists() or path.stat().st_size == 0:
        return []
    with path.open(encoding="utf-8", errors="ignore", newline="") as f:
        return list(csv.DictReader(f))


def write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in fieldnames})


def write_jsonl_row(handle: Any, row: dict[str, Any]) -> None:
    handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def safe_name(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", value).strip("_") or "root"


def workspace_path(repo: str, path: str) -> str:
    if not path:
        return repo
    return f"{repo.rstrip('/')}/{path.lstrip('/')}"


def path_kind(path: str) -> str:
    suffix = Path(path or "").suffix.lower()
    lower = (path or "").lower()
    if suffix in BINARY_EXTS:
        return suffix.lstrip(".")
    if "prebuilt" in lower:
        return "prebuilt"
    if "firmware" in lower or any(marker in lower for marker in ("spl", "uboot", "u-boot")):
        return "firmware"
    return suffix.lstrip(".") if suffix else "no_ext"


def is_binary_or_prebuilt(path: str, numstat_binary: bool = False, nul_detected: bool = False) -> bool:
    lower = (path or "").lower()
    suffix = Path(path or "").suffix.lower()
    return numstat_binary or nul_detected or suffix in BINARY_EXTS or any(marker in lower for marker in BINARY_MARKERS)


def guess_arch(path: str) -> str:
    lower = (path or "").lower()
    if any(token in lower for token in ("riscv64", "risc-v64")):
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


def guess_possible_usage(path: str) -> str:
    lower = (path or "").lower()
    suffix = Path(path or "").suffix.lower()
    if "toolchain" in lower or "clang" in lower or "gcc" in lower or "rustc" in lower:
        return "build_time_toolchain"
    if suffix == ".ko":
        return "kernel_module"
    if suffix in {".so", ".dll"}:
        return "runtime_library"
    if suffix in {".bin", ".img", ".elf"} or any(token in lower for token in ("firmware", "spl", "uboot", "u-boot")):
        return "boot_or_firmware"
    if suffix == ".hcb":
        return "hdf_generated_config"
    if suffix in {".zip", ".gz", ".xz", ".lz4", ".tar", ".bz2", ".7z"}:
        return "archive_payload"
    if suffix in {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".ttf", ".otf", ".woff", ".woff2"}:
        return "media_or_font_asset"
    if suffix in {".o", ".a", ".cmd"}:
        return "build_output_or_static_link"
    return "unknown"


def parse_shortstat(text: str) -> tuple[int, int, int]:
    files = insertions = deletions = 0
    m = re.search(r"(\d+) files? changed", text)
    if m:
        files = int(m.group(1))
    m = re.search(r"(\d+) insertions?", text)
    if m:
        insertions = int(m.group(1))
    m = re.search(r"(\d+) deletions?", text)
    if m:
        deletions = int(m.group(1))
    return files, insertions, deletions


def int_or_zero(value: str) -> int:
    try:
        return int(value)
    except Exception:
        return 0


def git_blob_info(root: Path, repo: str, commit_hash: str, file_path: str) -> tuple[str, str, bool]:
    size_cp = run_git(root, repo, ["cat-file", "-s", f"{commit_hash}:{file_path}"])
    if size_cp.returncode != 0:
        return "", "", False
    size_text = size_cp.stdout.strip()
    try:
        size = int(size_text)
    except Exception:
        size = 0
    if size > MAX_HASH_BYTES:
        return size_text, "", False
    proc = subprocess.Popen(
        ["git", "-C", str(root / repo), "show", f"{commit_hash}:{file_path}"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    digest = hashlib.sha256()
    prefix = bytearray()
    assert proc.stdout is not None
    while True:
        chunk = proc.stdout.read(1024 * 1024)
        if not chunk:
            break
        digest.update(chunk)
        if len(prefix) < 8192:
            prefix.extend(chunk[: 8192 - len(prefix)])
    proc.stdout.close()
    if proc.stderr is not None:
        proc.stderr.read()
        proc.stderr.close()
    proc.wait()
    if proc.returncode != 0:
        return size_text, "", False
    return size_text, digest.hexdigest(), b"\0" in prefix


def local_file_info(path: Path) -> tuple[str, str]:
    try:
        stat = path.stat()
    except OSError:
        return "", ""
    if stat.st_size > MAX_HASH_BYTES:
        return str(stat.st_size), ""
    try:
        data = path.read_bytes()
    except OSError:
        return str(stat.st_size), ""
    return str(stat.st_size), hashlib.sha256(data).hexdigest()


def emit_evidence(
    handle: Any,
    *,
    evidence_id: str,
    record_type: str,
    repo_path: str,
    subject_id: str,
    origin_type: str,
    source_path: str,
    summary: str,
    extracted_at: str,
) -> None:
    write_jsonl_row(
        handle,
        {
            "evidence_id": evidence_id,
            "record_type": record_type,
            "repo_path": repo_path,
            "subject_id": subject_id,
            "origin_type": origin_type,
            "source_path": source_path,
            "summary": summary,
            "extracted_at": extracted_at,
        },
    )


def diff_name_status(root: Path, repo: str, commit_hash: str) -> tuple[dict[str, str], dict[str, str]]:
    status_by_path: dict[str, str] = {}
    old_path_by_path: dict[str, str] = {}
    cp = run_git(root, repo, ["diff-tree", "--no-commit-id", "--root", "-r", "--name-status", "--find-renames", commit_hash])
    for line in cp.stdout.splitlines():
        parts = line.split("\t")
        if len(parts) >= 3 and (parts[0].startswith("R") or parts[0].startswith("C")):
            status_by_path[parts[-1]] = parts[0]
            old_path_by_path[parts[-1]] = parts[1]
        elif len(parts) >= 2:
            status_by_path[parts[1]] = parts[0]
    return status_by_path, old_path_by_path


def diff_numstat(root: Path, repo: str, commit_hash: str) -> list[tuple[str, str, str]]:
    rows: list[tuple[str, str, str]] = []
    cp = run_git(root, repo, ["diff-tree", "--no-commit-id", "--root", "-r", "--numstat", "--find-renames", commit_hash])
    for line in cp.stdout.splitlines():
        parts = line.split("\t")
        if len(parts) < 3:
            continue
        rows.append((parts[0], parts[1], parts[-1]))
    return rows


def binary_asset_row(
    *,
    evidence_id: str,
    repo: dict[str, str],
    origin_type: str,
    source_kind: str,
    commit_hash: str,
    file_path: str,
    change_type: str,
    size_bytes: str,
    sha256: str,
    evidence_source: str,
    analysis_note: str,
) -> dict[str, Any]:
    repo_path = repo.get("repo_path", "")
    full_path = workspace_path(repo_path, file_path)
    return {
        "evidence_id": evidence_id,
        "record_id": evidence_id,
        "repo_path": repo_path,
        "repo_name": repo.get("repo_name", ""),
        "classification": repo.get("classification", ""),
        "origin_type": origin_type,
        "source_kind": source_kind,
        "commit_hash": commit_hash,
        "commit": commit_hash,
        "path": full_path,
        "file_path": file_path,
        "change_type": change_type,
        "change_status": change_type,
        "file_type": path_kind(file_path),
        "size": size_bytes,
        "size_bytes": size_bytes,
        "sha256": sha256,
        "architecture": guess_arch(full_path),
        "possible_usage": guess_possible_usage(full_path),
        "source_commit": commit_hash,
        "introduced_by": f"{source_kind}:{commit_hash}" if commit_hash else source_kind,
        "license_risk": "unknown",
        "redistribution_risk": "unknown",
        "runtime_dependency": "unknown",
        "evidence_source": evidence_source,
        "analysis_note": analysis_note,
    }


def extract_commit_records(
    *,
    root: Path,
    out: Path,
    repos: list[dict[str, str]],
    revs: dict[str, dict[str, str]],
    commit_handle: Any,
    file_handle: Any,
    evidence_handle: Any,
    binary_rows: list[dict[str, Any]],
    extracted_at: str,
) -> dict[str, int]:
    counts = defaultdict(int)
    diffs = out / "01_raw_records/diffs"
    for repo in repos:
        repo_path = repo.get("repo_path", "")
        if not repo_path or not (root / repo_path / ".git").exists():
            continue
        rev_row = revs.get(repo_path, {})
        baseline_status = repo.get("baseline_status") or rev_row.get("baseline_status") or ""
        baseline_revision = repo.get("baseline_revision") or rev_row.get("baseline_revision") or ""
        merge_base_revision = repo.get("merge_base_revision") or rev_row.get("merge_base_revision") or ""
        range_limited = False
        if baseline_revision and merge_base_revision:
            rev_cp = run_git(root, repo_path, ["rev-list", "--reverse", f"{merge_base_revision}..HEAD"])
            range_limited = rev_cp.returncode == 0
        else:
            rev_cp = run_git(root, repo_path, ["rev-list", "--reverse", "HEAD"])
        if rev_cp.returncode != 0:
            log(f"skip commit scan for {repo_path}: {rev_cp.stderr.strip()[:200]}")
            continue
        revisions = [line.strip() for line in rev_cp.stdout.splitlines() if line.strip()]
        if not revisions:
            continue
        root_cp = run_git(root, repo_path, ["rev-list", "--max-parents=0", "HEAD"])
        root_revisions = [line.strip() for line in root_cp.stdout.splitlines() if line.strip()]
        root_revision = root_revisions[0] if root_revisions else revisions[0]
        for commit_hash in revisions:
            meta_cp = run_git(
                root,
                repo_path,
                ["show", "-s", "--format=%H%x1f%P%x1f%an%x1f%ae%x1f%aI%x1f%cn%x1f%ce%x1f%cI%x1f%s", commit_hash],
            )
            meta = meta_cp.stdout.rstrip("\n").split("\x1f")
            meta += [""] * (9 - len(meta))
            parents = [p for p in meta[1].split() if p]
            is_initial = commit_hash == root_revision or not parents
            is_merge = len(parents) > 1
            if is_initial:
                origin_type = "initial_import"
            elif is_merge:
                origin_type = "merge_commit"
            elif range_limited:
                origin_type = "downstream_unique"
            elif baseline_status in {"downstream_only", "initial_import"}:
                origin_type = "post_import_change"
            elif baseline_status == "baseline_unknown" or not baseline_revision:
                origin_type = "baseline_unknown"
            else:
                origin_type = "post_import_change"

            diff_path = ""
            file_rows: list[dict[str, Any]] = []
            insertions = deletions = 0
            if not is_initial and not is_merge:
                patch_path = diffs / f"commit__{safe_name(repo_path)}__{commit_hash[:12]}.patch"
                patch_cp = run_git_to_file(
                    root,
                    repo_path,
                    ["show", "--binary", "--find-renames", "--format=fuller", commit_hash],
                    patch_path,
                )
                if patch_cp.returncode != 0:
                    log(f"git show failed for {repo_path}:{commit_hash}: {patch_cp.stderr.strip()[:200]}")
                diff_path = str(patch_path.relative_to(out))
                counts["diffs"] += 1
                status_by_path, old_path_by_path = diff_name_status(root, repo_path, commit_hash)
                numstat_rows = diff_numstat(root, repo_path, commit_hash)
                skip_blob_info = len(numstat_rows) > MAX_BLOB_INFO_FILES_PER_COMMIT
                if skip_blob_info:
                    log(
                        "skip per-blob sha for large commit "
                        f"{repo_path}:{commit_hash[:12]} files={len(numstat_rows)}"
                    )
                for added, deleted, file_path in numstat_rows:
                    change_type = status_by_path.get(file_path, "")
                    old_path = old_path_by_path.get(file_path, "")
                    numstat_binary = added == "-" or deleted == "-"
                    size_bytes = ""
                    sha256 = ""
                    nul_detected = False
                    if not skip_blob_info and not change_type.startswith("D"):
                        size_bytes, sha256, nul_detected = git_blob_info(root, repo_path, commit_hash, file_path)
                    is_binary = is_binary_or_prebuilt(file_path, numstat_binary=numstat_binary, nul_detected=nul_detected)
                    add_count = 0 if numstat_binary else int_or_zero(added)
                    del_count = 0 if numstat_binary else int_or_zero(deleted)
                    insertions += add_count
                    deletions += del_count
                    evidence_id = f"file_change:{repo_path}:{commit_hash}:{file_path}"
                    row = {
                        "evidence_id": evidence_id,
                        "record_id": evidence_id,
                        "record_type": "file_change",
                        "commit_evidence_id": f"commit:{repo_path}:{commit_hash}",
                        "repo_path": repo_path,
                        "repo_name": repo.get("repo_name", ""),
                        "classification": repo.get("classification", ""),
                        "commit_hash": commit_hash,
                        "commit": commit_hash,
                        "origin_type": origin_type,
                        "change_type": change_type,
                        "change_status": change_type,
                        "path": file_path,
                        "file_path": file_path,
                        "workspace_path": workspace_path(repo_path, file_path),
                        "old_path": old_path,
                        "insertions": add_count,
                        "deletions": del_count,
                        "additions": add_count,
                        "is_binary_or_prebuilt": is_binary,
                        "blob_size": size_bytes,
                        "blob_sha256": sha256,
                        "diff_path": diff_path,
                        "extracted_at": extracted_at,
                    }
                    file_rows.append(row)
                    if is_binary:
                        binary_rows.append(
                            binary_asset_row(
                                evidence_id=f"binary_asset:{repo_path}:{commit_hash}:{file_path}",
                                repo=repo,
                                origin_type=origin_type,
                                source_kind="committed",
                                commit_hash=commit_hash,
                                file_path=file_path,
                                change_type=change_type,
                                size_bytes=size_bytes,
                                sha256=sha256,
                                evidence_source=diff_path,
                                analysis_note=f"classification={repo.get('classification', '')}; source=commit_diff",
                            )
                        )

            changed_files_count = len(file_rows)
            evidence_id = f"commit:{repo_path}:{commit_hash}"
            commit_row = {
                "evidence_id": evidence_id,
                "record_id": evidence_id,
                "record_type": "commit",
                "repo_path": repo_path,
                "repo_name": repo.get("repo_name", ""),
                "classification": repo.get("classification", ""),
                "commit_hash": commit_hash,
                "commit": commit_hash,
                "parents": parents,
                "is_initial": is_initial,
                "is_merge": is_merge,
                "origin_type": origin_type,
                "commit_origin_type": origin_type,
                "baseline_status": baseline_status,
                "baseline_revision": baseline_revision,
                "merge_base_revision": merge_base_revision,
                "current_branch": repo.get("current_branch", ""),
                "author_name": meta[2],
                "author_email": meta[3],
                "author_date": meta[4],
                "committer_name": meta[5],
                "committer_email": meta[6],
                "committer_date": meta[7],
                "subject": meta[8],
                "changed_files_count": changed_files_count,
                "files_changed": changed_files_count,
                "insertions": insertions,
                "deletions": deletions,
                "diff_path": diff_path,
                "extracted_at": extracted_at,
            }
            write_jsonl_row(commit_handle, commit_row)
            counts["commits"] += 1
            emit_evidence(
                evidence_handle,
                evidence_id=evidence_id,
                record_type="commit",
                repo_path=repo_path,
                subject_id=commit_hash,
                origin_type=origin_type,
                source_path=diff_path or "git log",
                summary=meta[8],
                extracted_at=extracted_at,
            )
            counts["evidence"] += 1
            for row in file_rows:
                write_jsonl_row(file_handle, row)
                counts["file_changes"] += 1
                emit_evidence(
                    evidence_handle,
                    evidence_id=row["evidence_id"],
                    record_type="file_change",
                    repo_path=repo_path,
                    subject_id=f"{commit_hash}:{row['path']}",
                    origin_type=origin_type,
                    source_path=diff_path,
                    summary=f"{row['change_type']} {row['path']}".strip(),
                    extracted_at=extracted_at,
                )
                counts["evidence"] += 1
    return dict(counts)


def extract_dirty_records(
    *,
    root: Path,
    out: Path,
    repos: list[dict[str, str]],
    dirty_handle: Any,
    evidence_handle: Any,
    binary_rows: list[dict[str, Any]],
    untracked_rows: list[dict[str, Any]],
    dirty_repo_rows: list[dict[str, Any]],
    extracted_at: str,
) -> dict[str, int]:
    counts = defaultdict(int)
    diffs = out / "01_raw_records/diffs"
    for repo in repos:
        repo_path = repo.get("repo_path", "")
        if not repo_path or not (root / repo_path / ".git").exists():
            continue
        status_cp = run_git(root, repo_path, ["status", "--porcelain=v1", "--untracked-files=normal"])
        if status_cp.returncode != 0:
            log(f"skip dirty scan for {repo_path}: {status_cp.stderr.strip()[:200]}")
            continue
        status_lines = [line for line in status_cp.stdout.splitlines() if line]
        if not status_lines:
            continue
        modified_lines = [line for line in status_lines if not line.startswith("??")]
        untracked_lines = [line for line in status_lines if line.startswith("??")]
        diff_path = ""
        if modified_lines:
            patch_path = diffs / f"dirty__{safe_name(repo_path)}.patch"
            diff_cp = run_git_to_file(root, repo_path, ["diff", "--binary"], patch_path)
            if diff_cp.returncode != 0:
                log(f"git diff failed for dirty repo {repo_path}: {diff_cp.stderr.strip()[:200]}")
            diff_path = str(patch_path.relative_to(out))
            counts["diffs"] += 1
        dirty_repo_id = f"dirty_repo:{repo_path}"
        dirty_repo_row = {
            "evidence_id": dirty_repo_id,
            "record_id": dirty_repo_id,
            "repo_path": repo_path,
            "repo_name": repo.get("repo_name", ""),
            "classification": repo.get("classification", ""),
            "head_revision": repo.get("current_revision", ""),
            "current_branch": repo.get("current_branch", ""),
            "origin_type": "dirty_workspace",
            "tracked_dirty_count": len(modified_lines),
            "modified_file_count": len(modified_lines),
            "untracked_file_count": len(untracked_lines),
            "diff_path": diff_path,
            "extracted_at": extracted_at,
        }
        dirty_repo_rows.append(dirty_repo_row)
        counts["dirty_repos"] += 1
        emit_evidence(
            evidence_handle,
            evidence_id=dirty_repo_id,
            record_type="dirty_repo",
            repo_path=repo_path,
            subject_id=repo.get("current_revision", ""),
            origin_type="dirty_workspace",
            source_path=diff_path or "git status --porcelain --untracked-files=normal",
            summary=f"{len(modified_lines)} modified, {len(untracked_lines)} untracked",
            extracted_at=extracted_at,
        )
        counts["evidence"] += 1
        for line in status_lines:
            xy_status = line[:2]
            file_path = line[3:]
            old_path = ""
            if " -> " in file_path:
                old_path, file_path = file_path.split(" -> ", 1)
            file_path = file_path.rstrip("/")
            absolute_path = root / repo_path / file_path
            if absolute_path.is_dir() or line[3:].endswith("/"):
                local_path_type = "directory"
            elif absolute_path.is_file():
                local_path_type = "file"
            else:
                local_path_type = "missing"
            size_bytes = ""
            sha256 = ""
            if local_path_type == "file":
                size_bytes, sha256 = local_file_info(absolute_path)
            is_binary = is_binary_or_prebuilt(file_path)
            evidence_id = f"dirty_file:{repo_path}:{file_path}"
            row = {
                "evidence_id": evidence_id,
                "record_id": evidence_id,
                "record_type": "dirty_file",
                "dirty_repo_evidence_id": dirty_repo_id,
                "repo_path": repo_path,
                "repo_name": repo.get("repo_name", ""),
                "classification": repo.get("classification", ""),
                "head_revision": repo.get("current_revision", ""),
                "origin_type": "dirty_workspace",
                "xy_status": xy_status,
                "change_type": xy_status.strip() or "modified",
                "path": file_path,
                "file_path": file_path,
                "workspace_path": workspace_path(repo_path, file_path),
                "old_path": old_path,
                "path_type": local_path_type,
                "size_bytes": size_bytes,
                "sha256": sha256,
                "is_binary_or_prebuilt": is_binary,
                "dirty_content_class": path_kind(file_path),
                "diff_path": "" if xy_status == "??" else diff_path,
                "extracted_at": extracted_at,
            }
            write_jsonl_row(dirty_handle, row)
            counts["dirty_files"] += 1
            emit_evidence(
                evidence_handle,
                evidence_id=evidence_id,
                record_type="dirty_file",
                repo_path=repo_path,
                subject_id=file_path,
                origin_type="dirty_workspace",
                source_path=row["diff_path"] or "git status --porcelain --untracked-files=normal",
                summary=f"{xy_status} {file_path}".strip(),
                extracted_at=extracted_at,
            )
            counts["evidence"] += 1
            if xy_status == "??":
                untracked_id = f"untracked:{repo_path}:{file_path}"
                untracked_rows.append(
                    {
                        "evidence_id": untracked_id,
                        "record_id": untracked_id,
                        "repo_path": repo_path,
                        "repo_name": repo.get("repo_name", ""),
                        "classification": repo.get("classification", ""),
                        "head_revision": repo.get("current_revision", ""),
                        "origin_type": "dirty_workspace",
                        "path": file_path,
                        "file_path": file_path,
                        "workspace_path": workspace_path(repo_path, file_path),
                        "path_type": local_path_type,
                        "size_bytes": size_bytes,
                        "sha256": sha256,
                        "is_binary_or_prebuilt": is_binary,
                        "evidence_source": "git status --porcelain --untracked-files=normal",
                    }
                )
                counts["untracked"] += 1
            if is_binary:
                binary_rows.append(
                    binary_asset_row(
                        evidence_id=f"binary_asset:dirty:{repo_path}:{file_path}",
                        repo=repo,
                        origin_type="dirty_workspace",
                        source_kind="dirty_workspace",
                        commit_hash=repo.get("current_revision", ""),
                        file_path=file_path,
                        change_type=xy_status,
                        size_bytes=size_bytes,
                        sha256=sha256,
                        evidence_source=row["diff_path"] or "git status --porcelain --untracked-files=normal",
                        analysis_note=f"classification={repo.get('classification', '')}; source=dirty_workspace",
                    )
                )
    return dict(counts)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True)
    parser.add_argument("--stage-result")
    args = parser.parse_args()

    out = Path(args.out).resolve()
    root = out.parent.resolve()
    raw = out / "01_raw_records"
    semantic = out / "03_semantic_analysis"
    diffs = raw / "diffs"
    raw.mkdir(parents=True, exist_ok=True)
    semantic.mkdir(parents=True, exist_ok=True)
    if diffs.exists():
        shutil.rmtree(diffs)
    diffs.mkdir(parents=True, exist_ok=True)

    missing_inputs = [rel for rel in INPUT_FILES if not (out / rel).exists()]
    if missing_inputs:
        raise SystemExit(f"missing required inputs: {missing_inputs}")

    repos = read_csv(out / "01_raw_records/repo_list.csv")
    revs = {row.get("repo_path", ""): row for row in read_csv(out / "00_config/repo_revision_map.csv") if row.get("repo_path")}
    extracted_at = datetime.now(timezone.utc).isoformat()
    binary_rows: list[dict[str, Any]] = []
    dirty_repo_rows: list[dict[str, Any]] = []
    untracked_rows: list[dict[str, Any]] = []

    log(f"workspace={root}")
    log(f"output={out}")
    log(f"repos={len(repos)}")
    log("dirty scan mode=--untracked-files=normal")

    with (raw / "commit_records.jsonl").open("w", encoding="utf-8") as commit_handle, (
        raw / "file_change_records.jsonl"
    ).open("w", encoding="utf-8") as file_handle, (raw / "dirty_file_records.jsonl").open(
        "w", encoding="utf-8"
    ) as dirty_handle, (semantic / "evidence_index.jsonl").open("w", encoding="utf-8") as evidence_handle:
        commit_counts = extract_commit_records(
            root=root,
            out=out,
            repos=repos,
            revs=revs,
            commit_handle=commit_handle,
            file_handle=file_handle,
            evidence_handle=evidence_handle,
            binary_rows=binary_rows,
            extracted_at=extracted_at,
        )
        dirty_counts = extract_dirty_records(
            root=root,
            out=out,
            repos=repos,
            dirty_handle=dirty_handle,
            evidence_handle=evidence_handle,
            binary_rows=binary_rows,
            untracked_rows=untracked_rows,
            dirty_repo_rows=dirty_repo_rows,
            extracted_at=extracted_at,
        )

    binary_fields = [
        "evidence_id",
        "record_id",
        "repo_path",
        "repo_name",
        "classification",
        "origin_type",
        "source_kind",
        "commit_hash",
        "commit",
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
        "source_commit",
        "introduced_by",
        "license_risk",
        "redistribution_risk",
        "runtime_dependency",
        "evidence_source",
        "analysis_note",
    ]
    dirty_repo_fields = [
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
    ]
    untracked_fields = [
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
        "size_bytes",
        "sha256",
        "is_binary_or_prebuilt",
        "evidence_source",
    ]
    write_csv(raw / "binary_asset_records.csv", binary_fields, binary_rows)
    write_csv(raw / "dirty_repo_records.csv", dirty_repo_fields, dirty_repo_rows)
    write_csv(raw / "untracked_file_records.csv", untracked_fields, untracked_rows)

    counts = defaultdict(int)
    for source in (commit_counts, dirty_counts):
        for key, value in source.items():
            counts[key] += value
    counts["binary_assets"] = len(binary_rows)
    counts["dirty_repos"] = len(dirty_repo_rows)
    counts["untracked"] = len(untracked_rows)

    print(json.dumps(dict(sorted(counts.items())), ensure_ascii=False, indent=2))

    result = {
        "stage": "02_raw_record_extractor",
        "status": "passed",
        "summary": (
            "Deterministic raw extraction completed with "
            f"{counts['commits']} commits, {counts['file_changes']} file changes, "
            f"{counts['binary_assets']} binary/prebuilt records, {counts['dirty_files']} dirty file records, "
            f"and {counts['untracked']} bounded untracked entries."
        ),
        "input_files_read": [f"porting_knowledge_output/{rel}" for rel in INPUT_FILES],
        "output_files_written": [f"porting_knowledge_output/{rel}" for rel in OUTPUT_FILES],
        "blocking_issues": [],
        "non_blocking_issues": [
            "Untracked directories are intentionally recorded as directory entries instead of recursively expanding large SDK/prebuilt trees."
        ],
        "next_stage_inputs": [
            "porting_knowledge_output/01_raw_records/commit_records.jsonl",
            "porting_knowledge_output/01_raw_records/file_change_records.jsonl",
            "porting_knowledge_output/01_raw_records/binary_asset_records.csv",
            "porting_knowledge_output/01_raw_records/dirty_repo_records.csv",
            "porting_knowledge_output/01_raw_records/dirty_file_records.jsonl",
            "porting_knowledge_output/01_raw_records/untracked_file_records.csv",
            "porting_knowledge_output/03_semantic_analysis/evidence_index.jsonl",
        ],
    }
    if args.stage_result:
        Path(args.stage_result).write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
