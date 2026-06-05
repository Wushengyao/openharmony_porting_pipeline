#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
from datetime import datetime
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any
import xml.etree.ElementTree as ET


DEFAULT_FOCUS_PATHS = [
    "productdefine",
    "vendor",
    "device",
    "kernel",
    "drivers",
    "build",
    "base",
    "foundation",
    "third_party",
    "arkcompiler",
    "arkui",
    "developtools",
    "graphic",
    "multimedia",
    "communication",
    "resourceschedule",
    "request",
    "web",
    "commonlibrary",
    "utils",
]

IGNORE_NAMES = {
    ".git",
    ".repo",
    ".ccache",
    "__pycache__",
    "out",
    "tmp",
    "temp",
    ".idea",
    ".vscode",
}

BINARY_EXTS = {
    ".a",
    ".bin",
    ".bmp",
    ".dat",
    ".elf",
    ".hap",
    ".hcd",
    ".img",
    ".jar",
    ".ko",
    ".o",
    ".png",
    ".so",
    ".zip",
}


def now() -> str:
    return datetime.now().astimezone().strftime("%Y-%m-%dT%H:%M:%S%z")


def log(level: str, msg: str) -> None:
    print(f"[{now()}] [{level}] {msg}", file=sys.stderr)


def normalize_rel(path: str) -> str:
    return path.replace("\\", "/").strip("/")


def rel_from_any(raw: str, roots: list[Path]) -> str:
    raw = raw.strip().strip('"')
    raw_path = Path(raw)
    candidates = []
    if raw_path.is_absolute():
        candidates.append(raw_path)
    else:
        candidates.append(Path.cwd() / raw_path)
    raw_norm = normalize_rel(raw)
    for root in roots:
        root_text = normalize_rel(str(root))
        if raw_norm == root_text:
            return "."
        if raw_norm.startswith(root_text + "/"):
            return raw_norm[len(root_text) + 1 :]
    for candidate in candidates:
        for root in roots:
            try:
                return normalize_rel(str(candidate.resolve().relative_to(root.resolve())))
            except Exception:
                continue
    # git diff --no-index may print the argument path exactly. Strip the first
    # existing focus prefix if the absolute-root normalization did not match.
    parts = raw_norm.split("/")
    for focus in DEFAULT_FOCUS_PATHS:
        focus_parts = focus.split("/")
        for idx in range(0, len(parts) - len(focus_parts) + 1):
            if parts[idx : idx + len(focus_parts)] == focus_parts:
                return "/".join(parts[idx:])
    return raw_norm


def classify_path(path: str) -> str:
    p = normalize_rel(path)
    if p.startswith("productdefine/"):
        return "product_config"
    if p.startswith("vendor/"):
        if any(token in p.lower() for token in ["/firmware", "/prebuilt", "/boot", "/uboot", "/u-boot"]):
            return "vendor_binary_dependency"
        return "vendor_product_config"
    if p.startswith("device/board/"):
        if any(token in p.lower() for token in ["firmware", "boot", ".hcd", ".bin", ".img", ".ko"]):
            return "board_external_dependency"
        return "board_config"
    if p.startswith("device/soc/"):
        if any(token in p.lower() for token in ["firmware", "prebuilt", ".so", ".bin", ".ko"]):
            return "soc_external_dependency"
        return "soc_config"
    if p.startswith("kernel/"):
        return "kernel_bsp"
    if p.startswith("drivers/") or "/hdf/" in p.lower() or p.endswith(".hcs"):
        return "hdf_driver"
    if p.startswith("build/"):
        return "build_system"
    if p.startswith("arkcompiler/"):
        return "arkcompiler_runtime"
    if p.startswith("arkui/") or "ace_engine" in p:
        return "arkui_runtime"
    if p.startswith("web/"):
        return "webview"
    if p.startswith("graphic/"):
        return "graphics"
    if p.startswith("multimedia/"):
        return "multimedia"
    if p.startswith("communication/"):
        return "communication"
    if p.startswith("resourceschedule/"):
        return "resourceschedule"
    if p.startswith("request/"):
        return "request"
    if p.startswith("third_party/"):
        return "third_party"
    return "source_or_config"


def is_binary_like(path: str) -> bool:
    p = Path(path.lower())
    return p.suffix in BINARY_EXTS or any(token in normalize_rel(path).lower() for token in ["/prebuilt", "/firmware", "/bootloader"])


def phase_for_category(category: str) -> str:
    if category in {"product_config"}:
        return "L0_target_identity"
    if category in {"vendor_product_config", "board_config", "soc_config", "build_system"}:
        return "L1_base_binding"
    if category in {"kernel_bsp", "board_external_dependency", "soc_external_dependency", "vendor_binary_dependency"}:
        return "L5_external_dependency_closure"
    if category in {"hdf_driver"}:
        return "L3_runtime_hdf_config"
    if category in {"arkcompiler_runtime", "arkui_runtime", "webview", "graphics", "multimedia", "communication", "resourceschedule", "request", "third_party"}:
        return "L2_build_triage"
    return "L4_feature_driver_source"


def run_git_diff(left: Path, right: Path) -> tuple[int, str, str]:
    cmd = [
        "git",
        "diff",
        "--no-index",
        "--name-status",
        "--no-renames",
        "--",
        str(left),
        str(right),
    ]
    proc = subprocess.run(cmd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    return proc.returncode, proc.stdout, proc.stderr


def walk_added_or_deleted(root: Path, focus_rel: str, status: str, max_records: int) -> list[dict[str, Any]]:
    base = root / focus_rel
    if not base.exists():
        return []
    records: list[dict[str, Any]] = []
    if base.is_file():
        rel = focus_rel
        records.append(make_record(rel, status))
        return records
    for dirpath, dirnames, filenames in os.walk(base):
        dirnames[:] = [d for d in dirnames if d not in IGNORE_NAMES]
        for filename in filenames:
            if len(records) >= max_records:
                return records
            path = Path(dirpath) / filename
            try:
                rel = normalize_rel(str(path.relative_to(root)))
            except Exception:
                rel = normalize_rel(str(path))
            records.append(make_record(rel, status))
    return records


def make_record(path: str, status: str) -> dict[str, Any]:
    category = classify_path(path)
    return {
        "path": normalize_rel(path),
        "status": status,
        "category": category,
        "phase": phase_for_category(category),
        "binary_like": is_binary_like(path),
    }


def is_hex_revision(value: str | None) -> bool:
    if not value or len(value) < 12:
        return False
    return all(char in "0123456789abcdefABCDEF" for char in value[:12])


def load_manifest_projects(manifest: Path) -> list[dict[str, str]]:
    tree = ET.parse(manifest)
    projects: list[dict[str, str]] = []
    for elem in tree.getroot().iter("project"):
        path = elem.get("path") or elem.get("name") or ""
        revision = elem.get("revision") or ""
        name = elem.get("name") or path
        if path and is_hex_revision(revision):
            projects.append({"path": normalize_rel(path), "name": name, "revision": revision})
    projects.sort(key=lambda item: item["path"])
    return projects


def discover_old_baseline_manifest(old_ported: Path) -> tuple[Path | None, list[str]]:
    warnings: list[str] = []
    tag_dir = old_ported / ".repo/manifests/tag"
    candidates: list[tuple[int, float, Path]] = []
    if tag_dir.is_dir():
        for path in tag_dir.glob("*.xml"):
            try:
                count = len(load_manifest_projects(path))
            except Exception as exc:
                warnings.append(f"could not parse candidate locked manifest {path}: {exc}")
                continue
            candidates.append((count, path.stat().st_mtime, path))
    if candidates:
        candidates.sort(key=lambda item: (item[0], item[1], item[2].name), reverse=True)
        count, _, path = candidates[0]
        if count > 0:
            return path, warnings
    for rel in [".repo/manifests/default.xml", ".repo/manifest.xml"]:
        path = old_ported / rel
        if not path.is_file():
            continue
        try:
            count = len(load_manifest_projects(path))
        except Exception as exc:
            warnings.append(f"could not parse fallback manifest {path}: {exc}")
            continue
        if count > 0:
            warnings.append(
                f"using fallback manifest {path}; prefer a locked .repo/manifests/tag/*.xml with concrete project revisions"
            )
            return path, warnings
    warnings.append("no locked old baseline manifest was found under old_ported/.repo/manifests/tag")
    return None, warnings


def path_matches_focus(path: str, focus_paths: list[str]) -> bool:
    p = normalize_rel(path)
    return any(p == focus or p.startswith(focus + "/") or focus.startswith(p + "/") for focus in focus_paths)


def run_git(repo: Path, args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", "-C", str(repo), *args], text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)


def manifest_remote_info(old_ported: Path) -> dict[str, str]:
    manifests = old_ported / ".repo/manifests"
    info = {"remote_url": "unknown", "branch": "unknown", "head": "unknown"}
    if not (manifests / ".git").exists():
        return info
    remote = run_git(manifests, ["remote", "get-url", "origin"])
    branch = run_git(manifests, ["branch", "--show-current"])
    head = run_git(manifests, ["rev-parse", "HEAD"])
    if remote.returncode == 0 and remote.stdout.strip():
        info["remote_url"] = remote.stdout.strip()
    if branch.returncode == 0 and branch.stdout.strip():
        info["branch"] = branch.stdout.strip()
    if head.returncode == 0 and head.stdout.strip():
        info["head"] = head.stdout.strip()
    return info


def parse_repo_name_status(stdout: str, repo_path: str, extra: dict[str, Any]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for line in stdout.splitlines():
        if not line.strip():
            continue
        cols = line.split("\t")
        if len(cols) < 2:
            continue
        status = cols[0].strip()
        rel = normalize_rel(cols[-1])
        full = normalize_rel(f"{repo_path}/{rel}")
        record = make_record(full, status)
        record.update(extra)
        records.append(record)
    return records


def diff_old_ported_from_manifest(
    old_ported: Path,
    manifest: Path,
    focus_paths: list[str],
    max_records: int,
) -> tuple[list[dict[str, Any]], list[str], dict[str, Any]]:
    warnings: list[str] = []
    projects = load_manifest_projects(manifest)
    remaining = max_records
    records: list[dict[str, Any]] = []
    stats = {
        "manifest_path": str(manifest),
        "project_count": len(projects),
        "matching_focus_project_count": 0,
        "same_head_count": 0,
        "ahead_repo_count": 0,
        "ahead_commit_count": 0,
        "missing_checkout_count": 0,
        "missing_revision_count": 0,
        "not_ancestor_count": 0,
    }
    for project in projects:
        repo_path = project["path"]
        if not path_matches_focus(repo_path, focus_paths):
            continue
        stats["matching_focus_project_count"] += 1
        repo = old_ported / repo_path
        revision = project["revision"]
        if not (repo / ".git").exists():
            stats["missing_checkout_count"] += 1
            warnings.append(f"manifest project missing checkout: {repo_path}")
            continue
        head_proc = run_git(repo, ["rev-parse", "HEAD"])
        if head_proc.returncode != 0 or not head_proc.stdout.strip():
            warnings.append(f"could not read HEAD for {repo_path}: {head_proc.stderr.strip()[:200]}")
            continue
        head = head_proc.stdout.strip()
        if head == revision:
            stats["same_head_count"] += 1
            continue
        exists = run_git(repo, ["cat-file", "-e", f"{revision}^{{commit}}"])
        if exists.returncode != 0:
            stats["missing_revision_count"] += 1
            warnings.append(f"manifest revision not present in checkout for {repo_path}: {revision[:12]}")
            continue
        ancestor = run_git(repo, ["merge-base", "--is-ancestor", revision, "HEAD"])
        if ancestor.returncode != 0:
            stats["not_ancestor_count"] += 1
            warnings.append(f"manifest revision is not an ancestor of HEAD for {repo_path}: {revision[:12]}..{head[:12]}")
            continue
        count_proc = run_git(repo, ["rev-list", "--count", f"{revision}..HEAD"])
        commit_count = int((count_proc.stdout.strip() or "0")) if count_proc.returncode == 0 else 0
        diff_proc = run_git(repo, ["diff", "--name-status", "--no-renames", f"{revision}..HEAD", "--"])
        if diff_proc.returncode not in (0, 1):
            warnings.append(f"git diff failed for {repo_path}: {diff_proc.stderr.strip()[:240]}")
            continue
        stats["ahead_repo_count"] += 1
        stats["ahead_commit_count"] += commit_count
        extra = {
            "repo_path": repo_path,
            "baseline_revision": revision[:12],
            "head_revision": head[:12],
            "commit_count": commit_count,
            "content_source": "old_ported_baseline_manifest",
        }
        found = [record for record in parse_repo_name_status(diff_proc.stdout, repo_path, extra) if path_matches_focus(record["path"], focus_paths)]
        if len(found) > remaining:
            warnings.append(f"record limit truncated {repo_path}: kept {remaining} of {len(found)} records")
            found = found[:remaining]
        records.extend(found)
        remaining -= len(found)
        if remaining <= 0:
            warnings.append(f"record limit reached while scanning {repo_path}")
            break
    records.sort(key=lambda item: item["path"])
    return records, warnings, stats


def parse_name_status(stdout: str, left_root: Path, right_root: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for line in stdout.splitlines():
        if not line.strip():
            continue
        cols = line.split("\t")
        if len(cols) < 2:
            continue
        status = cols[0].strip()
        raw_path = cols[-1]
        rel = rel_from_any(raw_path, [left_root, right_root])
        records.append(make_record(rel, status))
    return records


def diff_focus(left_root: Path, right_root: Path, focus_paths: list[str], max_records: int) -> tuple[list[dict[str, Any]], list[str]]:
    records: list[dict[str, Any]] = []
    warnings: list[str] = []
    remaining = max_records
    for focus in focus_paths:
        if remaining <= 0:
            warnings.append(f"record limit reached at focus path {focus}")
            break
        left = left_root / focus
        right = right_root / focus
        if not left.exists() and not right.exists():
            continue
        if left.exists() and not right.exists():
            found = walk_added_or_deleted(left_root, focus, "D", remaining)
            records.extend(found)
            remaining -= len(found)
            continue
        if right.exists() and not left.exists():
            found = walk_added_or_deleted(right_root, focus, "A", remaining)
            records.extend(found)
            remaining -= len(found)
            continue
        rc, stdout, stderr = run_git_diff(left, right)
        if rc not in (0, 1):
            warnings.append(f"git diff --no-index failed for {focus}: exit={rc}: {stderr.strip()[:300]}")
            continue
        found = parse_name_status(stdout, left_root, right_root)
        if len(found) > remaining:
            warnings.append(f"record limit truncated {focus}: kept {remaining} of {len(found)} records")
            found = found[:remaining]
        records.extend(found)
        remaining -= len(found)
    records.sort(key=lambda item: item["path"])
    return records, warnings


def index_by_path(records: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    indexed: dict[str, dict[str, Any]] = {}
    for record in records:
        indexed.setdefault(record["path"], record)
    return indexed


def migration_decision(record: dict[str, Any], new_original: Path, upstream: dict[str, dict[str, Any]], workspace_delta: dict[str, dict[str, Any]]) -> tuple[str, str, str]:
    path = record["path"]
    category = record["category"]
    new_exists = (new_original / path).exists()
    if record.get("binary_like") or category in {"kernel_bsp", "board_external_dependency", "soc_external_dependency", "vendor_binary_dependency"}:
        return "route_to_external_dependency_followup", "external_dependency", "binary/BSP/firmware/prebuilt changes require provenance and cannot be treated as source fixes"
    if not new_exists:
        return "manual_retarget_required", "high", "old porting path is absent in the new version tree"
    if path in upstream:
        return "merge_required", "high", "same path changed between old and new OpenHarmony baselines"
    if path in workspace_delta:
        return "already_in_progress_review", "medium", "new workspace already differs from the new original baseline"
    return "direct_review_candidate", "medium", "path exists in new baseline and has no same-path upstream delta in the bounded scan"


def build_conflict_matrix(
    old_delta: list[dict[str, Any]],
    upstream_delta: list[dict[str, Any]],
    workspace_delta: list[dict[str, Any]],
    new_original: Path,
) -> list[dict[str, Any]]:
    upstream = index_by_path(upstream_delta)
    workspace = index_by_path(workspace_delta)
    matrix: list[dict[str, Any]] = []
    for idx, record in enumerate(old_delta, start=1):
        decision, risk, reason = migration_decision(record, new_original, upstream, workspace)
        path = record["path"]
        matrix.append(
            {
                "item_id": f"UPG-{idx:05d}",
                "path": path,
                "old_porting_status": record["status"],
                "category": record["category"],
                "phase": record["phase"],
                "new_original_path_status": "present" if (new_original / path).exists() else "missing",
                "upstream_upgrade_status": upstream.get(path, {}).get("status", "not_touched_same_path"),
                "new_workspace_status": workspace.get(path, {}).get("status", "matches_new_original_or_not_scanned"),
                "migration_decision": decision,
                "risk_level": risk,
                "reason": reason,
                "evidence_refs": [
                    f"old_porting_delta:{path}",
                    f"new_original:{path}",
                ],
            }
        )
    return matrix


def count_by(items: list[dict[str, Any]], key: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in items:
        value = str(item.get(key, "unknown"))
        counts[value] = counts.get(value, 0) + 1
    return dict(sorted(counts.items()))


def json_yaml(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, indent=2) + "\n"


def write_text(path: Path, text: str, outputs: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    outputs.append(str(path))


def write_csv(path: Path, rows: list[dict[str, Any]], outputs: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "path",
        "status",
        "category",
        "phase",
        "binary_like",
        "repo_path",
        "baseline_revision",
        "head_revision",
        "commit_count",
        "content_source",
    ]
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})
    outputs.append(str(path))


def md_delta(title: str, rows: list[dict[str, Any]], warnings: list[str]) -> str:
    lines = [
        f"# {title}",
        "",
        f"- Record count: {len(rows)}",
        f"- By category: `{json.dumps(count_by(rows, 'category'), ensure_ascii=False)}`",
        f"- By status: `{json.dumps(count_by(rows, 'status'), ensure_ascii=False)}`",
        "",
    ]
    if warnings:
        lines.extend(["## Scan Warnings", ""])
        lines.extend(f"- {warning}" for warning in warnings)
        lines.append("")
    lines.extend(["## First Records", "", "| status | category | path |", "| --- | --- | --- |"])
    for row in rows[:200]:
        lines.append(f"| {row['status']} | {row['category']} | `{row['path']}` |")
    if len(rows) > 200:
        lines.append(f"| ... | ... | {len(rows) - 200} more records omitted |")
    lines.append("")
    return "\n".join(lines)


def md_old_baseline(info: dict[str, Any]) -> str:
    lines = [
        "# Old Original Baseline",
        "",
        f"- Baseline mode: `{info.get('baseline_mode', 'unknown')}`",
        f"- Old original root: `{info.get('old_original_root', 'unknown')}`",
        f"- Baseline manifest: `{info.get('manifest_path', 'unknown')}`",
        f"- Manifest projects: {info.get('project_count', 0)}",
        f"- Matching focus projects: {info.get('matching_focus_project_count', 0)}",
        f"- Ahead repos: {info.get('ahead_repo_count', 0)}",
        f"- Ahead commits: {info.get('ahead_commit_count', 0)}",
        "",
        "Do not use a moving latest release branch as `old_original`. Reconstruct the old clean baseline from the locked manifest whenever the original directory is unavailable.",
        "",
    ]
    command = info.get("reconstruction_command") or []
    if command:
        lines.extend(["## Reconstruction Command", "", "```bash"])
        lines.extend(command)
        lines.extend(["```", ""])
    warnings = info.get("warnings") or []
    if warnings:
        lines.extend(["## Warnings", ""])
        lines.extend([f"- {item}" for item in warnings])
        lines.append("")
    return "\n".join(lines)


def md_matrix(matrix: list[dict[str, Any]]) -> str:
    lines = [
        "# Four-Tree Conflict Matrix",
        "",
        f"- Item count: {len(matrix)}",
        f"- By decision: `{json.dumps(count_by(matrix, 'migration_decision'), ensure_ascii=False)}`",
        f"- By phase: `{json.dumps(count_by(matrix, 'phase'), ensure_ascii=False)}`",
        "",
        "| id | decision | phase | risk | path | reason |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for row in matrix[:250]:
        lines.append(
            f"| {row['item_id']} | {row['migration_decision']} | {row['phase']} | {row['risk_level']} | `{row['path']}` | {row['reason']} |"
        )
    if len(matrix) > 250:
        lines.append(f"| ... | ... | ... | ... | {len(matrix) - 250} more records omitted | ... |")
    lines.append("")
    return "\n".join(lines)


def make_requirement_index(matrix: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "artifact_type": "migration_requirement_index",
        "generated_at": now(),
        "requirement_count": len(matrix),
        "requirements": [
            {
                "requirement_id": row["item_id"].replace("UPG-", "REQ-"),
                "source_path": row["path"],
                "category": row["category"],
                "phase": row["phase"],
                "migration_decision": row["migration_decision"],
                "risk_level": row["risk_level"],
                "next_action": next_action_for(row),
                "evidence_refs": row["evidence_refs"],
            }
            for row in matrix
        ],
    }


def next_action_for(row: dict[str, Any]) -> str:
    decision = row["migration_decision"]
    if decision == "direct_review_candidate":
        return "review and port the old source/config change onto the new version file, then build-triage"
    if decision == "merge_required":
        return "compare old porting intent with upstream new-version changes and produce a manual merge"
    if decision == "manual_retarget_required":
        return "locate the renamed or replaced new-version module before writing any patch"
    if decision == "already_in_progress_review":
        return "inspect the existing new-workspace delta before applying additional migration changes"
    if decision == "route_to_external_dependency_followup":
        return "request or inventory the real BSP/firmware/prebuilt dependency; use fake interfaces only for compile triage"
    return "record uncertainty and gather more evidence"


def make_work_order(matrix: list[dict[str, Any]]) -> dict[str, Any]:
    batches = []
    for phase in ["L0_target_identity", "L1_base_binding", "L2_build_triage", "L3_runtime_hdf_config", "L4_feature_driver_source", "L5_external_dependency_closure"]:
        items = [row for row in matrix if row["phase"] == phase]
        if not items:
            continue
        batches.append(
            {
                "batch_id": f"BATCH-{len(batches) + 1:03d}",
                "phase": phase,
                "item_count": len(items),
                "status": "manual_review_required",
                "objective": objective_for_phase(phase),
                "representative_paths": [row["path"] for row in items[:30]],
                "blocking_reasons": sorted({row["reason"] for row in items if row["risk_level"] in {"high", "external_dependency"}}),
                "verification_commands": [
                    {
                        "command_id": f"BUILD-{len(batches) + 1:03d}",
                        "command": "./build.sh --product-name <target_product> --ccache=false",
                        "runnable_now": False,
                        "scope": "build_only",
                    }
                ],
                "evidence_refs": [f"four_tree_conflict_matrix:{row['item_id']}" for row in items[:50]],
            }
        )
    return {
        "schema_version": 1,
        "artifact_type": "upgrade_porting_work_order",
        "generated_at": now(),
        "default_execution_policy": "manual_review_only",
        "workspace_write_policy": "do_not_write_to_workspace",
        "batch_count": len(batches),
        "batches": batches,
    }


def objective_for_phase(phase: str) -> str:
    return {
        "L0_target_identity": "make the target product identity visible in the new OpenHarmony version",
        "L1_base_binding": "bind product, vendor, board, SoC, and core build metadata without hiding selected features",
        "L2_build_triage": "migrate source/build compatibility changes proven by the four-tree matrix and build logs",
        "L3_runtime_hdf_config": "carry HDF and runtime configuration changes after base binding is visible",
        "L4_feature_driver_source": "port driver and feature source closures with manual API review",
        "L5_external_dependency_closure": "close BSP, firmware, prebuilt, bootloader, closed-driver, and packaging dependency gaps",
    }.get(phase, "review and migrate remaining evidence-bound changes")


def make_patch_plan(matrix: list[dict[str, Any]]) -> dict[str, Any]:
    patches = []
    for row in matrix:
        patches.append(
            {
                "patch_id": row["item_id"].replace("UPG-", "PATCH-"),
                "title": f"{row['migration_decision']} for {row['path']}",
                "target_paths": [row["path"]],
                "risk_level": row["risk_level"],
                "apply_mode": "manual_review",
                "auto_generate": False,
                "rationale": row["reason"],
                "blocked_by_external_dependency": row["migration_decision"] == "route_to_external_dependency_followup",
                "evidence_refs": [f"four_tree_conflict_matrix:{row['item_id']}"],
            }
        )
    return {
        "schema_version": 1,
        "artifact_type": "upgrade_patch_plan",
        "generated_at": now(),
        "default_apply_mode": "plan-only",
        "patch_count": len(patches),
        "patches": patches,
    }


def make_external_followup(matrix: list[dict[str, Any]]) -> dict[str, Any]:
    items = [
        {
            "dependency_id": row["item_id"].replace("UPG-", "EXT-"),
            "category": dependency_category(row),
            "provider_hint": "vendor_or_soc_provider",
            "requested_artifact": row["path"],
            "why_needed": row["reason"],
            "required_metadata": ["version", "source", "license", "sha256", "architecture", "redistribution_terms"],
            "evidence_refs": [f"four_tree_conflict_matrix:{row['item_id']}"],
        }
        for row in matrix
        if row["migration_decision"] == "route_to_external_dependency_followup"
    ]
    categories = ["bsp", "bootloader", "firmware", "prebuilt", "closed_driver", "signing_packaging_tools"]
    used = {item["category"] for item in items}
    return {
        "schema_version": 1,
        "artifact_type": "external_dependency_followup",
        "generated_at": now(),
        "coverage": [{"category": category, "status": "required" if category in used else "unknown"} for category in categories],
        "item_count": len(items),
        "items": items,
    }


def dependency_category(row: dict[str, Any]) -> str:
    p = row["path"].lower()
    if "boot" in p or "uboot" in p or "u-boot" in p:
        return "bootloader"
    if "firmware" in p or p.endswith(".hcd") or p.endswith(".bin"):
        return "firmware"
    if p.endswith(".so") or p.endswith(".a") or "/prebuilt" in p:
        return "prebuilt"
    if p.endswith(".ko") or row["category"] == "kernel_bsp":
        return "bsp"
    return "closed_driver"


def make_uncertainty(matrix: list[dict[str, Any]], warnings: list[str]) -> dict[str, Any]:
    items = []
    for warning in warnings:
        items.append(
            {
                "uncertainty_id": f"UNC-{len(items) + 1:03d}",
                "topic": "bounded_scan",
                "unknown": warning,
                "impact": "medium",
                "next_action": "rerun with narrower focus paths or full scan evidence if this path range matters",
                "evidence_refs": ["workspace:four_tree_scan"],
            }
        )
    for row in matrix:
        if row["migration_decision"] in {"manual_retarget_required", "merge_required"}:
            items.append(
                {
                    "uncertainty_id": f"UNC-{len(items) + 1:03d}",
                    "topic": row["path"],
                    "unknown": row["reason"],
                    "impact": row["risk_level"],
                    "next_action": next_action_for(row),
                    "evidence_refs": [f"four_tree_conflict_matrix:{row['item_id']}"],
                }
            )
    return {
        "schema_version": 1,
        "artifact_type": "uncertainty_ledger",
        "generated_at": now(),
        "item_count": len(items),
        "items": items,
    }


def make_build_acceptance(new_workspace: Path) -> dict[str, Any]:
    build_sh = new_workspace / "build.sh"
    return {
        "schema_version": 1,
        "artifact_type": "build_acceptance",
        "generated_at": now(),
        "scope": "build_only",
        "environment_setup_policy": "forbidden",
        "status_policy": {"build": "planned", "boot": "unknown", "runtime": "unknown", "tests": "unknown"},
        "commands": [
            {
                "command_id": "BUILD-001",
                "command": "./build.sh --product-name <target_product> --ccache=false" if build_sh.exists() else "unknown",
                "cwd": str(new_workspace),
                "purpose": "compile-flow triage after reviewed migration batches are applied",
                "uses_existing_script": build_sh.exists(),
                "environment_setup": False,
                "evidence_refs": ["workspace:build.sh" if build_sh.exists() else "unknown:missing_build_script"],
            }
        ],
    }


def write_artifacts(
    artifact_dir: Path,
    roots: dict[str, Any],
    focus_paths: list[str],
    old_delta: list[dict[str, Any]],
    upstream_delta: list[dict[str, Any]],
    workspace_delta: list[dict[str, Any]],
    matrix: list[dict[str, Any]],
    warnings: list[str],
    baseline_info: dict[str, Any],
) -> list[str]:
    outputs: list[str] = []
    artifact_dir.mkdir(parents=True, exist_ok=True)
    profile = {
        "schema_version": 1,
        "artifact_type": "four_tree_profile",
        "generated_at": now(),
        "mode": "plan-only",
        "baseline_mode": baseline_info.get("baseline_mode", "unknown"),
        "roots": {name: str(path) for name, path in roots.items()},
        "old_baseline_manifest": baseline_info.get("manifest_path", "unknown"),
        "focus_paths": focus_paths,
        "scan_policy": {
            "workspace_write_policy": "do_not_write_to_workspace",
            "external_dependency_policy": "inventory_only",
            "build_acceptance_scope": "build_only",
        },
        "counts": {
            "old_porting_delta": len(old_delta),
            "upstream_upgrade_delta": len(upstream_delta),
            "new_workspace_delta": len(workspace_delta),
            "conflict_items": len(matrix),
        },
        "warnings": warnings,
    }
    write_text(artifact_dir / "four_tree_profile.yaml", json_yaml(profile), outputs)
    old_baseline = {
        "schema_version": 1,
        "artifact_type": "old_original_baseline",
        "generated_at": now(),
        **baseline_info,
    }
    write_text(artifact_dir / "old_original_baseline.yaml", json_yaml(old_baseline), outputs)
    write_text(artifact_dir / "old_original_baseline.md", md_old_baseline(old_baseline), outputs)
    write_csv(artifact_dir / "old_porting_delta.csv", old_delta, outputs)
    write_text(artifact_dir / "old_porting_delta.md", md_delta("Old Porting Delta", old_delta, []), outputs)
    write_csv(artifact_dir / "upstream_upgrade_delta.csv", upstream_delta, outputs)
    write_text(artifact_dir / "upstream_upgrade_delta.md", md_delta("Upstream Upgrade Delta", upstream_delta, []), outputs)
    write_csv(artifact_dir / "new_workspace_delta.csv", workspace_delta, outputs)
    write_text(artifact_dir / "new_workspace_delta.md", md_delta("New Workspace Delta", workspace_delta, []), outputs)
    matrix_artifact = {
        "schema_version": 1,
        "artifact_type": "four_tree_conflict_matrix",
        "generated_at": now(),
        "item_count": len(matrix),
        "decision_counts": count_by(matrix, "migration_decision"),
        "phase_counts": count_by(matrix, "phase"),
        "items": matrix,
    }
    write_text(artifact_dir / "four_tree_conflict_matrix.yaml", json_yaml(matrix_artifact), outputs)
    write_text(artifact_dir / "four_tree_conflict_matrix.md", md_matrix(matrix), outputs)
    requirement_index = make_requirement_index(matrix)
    write_text(artifact_dir / "migration_requirement_index.yaml", json_yaml(requirement_index), outputs)
    write_text(
        artifact_dir / "migration_requirement_index.md",
        md_matrix(
            [
                {
                    **row,
                    "migration_decision": row["migration_decision"],
                    "reason": next_action_for(row),
                }
                for row in matrix
            ]
        ).replace("# Four-Tree Conflict Matrix", "# Migration Requirement Index", 1),
        outputs,
    )
    work_order = make_work_order(matrix)
    write_text(artifact_dir / "upgrade_porting_work_order.yaml", json_yaml(work_order), outputs)
    write_text(artifact_dir / "upgrade_porting_work_order.md", md_work_order(work_order), outputs)
    patch_plan = make_patch_plan(matrix)
    write_text(artifact_dir / "upgrade_patch_plan.yaml", json_yaml(patch_plan), outputs)
    write_text(artifact_dir / "upgrade_patch_plan.md", md_patch_plan(patch_plan), outputs)
    external = make_external_followup(matrix)
    write_text(artifact_dir / "external_dependency_followup.yaml", json_yaml(external), outputs)
    write_text(artifact_dir / "external_dependency_followup.md", md_external(external), outputs)
    build = make_build_acceptance(roots["new_workspace"])
    write_text(artifact_dir / "build_acceptance.yaml", json_yaml(build), outputs)
    write_text(artifact_dir / "build_acceptance.md", "# Build Acceptance\n\nBuild acceptance is compile-flow only. Boot, runtime, and tests remain unknown until explicit logs prove them.\n", outputs)
    uncertainty = make_uncertainty(matrix, warnings)
    write_text(artifact_dir / "uncertainty_ledger.yaml", json_yaml(uncertainty), outputs)
    write_text(artifact_dir / "uncertainty_ledger.md", md_uncertainty(uncertainty), outputs)
    summary = {
        "schema_version": 1,
        "artifact_type": "upgrade_porting_summary",
        "generated_at": now(),
        "completion_claim": "not_complete",
        "summary": "four-tree upgrade migration evidence generated; no workspace files were modified",
        "next_actions": [
            "review direct_review_candidate and merge_required items before writing source patches",
            "resolve manual_retarget_required items against the new-version module layout",
            "inventory BSP, firmware, prebuilt, bootloader, and closed-driver dependencies before runtime claims",
            "run build-only triage after reviewed L0/L1 batches are applied",
        ],
    }
    write_text(artifact_dir / "upgrade_porting_summary.yaml", json_yaml(summary), outputs)
    write_text(artifact_dir / "upgrade_porting_summary.md", md_summary(profile, matrix, external, uncertainty), outputs)
    return outputs


def md_work_order(work_order: dict[str, Any]) -> str:
    lines = ["# Upgrade Porting Work Order", "", f"- Batch count: {work_order['batch_count']}", ""]
    for batch in work_order["batches"]:
        lines.extend(
            [
                f"## {batch['batch_id']} {batch['phase']}",
                "",
                f"- Items: {batch['item_count']}",
                f"- Status: {batch['status']}",
                f"- Objective: {batch['objective']}",
                "",
            ]
        )
    return "\n".join(lines)


def md_patch_plan(patch_plan: dict[str, Any]) -> str:
    lines = ["# Upgrade Patch Plan", "", f"- Patch count: {patch_plan['patch_count']}", "- Default apply mode: plan-only", ""]
    lines.extend(["| patch | risk | path | rationale |", "| --- | --- | --- | --- |"])
    for patch in patch_plan["patches"][:200]:
        path = patch["target_paths"][0] if patch["target_paths"] else "unknown"
        lines.append(f"| {patch['patch_id']} | {patch['risk_level']} | `{path}` | {patch['rationale']} |")
    return "\n".join(lines) + "\n"


def md_external(external: dict[str, Any]) -> str:
    lines = ["# External Dependency Follow-Up", "", f"- Item count: {external['item_count']}", ""]
    lines.extend(["| id | category | artifact | why |", "| --- | --- | --- | --- |"])
    for item in external["items"][:200]:
        lines.append(f"| {item['dependency_id']} | {item['category']} | `{item['requested_artifact']}` | {item['why_needed']} |")
    return "\n".join(lines) + "\n"


def md_uncertainty(uncertainty: dict[str, Any]) -> str:
    lines = ["# Uncertainty Ledger", "", f"- Item count: {uncertainty['item_count']}", ""]
    lines.extend(["| id | topic | impact | next action |", "| --- | --- | --- | --- |"])
    for item in uncertainty["items"][:200]:
        lines.append(f"| {item['uncertainty_id']} | `{item['topic']}` | {item['impact']} | {item['next_action']} |")
    return "\n".join(lines) + "\n"


def md_summary(profile: dict[str, Any], matrix: list[dict[str, Any]], external: dict[str, Any], uncertainty: dict[str, Any]) -> str:
    lines = [
        "# Upgrade Porting Summary",
        "",
        "No workspace files were modified.",
        "",
        f"- Old porting delta: {profile['counts']['old_porting_delta']}",
        f"- Upstream upgrade delta: {profile['counts']['upstream_upgrade_delta']}",
        f"- New workspace delta: {profile['counts']['new_workspace_delta']}",
        f"- Migration/conflict items: {len(matrix)}",
        f"- External dependency items: {external['item_count']}",
        f"- Uncertainty items: {uncertainty['item_count']}",
        f"- Decisions: `{json.dumps(count_by(matrix, 'migration_decision'), ensure_ascii=False)}`",
        "",
        "Build success must not be treated as boot, runtime, driver, app, CTS, or test success.",
        "",
    ]
    return "\n".join(lines)


def existing_dir(value: str, name: str) -> Path:
    path = Path(value).expanduser().resolve()
    if not path.is_dir():
        raise SystemExit(f"{name} must be an existing directory: {path}")
    return path


def existing_file(value: str, name: str) -> Path:
    path = Path(value).expanduser().resolve()
    if not path.is_file():
        raise SystemExit(f"{name} must be an existing file: {path}")
    return path


def reconstruction_command(old_ported: Path, manifest: Path) -> list[str]:
    info = manifest_remote_info(old_ported)
    try:
        manifest_rel = normalize_rel(str(manifest.relative_to(old_ported / ".repo/manifests")))
    except Exception:
        manifest_rel = str(manifest)
    command = []
    if info["remote_url"] != "unknown":
        branch_arg = f" -b {info['branch']}" if info["branch"] != "unknown" else ""
        command.append(f"repo init -u {info['remote_url']}{branch_arg} -m {manifest_rel}")
    else:
        command.append(f"repo init -u <manifest_url> -b <manifest_branch> -m {manifest_rel}")
    command.append("repo sync -j8")
    return command


def main() -> None:
    ap = argparse.ArgumentParser(description="Generate four-tree OpenHarmony version-upgrade porting evidence.")
    ap.add_argument("--old-original")
    ap.add_argument("--old-ported", required=True)
    ap.add_argument("--new-original", required=True)
    ap.add_argument("--new-workspace", required=True)
    ap.add_argument("--old-baseline-manifest")
    ap.add_argument("--no-auto-old-baseline-manifest", action="store_true")
    ap.add_argument("--out", required=True)
    ap.add_argument("--artifact-root")
    ap.add_argument("--stage-result")
    ap.add_argument("--focus-path", action="append", default=[])
    ap.add_argument("--max-records", type=int, default=20000)
    args = ap.parse_args()

    old_ported = existing_dir(args.old_ported, "--old-ported")
    new_original = existing_dir(args.new_original, "--new-original")
    new_workspace = existing_dir(args.new_workspace, "--new-workspace")
    old_original = existing_dir(args.old_original, "--old-original") if args.old_original else None
    baseline_manifest = existing_file(args.old_baseline_manifest, "--old-baseline-manifest") if args.old_baseline_manifest else None
    out = Path(args.out).expanduser().resolve()
    artifact_dir = Path(args.artifact_root).expanduser().resolve() if args.artifact_root else out / "09_version_upgrade"
    focus_paths = [normalize_rel(path) for path in (args.focus_path or DEFAULT_FOCUS_PATHS)]
    focus_paths = [path for path in focus_paths if path and path != "."]
    max_records = max(1, args.max_records)

    roots: dict[str, Any] = {
        "old_original": old_original if old_original is not None else "unknown",
        "old_ported": old_ported,
        "new_original": new_original,
        "new_workspace": new_workspace,
    }
    baseline_info: dict[str, Any] = {
        "baseline_mode": "old_original_directory" if old_original is not None else "old_ported_locked_manifest",
        "old_original_root": str(old_original) if old_original is not None else "unknown",
        "manifest_path": "unknown",
        "project_count": 0,
        "matching_focus_project_count": 0,
        "same_head_count": 0,
        "ahead_repo_count": 0,
        "ahead_commit_count": 0,
        "missing_checkout_count": 0,
        "missing_revision_count": 0,
        "not_ancestor_count": 0,
        "reconstruction_command": [],
        "warnings": [],
    }

    old_warnings: list[str] = []
    upstream_warnings: list[str] = []
    if old_original is not None:
        log("INFO", "scanning old_original -> old_ported")
        old_delta, old_warnings = diff_focus(old_original, old_ported, focus_paths, max_records)
        log("INFO", "scanning old_original -> new_original")
        upstream_delta, upstream_warnings = diff_focus(old_original, new_original, focus_paths, max_records)
        if baseline_manifest is not None:
            try:
                projects = load_manifest_projects(baseline_manifest)
                baseline_info.update(
                    {
                        "manifest_path": str(baseline_manifest),
                        "project_count": len(projects),
                        "reconstruction_command": reconstruction_command(old_ported, baseline_manifest),
                    }
                )
            except Exception as exc:
                baseline_info["warnings"].append(f"could not summarize old baseline manifest {baseline_manifest}: {exc}")
    else:
        if baseline_manifest is None and not args.no_auto_old_baseline_manifest:
            baseline_manifest, discovery_warnings = discover_old_baseline_manifest(old_ported)
            baseline_info["warnings"].extend(discovery_warnings)
        if baseline_manifest is None:
            raise SystemExit(
                "--old-original was not supplied and no locked old baseline manifest could be found; "
                "provide --old-original or --old-baseline-manifest"
            )
        log("INFO", "scanning old_ported HEAD against locked old baseline manifest")
        old_delta, old_warnings, manifest_stats = diff_old_ported_from_manifest(old_ported, baseline_manifest, focus_paths, max_records)
        baseline_info.update(manifest_stats)
        baseline_info["baseline_mode"] = "old_ported_locked_manifest"
        baseline_info["old_original_root"] = "not_supplied_reconstruct_from_manifest"
        baseline_info["reconstruction_command"] = reconstruction_command(old_ported, baseline_manifest)
        upstream_delta = []
        upstream_warnings.append(
            "old_original directory was not supplied; old_original -> new_original upstream upgrade delta is unavailable until the locked baseline is reconstructed"
        )
    log("INFO", "scanning new_original -> new_workspace")
    workspace_delta, workspace_warnings = diff_focus(new_original, new_workspace, focus_paths, max_records)
    warnings = old_warnings + upstream_warnings + workspace_warnings + list(baseline_info.get("warnings") or [])
    matrix = build_conflict_matrix(old_delta, upstream_delta, workspace_delta, new_original)
    outputs = write_artifacts(artifact_dir, roots, focus_paths, old_delta, upstream_delta, workspace_delta, matrix, warnings, baseline_info)

    status = "passed" if old_delta and old_original is not None else "partial"
    blocking: list[str] = []
    non_blocking = warnings[:]
    if not old_delta:
        non_blocking.append("old_original -> old_ported produced no records in the bounded scan")
    if old_original is None:
        non_blocking.append("old_original was inferred from a locked manifest; reconstruct it for complete upstream upgrade delta analysis")
    stage_result = {
        "stage": "11_version_upgrade_porting",
        "status": status,
        "summary": "four-tree version-upgrade porting evidence generated",
        "execution_mode": "plan-only",
        "artifact_root": str(artifact_dir),
        "input_roots": {name: str(path) for name, path in roots.items()},
        "baseline_mode": baseline_info.get("baseline_mode", "unknown"),
        "old_baseline_manifest": baseline_info.get("manifest_path", "unknown"),
        "input_files_read": [],
        "output_files_written": outputs,
        "blocking_issues": blocking,
        "non_blocking_issues": non_blocking,
        "next_stage_inputs": [
            str(artifact_dir / "four_tree_conflict_matrix.yaml"),
            str(artifact_dir / "upgrade_porting_work_order.yaml"),
            str(artifact_dir / "external_dependency_followup.yaml"),
        ],
        "old_porting_delta_count": len(old_delta),
        "upstream_upgrade_delta_count": len(upstream_delta),
        "new_workspace_delta_count": len(workspace_delta),
        "conflict_item_count": len(matrix),
        "external_dependency_followup_count": sum(1 for row in matrix if row["migration_decision"] == "route_to_external_dependency_followup"),
        "uncertainty_count": len(make_uncertainty(matrix, warnings)["items"]),
    }
    if args.stage_result:
        stage_path = Path(args.stage_result).expanduser().resolve()
        stage_path.parent.mkdir(parents=True, exist_ok=True)
        stage_path.write_text(json.dumps(stage_result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(stage_result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
