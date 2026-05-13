#!/usr/bin/env python3
"""Deterministic semantic layer generator for OpenHarmony porting pipeline.

This script is intentionally conservative.  It is useful as a fallback and as
candidate generation for LLM-assisted stages, but it must not over-promote noisy
sync/import commits into reusable knowledge cases.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import shutil
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable


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


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists() or path.stat().st_size == 0:
        return []
    with path.open(encoding="utf-8", errors="ignore", newline="") as f:
        return list(csv.DictReader(f))


def safe_name(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "__", (value or "").strip("/")) or "root"


def recreate_generated_dir(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)


def int_value(value: Any) -> int:
    try:
        return int(value or 0)
    except Exception:
        return 0


def path_of(row: dict[str, Any]) -> str:
    return str(row.get("path") or row.get("file_path") or "")


def is_gitattributes_only(paths: Iterable[str]) -> bool:
    vals = [p for p in paths if p]
    return bool(vals) and all(Path(p).name == ".gitattributes" for p in vals)


def subject_text(subject: Any) -> str:
    return str(subject or "").strip()


def infer_noise_reason(subject: str, paths: list[str], origin_type: str | None) -> str | None:
    text = " ".join([subject, *paths]).lower()
    if origin_type == "initial_import":
        return "initial_import_baseline"
    if "force sync sdk code" in text or re.search(r"\bforce\s+sync\b", text):
        return "force_sync_subject"
    if is_gitattributes_only(paths):
        return "gitattributes_only"
    if all(Path(p).suffix in {".md", ".txt", ".rst"} for p in paths if p) and paths:
        return "document_only"
    return None


def infer_theme(subject: Any, paths: list[str], origin_type: str | None = None) -> tuple[str, str | None]:
    subj = subject_text(subject)
    noise = infer_noise_reason(subj, paths, origin_type)
    if noise:
        if noise == "initial_import_baseline":
            return "initial_import", noise
        return "sync_noise", noise

    text = " ".join([subj, *paths]).lower()
    if "libawion" in text and ("uapi" in text or "cedar_ve_uapi" in text):
        return "soc_uapi_include_integration", None
    if "toybox" in text and "reboot" in text and "efex" in text:
        return "reboot_efex_runtime_support", None
    if "cedar-ve" in text or "cedar_ve" in text:
        return "cedar_ve_driver_uapi_fix", None
    rules: list[tuple[str, list[str]]] = [
        ("wifi_type_api_compat", ["u8", "u16", "u32", "pthread_setname", "pthread_setname_np", "ps -e", "wifimanager", "wirelesscommon"]),
        ("wifi_runtime_integration", ["wifi", "wpa", "supplicant", "bk7236", "dhcpcd", "libnl", "netlink"]),
        ("hdf_audio_chain", ["audio", "codec", "dai", "dma", "speaker", "pa_pin", "hdf", ".hcs", ".hcb"]),
        ("product_board_soc_binding", ["productdefine", "product", "vendor/", "device/board", "device/soc", "config.json", "bundle.json"]),
        ("boot_firmware_board_config", ["bootloader", "brandy", "u-boot", "uboot", "spl", "arisc", "dsp", "fex", ".dts", ".dtsi"]),
        ("kernel_driver_adaptation", ["kernel", "driver", "drivers/", ".ko", "defconfig", "kconfig"]),
        ("build_integration", ["build.gn", "bundle.json", "config.gni", "gn", "makefile", "ninja", "product.gni"]),
        ("binary_prebuilt_provenance", ["prebuilt", ".bin", ".so", ".a", ".elf", ".img", ".fw"]),
    ]
    for theme, needles in rules:
        if any(needle in text for needle in needles):
            return theme, None
    return "general_porting", None


def candidate_score(theme: str, row: dict[str, Any], files: list[dict[str, Any]]) -> tuple[int, list[str]]:
    reasons: list[str] = []
    score = 0
    if row.get("origin_type") == "initial_import":
        return 0, ["initial import is not a reusable fix case"]
    if theme in {"sync_noise", "initial_import"}:
        return 0, [f"theme={theme} is excluded from case generation"]
    if files:
        score += 10
        reasons.append("has file-level evidence")
    if row.get("diff_path"):
        score += 5
        reasons.append("has diff evidence")
    if theme in {
        "wifi_type_api_compat",
        "wifi_runtime_integration",
        "hdf_audio_chain",
        "product_board_soc_binding",
        "boot_firmware_board_config",
        "kernel_driver_adaptation",
        "soc_uapi_include_integration",
        "reboot_efex_runtime_support",
        "cedar_ve_driver_uapi_fix",
    }:
        score += 15
        reasons.append(f"theme {theme} is high-value for board/SoC porting")
    changed = int_value(row.get("changed_files_count"))
    if 1 <= changed <= 80:
        score += 3
        reasons.append("bounded patch size")
    elif changed > 300:
        score -= 10
        reasons.append("very large patch likely needs manual decomposition")
    return max(0, score), reasons


def first_items(items: Iterable[Any], limit: int = 8) -> list[Any]:
    return list(items)[:limit]


def md_table(headers: list[str], rows: list[list[Any]]) -> str:
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join(["---"] * len(headers)) + " |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(str(cell).replace("\n", " ") for cell in row) + " |")
    return "\n".join(lines)


def binary_repo_for_path(path: str) -> str:
    if not path:
        return "unknown"
    parts = path.split("/")
    if path.startswith("device/board/") and len(parts) >= 5:
        return "/".join(parts[:5])
    if path.startswith("device/soc/") and len(parts) >= 4:
        return "/".join(parts[:4])
    if path.startswith("vendor/") and len(parts) >= 3:
        return "/".join(parts[:3])
    for prefix in ["arkcompiler", "developtools", "third_party", "drivers", "prebuilts", "foundation", "applications"]:
        if path.startswith(prefix + "/") or path == prefix:
            return prefix
    return parts[0]


def dirty_status(row: dict[str, Any]) -> str:
    return str(row.get("xy_status") or row.get("change_type") or row.get("change_status") or "unknown")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--stage-result")
    args = ap.parse_args()
    out = Path(args.out)
    sem_dir = out / "03_semantic_analysis"
    repo_dir = sem_dir / "repo_analysis"
    subsystem_dir = sem_dir / "subsystem_analysis"
    llm_dir = sem_dir / "_llm_inputs"
    sem_dir.mkdir(parents=True, exist_ok=True)
    recreate_generated_dir(repo_dir)
    recreate_generated_dir(subsystem_dir)
    recreate_generated_dir(llm_dir)

    commits = read_jsonl(out / "01_raw_records/commit_records.jsonl")
    files = read_jsonl(out / "01_raw_records/file_change_records.jsonl")
    dirty_files = read_jsonl(out / "01_raw_records/dirty_file_records.jsonl")
    binary_rows = read_csv(out / "01_raw_records/binary_asset_records.csv")
    stats_path = out / "02_statistics/statistics_summary.json"
    stats = json.loads(stats_path.read_text(encoding="utf-8")) if stats_path.exists() else {}

    files_by_commit: dict[str, list[dict[str, Any]]] = defaultdict(list)
    files_by_repo: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for file_row in files:
        files_by_commit[str(file_row.get("commit_evidence_id") or "")].append(file_row)
        files_by_repo[str(file_row.get("repo_path") or "unknown")].append(file_row)

    commits_by_repo: dict[str, list[dict[str, Any]]] = defaultdict(list)
    commits_by_class: dict[str, list[dict[str, Any]]] = defaultdict(list)
    commit_analysis: list[dict[str, Any]] = []
    for row in commits:
        repo = str(row.get("repo_path") or "unknown")
        classification = str(row.get("classification") or "unknown")
        related_files = files_by_commit.get(str(row.get("evidence_id") or ""), [])
        related_paths = [path_of(item) for item in related_files]
        theme, noise_reason = infer_theme(row.get("subject"), related_paths, row.get("origin_type"))
        score, reasons = candidate_score(theme, row, related_files)
        evidence_files = [
            {
                "evidence_id": item.get("evidence_id"),
                "repo_path": item.get("repo_path"),
                "file_path": path_of(item),
                "change_type": item.get("change_type"),
            }
            for item in first_items(related_files, 20)
        ]
        analysis = {
            "record_type": "commit_analysis",
            "commit_evidence_id": row.get("evidence_id"),
            "repo_path": repo,
            "classification": classification,
            "commit_hash": row.get("commit_hash") or row.get("commit"),
            "origin_type": row.get("origin_type"),
            "subject": row.get("subject"),
            "semantic_theme": theme,
            "noise_reason": noise_reason,
            "is_case_candidate": score >= 15,
            "case_candidate_score": score,
            "case_candidate_reasons": reasons,
            "porting_relevance": (
                "excluded/noise" if noise_reason else f"{theme} evidence for target OpenHarmony port"
            ),
            "evidence_commits": [f"{repo}:{row.get('commit_hash') or row.get('commit')}"] if (row.get("commit_hash") or row.get("commit")) else [],
            "evidence_files": evidence_files,
            "evidence_diffs": [row.get("diff_path")] if row.get("diff_path") else [],
            "changed_files_count": int_value(row.get("changed_files_count")),
            "insertions": int_value(row.get("insertions")),
            "deletions": int_value(row.get("deletions")),
        }
        commit_analysis.append(analysis)
        commits_by_repo[repo].append(analysis)
        commits_by_class[classification].append(analysis)

    dirty_by_repo: dict[str, list[dict[str, Any]]] = defaultdict(list)
    dirty_by_class: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in dirty_files:
        repo = str(row.get("repo_path") or "unknown")
        classification = str(row.get("classification") or row.get("dirty_content_class") or "unknown")
        dirty_by_repo[repo].append(row)
        dirty_by_class[classification].append(row)

    binary_by_repo: dict[str, list[dict[str, str]]] = defaultdict(list)
    binary_by_class: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in binary_rows:
        path = row.get("path") or row.get("file_path") or ""
        repo = row.get("repo_path") or binary_repo_for_path(path)
        classification_match = re.search(r"(?:^|; )classification=([^;]+)", row.get("analysis_note") or "")
        classification = row.get("classification") or (classification_match.group(1) if classification_match else "unknown")
        binary_by_repo[repo].append(row)
        binary_by_class[classification].append(row)

    with (sem_dir / "commit_analysis.jsonl").open("w", encoding="utf-8") as f:
        for row in commit_analysis:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    # Compact LLM input slices.  These are small enough to pass into a model stage
    # and contain explicit candidate/noise flags.
    candidates = sorted(
        [row for row in commit_analysis if row.get("is_case_candidate")],
        key=lambda row: (-int_value(row.get("case_candidate_score")), row.get("repo_path") or ""),
    )
    with (llm_dir / "semantic_candidate_commits.jsonl").open("w", encoding="utf-8") as f:
        for row in candidates[:120]:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    noisy = [row for row in commit_analysis if row.get("noise_reason")]
    with (llm_dir / "excluded_noise_commits.jsonl").open("w", encoding="utf-8") as f:
        for row in noisy[:200]:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    risk_items = [
        "# Risk Items",
        "",
        f"- Statistics source: `02_statistics/statistics_summary.json` records {stats.get('commit_records_count', len(commits))} commits, {stats.get('file_change_records_count', len(files))} file changes, {stats.get('binary_asset_records_count', len(binary_rows))} binary assets, and {stats.get('dirty_file_records_count', len(dirty_files))} dirty files.",
        "- Dirty workspace facts are separated from committed history and must not be treated as landed upstream changes.",
        f"- {len(noisy)} commit analyses are excluded as initial import, force-sync, .gitattributes-only, or documentation-only noise.",
    ]
    runtime_binary_examples = [row for row in binary_rows if str(row.get("runtime_dependency") or "").lower() == "yes"][:20]
    if runtime_binary_examples:
        risk_items.append("- Runtime binary/prebuilt artifacts require provenance and redistribution review:")
        for row in runtime_binary_examples:
            risk_items.append(
                f"  - `{row.get('path') or row.get('file_path')}` sha256={row.get('sha256')} usage={row.get('possible_usage')} introduced_by={row.get('introduced_by')}"
            )
    large_commits = sorted(
        [row for row in commit_analysis if row.get("is_case_candidate")],
        key=lambda row: int_value(row.get("insertions")) + int_value(row.get("deletions")),
        reverse=True,
    )[:10]
    if large_commits:
        risk_items.append("- Large downstream candidate diffs should be reviewed before reuse:")
        for row in large_commits:
            risk_items.append(
                f"  - {row['commit_evidence_id']} `{row['repo_path']}` {row['commit_hash']} theme={row['semantic_theme']} score={row['case_candidate_score']} diff={row['evidence_diffs'] or ['unknown']}"
            )

    workaround_items = [
        "# Workaround Items",
        "",
        "- Keep workaround notes separate from reusable rules. Items below are evidence-bound observations, not best practices.",
        "- Wi-Fi enablement imports large libnl/wpa_supplicant patch payloads; reuse only after checking whether upstream OpenHarmony already has equivalent support.",
        "- Dirty prebuilt/toolchain trees under `prebuilts/` and Node package trees under `arkcompiler/` may be local build-environment workarounds until provenance is confirmed.",
        "- Generated HDF binary config such as `vendor/seed/t113_evb1/hdf_config/hdf_hcs.hcb` should be regenerated from source HCS where possible rather than edited directly.",
        "- Force-sync and .gitattributes-only commits are synchronization/noise evidence, not reusable porting cases.",
    ]

    all_repos = sorted(set(commits_by_repo) | set(files_by_repo) | set(dirty_by_repo) | set(binary_by_repo))
    for repo in all_repos:
        repo_commits = commits_by_repo.get(repo, [])
        repo_files = files_by_repo.get(repo, [])
        repo_dirty = dirty_by_repo.get(repo, [])
        repo_binary = binary_by_repo.get(repo, [])
        themes = Counter(row["semantic_theme"] for row in repo_commits)
        candidates_for_repo = [row for row in repo_commits if row.get("is_case_candidate")]
        excluded_for_repo = [row for row in repo_commits if row.get("noise_reason")]
        lines = [
            f"# Repo Analysis: {repo}",
            "",
            md_table(
                ["Metric", "Value"],
                [
                    ["commit analyses", len(repo_commits)],
                    ["case candidates", len(candidates_for_repo)],
                    ["excluded/noise commits", len(excluded_for_repo)],
                    ["file change records", len(repo_files)],
                    ["dirty file records", len(repo_dirty)],
                    ["binary asset records", len(repo_binary)],
                    ["top themes", ", ".join(f"{key}:{value}" for key, value in themes.most_common(5)) or "none"],
                ],
            ),
            "",
            "## Evidence Commits",
        ]
        for row in first_items(candidates_for_repo, 16):
            lines.append(
                f"- {row['commit_evidence_id']} `{row['commit_hash']}` theme={row['semantic_theme']} score={row['case_candidate_score']} subject={row['subject']} diff={row['evidence_diffs'] or ['unknown']}"
            )
        if not candidates_for_repo:
            lines.append("- No reusable case candidate beyond initial import/sync/noise in raw commit records.")
        if excluded_for_repo:
            lines.extend(["", "## Excluded / Noise Evidence"])
            for row in first_items(excluded_for_repo, 8):
                lines.append(f"- {row['commit_evidence_id']} `{row['commit_hash']}` reason={row['noise_reason']} subject={row['subject']}")
        lines.extend(["", "## Evidence Files"])
        for row in first_items(repo_files, 16):
            lines.append(
                f"- {row.get('evidence_id')} `{path_of(row)}` change={row.get('change_type')} commit={row.get('commit_evidence_id')}"
            )
        if repo_dirty:
            lines.extend(["", "## Dirty Workspace Evidence"])
            for row in first_items(repo_dirty, 16):
                lines.append(
                    f"- {row.get('evidence_id')} `{row.get('path') or row.get('file_path')}` xy_status={dirty_status(row)} change_type={row.get('change_type') or 'unknown'} class={row.get('dirty_content_class') or row.get('classification')}"
                )
        if repo_binary:
            lines.extend(["", "## Binary/Prebuilt Evidence"])
            for row in first_items(repo_binary, 12):
                lines.append(
                    f"- `{row.get('path') or row.get('file_path')}` kind={row.get('asset_kind') or 'unknown'} sha256={row.get('sha256')} arch={row.get('architecture')} runtime={row.get('runtime_dependency')}"
                )
        lines.extend([
            "",
            "## Scope Note",
            "Unsupported claims are `unknown`; conclusions above are derived only from listed evidence records. Force-sync and .gitattributes-only commits must not be promoted into reusable cases.",
            "",
        ])
        (repo_dir / f"{safe_name(repo)}.md").write_text("\n".join(lines), encoding="utf-8")

    all_classes = sorted(set(commits_by_class) | set(dirty_by_class) | set(binary_by_class))
    for classification in all_classes:
        rows = commits_by_class.get(classification, [])
        dirty = dirty_by_class.get(classification, [])
        binary = binary_by_class.get(classification, [])
        themes = Counter(row["semantic_theme"] for row in rows)
        candidates_in_class = [row for row in rows if row.get("is_case_candidate")]
        lines = [
            f"# Subsystem Analysis: {classification}",
            "",
            md_table(
                ["Metric", "Value"],
                [
                    ["commit analyses", len(rows)],
                    ["case candidates", len(candidates_in_class)],
                    ["dirty file records", len(dirty)],
                    ["binary asset records", len(binary)],
                    ["top themes", ", ".join(f"{key}:{value}" for key, value in themes.most_common(8)) or "none"],
                ],
            ),
            "",
            "## Representative Candidate Evidence",
        ]
        for row in first_items(candidates_in_class, 20):
            lines.append(
                f"- {row['commit_evidence_id']} `{row['repo_path']}` {row['commit_hash']} theme={row['semantic_theme']} score={row['case_candidate_score']} files={len(row['evidence_files'])}"
            )
        if not candidates_in_class:
            lines.append("- No reusable candidate commits after filtering sync/import/noise records.")
        if binary:
            lines.extend(["", "## Binary/Prebuilt Evidence"])
            for row in first_items(binary, 12):
                lines.append(f"- `{row.get('path') or row.get('file_path')}` kind={row.get('asset_kind') or 'unknown'} sha256={row.get('sha256')} usage={row.get('possible_usage')}")
        lines.append("")
        (subsystem_dir / f"{safe_name(classification)}.md").write_text("\n".join(lines), encoding="utf-8")

    (sem_dir / "risk_items.md").write_text("\n".join(risk_items) + "\n", encoding="utf-8")
    (sem_dir / "workaround_items.md").write_text("\n".join(workaround_items) + "\n", encoding="utf-8")

    outputs = [
        "03_semantic_analysis/commit_analysis.jsonl",
        "03_semantic_analysis/repo_analysis/",
        "03_semantic_analysis/subsystem_analysis/",
        "03_semantic_analysis/_llm_inputs/semantic_candidate_commits.jsonl",
        "03_semantic_analysis/_llm_inputs/excluded_noise_commits.jsonl",
        "03_semantic_analysis/risk_items.md",
        "03_semantic_analysis/workaround_items.md",
    ]
    result = {
        "stage": "04_semantic_analyzer",
        "status": "passed",
        "summary": f"Generated filtered semantic analysis for {len(commit_analysis)} commits, {len(all_repos)} repos, {len(all_classes)} subsystem classes, and {len(candidates)} case candidates.",
        "input_files_read": [
            "00_config/task_profile.yaml",
            "01_raw_records/commit_records.jsonl",
            "01_raw_records/file_change_records.jsonl",
            "01_raw_records/dirty_file_records.jsonl",
            "01_raw_records/binary_asset_records.csv",
            "01_raw_records/diffs/",
            "03_semantic_analysis/evidence_index.jsonl",
            "02_statistics/statistics_summary.json",
        ],
        "output_files_written": outputs,
        "blocking_issues": [],
        "non_blocking_issues": [
            "Deterministic semantic text is evidence-filtered but still mechanically generated; prefer LLM refinement for hunk-level interpretation.",
        ],
        "next_stage_inputs": outputs,
        "case_candidate_count": len(candidates),
        "excluded_noise_commit_count": len(noisy),
    }
    if args.stage_result:
        Path(args.stage_result).write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
