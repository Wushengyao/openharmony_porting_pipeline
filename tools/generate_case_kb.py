#!/usr/bin/env python3
"""Evidence-bound case/knowledge-base generator for OpenHarmony porting pipeline.

The deterministic path is intentionally selective.  It prefers fewer reusable
cases with real porting semantics over many template cases.  Sync/noise commits,
initial imports, and .gitattributes-only changes are excluded from reusable
cases and may only appear in risk notes or rejected evidence.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import shutil
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable


CASE_ORDER = [
    "wifi_type_api_compat",
    "wifi_runtime_integration",
    "hdf_audio_chain",
    "soc_uapi_include_integration",
    "reboot_efex_runtime_support",
    "cedar_ve_driver_uapi_fix",
    "build_integration",
]

CASE_DEFS = {
    "wifi_type_api_compat": {
        "id": "T113-WIFI-API-COMPAT",
        "title": "WiFi vendor code type and libc API compatibility",
        "problem": "Vendor WiFi-related code can depend on non-standard Linux/vendor type aliases or libc/toolbox behaviours that are not stable in the OpenHarmony target build/runtime context.",
        "root_cause": "The code path was written for a different SDK/libc/toolbox environment and assumes symbols or command semantics such as u8/u16/u32, pthread_setname_np, ps output, or fcntl/link behaviour without checking the target OpenHarmony sysroot and runtime tools.",
        "fix": "Replace non-standard aliases with explicit C99/stdint types where appropriate, adjust API calls to the target libc header declaration, and validate shell/process detection commands on the target image instead of assuming Linux desktop semantics.",
        "rule": "When importing vendor WiFi code into an OpenHarmony board/SoC port, first scan for non-standard type aliases, libc-specific function signatures, and shell command assumptions before treating build/runtime failures as driver issues.",
    },
    "wifi_runtime_integration": {
        "id": "T113-WIFI-RUNTIME-INTEGRATION",
        "title": "WiFi BSP, third_party and runtime integration chain",
        "problem": "WiFi bring-up is a cross-layer change: board scripts, SoC/BSP support, libnl/wpa_supplicant/dhcpcd payloads, firmware or vendor libraries, and runtime service configuration must agree.",
        "root_cause": "A single WiFi patch rarely contains all required integration points. Missing or mismatched third_party patches, board-level scripts, prebuilt runtime binaries, or product configuration can make the system build but fail at runtime.",
        "fix": "Trace WiFi evidence across board/vendor/device/soc/third_party/prebuilt records, keep runtime binaries separate from source fixes, and require target-side verification for process detection and service startup.",
        "rule": "For a new board, treat WiFi as a subsystem chain rather than a single repo change; verify source patch, runtime binary, service configuration, and product inclusion together.",
    },
    "hdf_audio_chain": {
        "id": "T113-HDF-AUDIO-CHAIN",
        "title": "HDF Audio multi-repo adaptation chain",
        "problem": "T113 audio/HDF enablement usually spans drivers, board configuration, SoC defconfig or BSP, vendor HDF configuration, generated HCS/HCB assets, and board DTS/pin control.",
        "root_cause": "HDF audio wiring is distributed. A codec/DAI/DMA driver change alone is insufficient unless board and vendor configuration bind the device, route GPIO/PA pins, and include generated/runtime configuration consistently.",
        "fix": "Review and replay HDF audio changes as a chain: driver implementation, board/kernel/HDF files, SoC enablement, vendor hdf_config, and generated artifacts. Regenerate binary HDF configuration from source where possible.",
        "rule": "Never classify an audio/HDF bring-up as complete from one repo. Require driver + board + SoC + vendor configuration evidence before reusing the case.",
    },
    "soc_uapi_include_integration": {
        "id": "T113-SOC-UAPI-INCLUDE-INTEGRATION",
        "title": "SoC BSP UAPI include path integration",
        "problem": "SoC common libraries can silently include a stale private copy of kernel UAPI headers instead of the BSP-provided UAPI path, causing ABI drift between userspace wrappers and the kernel driver interface.",
        "root_cause": "The `libawion` evidence only shows a SoC/common BUILD.gn and cedar VE UAPI include-path adjustment; it does not prove full product/vendor/board binding.",
        "fix": "Prefer the authoritative `device/soc/allwinner/bsp/include/uapi` header path for SoC userspace wrappers, remove duplicate local UAPI headers when the diff does so, and verify the affected library still builds against the target BSP.",
        "rule": "Classify this evidence as SoC BSP/UAPI integration unless productdefine, vendor and device/board records are also cited.",
    },
    "reboot_efex_runtime_support": {
        "id": "T113-REBOOT-EFEX-RUNTIME-SUPPORT",
        "title": "Toybox reboot efex runtime command support",
        "problem": "Board recovery workflows may require a userspace reboot command path that can request Allwinner EFEX/FEL-style recovery mode, but this is runtime command support rather than bootloader provenance.",
        "root_cause": "The cited evidence is limited to `third_party/toybox/toys/other/reboot.c` and commit subject `toybox:reboot support efex`; no bootloader binaries, ARISC/DSP firmware, FEX, DTS or environment blobs are cited.",
        "fix": "Treat the patch as a toybox/runtime command adaptation. Validate accepted reboot arguments and target serial behaviour separately from bootloader or firmware binary provenance review.",
        "rule": "Do not label reboot/efex toybox evidence as a complete boot/firmware case unless bootloader, firmware and board configuration assets are also present in the evidence block.",
    },
    "cedar_ve_driver_uapi_fix": {
        "id": "T113-CEDAR-VE-DRIVER-UAPI-FIX",
        "title": "Cedar VE kernel driver and UAPI fix",
        "problem": "Cedar VE driver changes affect the kernel/userspace video-engine contract and should not be mixed with unrelated dirty HDF audio object files or generated build outputs.",
        "root_cause": "The committed evidence is a bounded BSP source patch under `drivers/ve/cedar-ve` plus `include/uapi/linux/cedar_ve_uapi.h`; dirty HDF audio `.o/.cmd` files are separate generated workspace risk.",
        "fix": "Review and replay the committed Cedar VE source/UAPI patch as one kernel/BSP driver case, then handle HDF audio generated artifacts through dirty/binary cleanup rather than this reusable fix.",
        "rule": "Keep Cedar VE driver/UAPI fixes evidence-bound to committed BSP source files; classify generated HDF audio objects and `.cmd` files as dirty workspace risk.",
    },
    "build_integration": {
        "id": "T113-BUILD-INTEGRATION",
        "title": "Build and product integration fixes",
        "problem": "Board/SoC ports require build graph inclusion in GN/product definitions; missing build metadata can look like source incompatibility.",
        "root_cause": "Imported code or board directories may not be visible to OpenHarmony build metadata until BUILD.gn, bundle/product definitions, or configuration files are updated.",
        "fix": "Check productdefine, BUILD.gn, bundle metadata, config.gni and toolchain assumptions before editing runtime code.",
        "rule": "For every imported module, prove that it is reachable from the intended product build target and that architecture/toolchain assumptions match the task profile.",
    },
}


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8", errors="ignore") as f:
        for line in f:
            if not line.strip():
                continue
            try:
                rows.append(json.loads(line))
            except Exception:
                continue
    return rows


def read_csv(path: Path, limit: int | None = None) -> list[dict[str, str]]:
    if not path.exists() or path.stat().st_size == 0:
        return []
    rows: list[dict[str, str]] = []
    with path.open(encoding="utf-8", errors="ignore", newline="") as f:
        for row in csv.DictReader(f):
            rows.append(row)
            if limit and len(rows) >= limit:
                break
    return rows


def safe_name(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", value).strip("_") or "case"


def recreate_generated_dir(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)


def file_path(item: dict[str, Any]) -> str:
    return str(item.get("file_path") or item.get("path") or "")


def is_noise_row(row: dict[str, Any]) -> bool:
    if row.get("origin_type") == "initial_import":
        return True
    if row.get("semantic_theme") in {"sync_noise", "initial_import"}:
        return True
    if row.get("noise_reason"):
        return True
    subject = str(row.get("subject") or "").lower()
    if "force sync sdk code" in subject:
        return True
    files = [file_path(f) for f in row.get("evidence_files") or []]
    if files and all(Path(p).name == ".gitattributes" for p in files):
        return True
    return False


def uniq_dicts(items: Iterable[dict[str, Any]], key: str = "file_path", limit: int = 20) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in items:
        val = str(item.get(key) or item.get("path") or item.get("evidence_id") or json.dumps(item, sort_keys=True))
        if val in seen:
            continue
        seen.add(val)
        out.append(item)
        if len(out) >= limit:
            break
    return out


def collect_related_dirty(theme: str, dirty_files: list[dict[str, Any]], limit: int = 12) -> list[dict[str, Any]]:
    needles = {
        "wifi_type_api_compat": ["wifi", "wpa", "supplicant", "dhcpcd", "bk7236"],
        "wifi_runtime_integration": ["wifi", "wpa", "supplicant", "dhcpcd", "bk7236", "libnl"],
        "hdf_audio_chain": ["audio", "hdf", "codec", "dai", "dma", "hcs", "hcb"],
        "product_board_soc_binding": ["product", "vendor/", "device/board", "device/soc", "config.json"],
        "boot_firmware_board_config": ["boot", "brandy", "u-boot", "spl", "arisc", "dsp", "fex", "dts"],
        "kernel_driver_adaptation": ["kernel", "driver", "drivers/", ".ko"],
        "soc_uapi_include_integration": ["libawion", "uapi", "cedar_ve_uapi", "device/soc/allwinner/common"],
        "reboot_efex_runtime_support": ["toybox", "reboot", "efex"],
        "cedar_ve_driver_uapi_fix": ["cedar-ve", "cedar_ve", "ve_plat", "device/soc/allwinner/bsp"],
        "build_integration": ["build.gn", "bundle.json", "productdefine", "config.gni"],
    }.get(theme, [])
    result = []
    for row in dirty_files:
        text = f"{row.get('repo_path','')} {row.get('path','')} {row.get('file_path','')} {row.get('dirty_content_class','')}".lower()
        if any(n in text for n in needles):
            result.append(row)
            if len(result) >= limit:
                break
    return result


def collect_related_binary(theme: str, binary_rows: list[dict[str, str]], limit: int = 12) -> list[dict[str, str]]:
    needles = {
        "wifi_type_api_compat": ["wifi", "wpa", "supplicant", "dhcpcd", "bk7236"],
        "wifi_runtime_integration": ["wifi", "wpa", "supplicant", "dhcpcd", "bk7236", "libnl"],
        "hdf_audio_chain": ["audio", "hdf", "codec", "hcs", "hcb"],
        "product_board_soc_binding": ["vendor/", "device/board", "device/soc"],
        "boot_firmware_board_config": ["boot", "brandy", "u-boot", "spl", "arisc", "dsp", "fex", ".bin"],
        "kernel_driver_adaptation": ["kernel", "driver", ".ko"],
        "soc_uapi_include_integration": ["libawion", "uapi", "cedar_ve_uapi", "device/soc/allwinner/common"],
        "reboot_efex_runtime_support": ["toybox", "reboot", "efex"],
        "cedar_ve_driver_uapi_fix": ["cedar-ve", "cedar_ve", "ve_plat", "device/soc/allwinner/bsp"],
        "build_integration": ["build", "prebuilt", "toolchain"],
    }.get(theme, [])
    result = []
    for row in binary_rows:
        text = f"{row.get('path','')} {row.get('file_path','')} {row.get('possible_usage','')} {row.get('analysis_note','')}".lower()
        if any(n in text for n in needles):
            result.append(row)
            if len(result) >= limit:
                break
    return result


def dirty_status(item: dict[str, Any]) -> str:
    return str(item.get("xy_status") or item.get("change_type") or item.get("change_status") or "unknown")


def case_markdown(idx: int, theme: str, rows: list[dict[str, Any]], dirty: list[dict[str, Any]], binaries: list[dict[str, str]]) -> str:
    spec = CASE_DEFS[theme]
    files: list[dict[str, Any]] = []
    diffs: list[str] = []
    for row in rows:
        files.extend(row.get("evidence_files") or [])
        diffs.extend([d for d in row.get("evidence_diffs") or [] if d])
    files = uniq_dicts(files, limit=18)
    diffs = list(dict.fromkeys(diffs))[:8]

    lines = [
        f"# Case {idx}: {spec['title']}",
        "",
        f"## Case ID",
        "",
        spec["id"],
        "",
        "## Evidence",
        "",
        "```yaml",
        "evidence:",
        "  commits:",
    ]
    for row in rows[:6]:
        lines.extend([
            f"    - repo_path: {row.get('repo_path')}",
            f"      commit_hash: {row.get('commit_hash')}",
            f"      evidence_id: {row.get('commit_evidence_id')}",
            f"      subject: {row.get('subject')}",
            f"      semantic_theme: {row.get('semantic_theme')}",
        ])
    lines.append("  files:")
    for item in files:
        lines.extend([
            f"    - repo_path: {item.get('repo_path')}",
            f"      file_path: {file_path(item)}",
            f"      evidence_id: {item.get('evidence_id')}",
        ])
    if diffs:
        lines.append("  diffs:")
        for diff in diffs:
            lines.append(f"    - {diff}")
    if dirty:
        lines.append("  dirty_records:")
        for item in dirty[:8]:
            lines.extend([
                f"    - repo_path: {item.get('repo_path')}",
                f"      file_path: {item.get('path') or item.get('file_path')}",
                f"      evidence_id: {item.get('evidence_id')}",
                f"      xy_status: {dirty_status(item)}",
                f"      change_type: {item.get('change_type') or 'unknown'}",
                "      relation: theme_matched_risk",
            ])
    if binaries:
        lines.append("  binary_records:")
        for item in binaries[:8]:
            lines.extend([
                f"    - path: {item.get('path') or item.get('file_path')}",
                f"      asset_kind: {item.get('asset_kind') or 'unknown'}",
                f"      sha256: {item.get('sha256')}",
                f"      possible_usage: {item.get('possible_usage')}",
                f"      runtime_dependency: {item.get('runtime_dependency')}",
                "      relation: theme_matched_risk",
            ])
    lines.extend([
        "```",
        "",
        "## Problem",
        "",
        spec["problem"],
        "",
        "## Root Cause",
        "",
        spec["root_cause"],
        "",
        "## Fix / Handling Pattern",
        "",
        spec["fix"],
        "",
        "## Reusable Rule",
        "",
        spec["rule"],
        "",
        "## Applicability",
        "",
        "- ARM-primary OpenHarmony board/SoC ports.",
        "- T113/T113-S3 style Allwinner board bring-up, especially where evidence paths match the listed files.",
        "- Cases where the same subsystem evidence chain exists in commit/file/dirty/binary records.",
        "",
        "## Non-Applicability",
        "",
        "- RISC-V-primary OpenHarmony distributions unless `task_profile.yaml` explicitly changes the runtime architecture.",
        "- Force-sync, .gitattributes-only, or initial-import commits without subsystem-specific evidence.",
        "- Binary/prebuilt reuse without sha256, source/provenance and redistribution review.",
        "",
        "## Verification",
        "",
        "- Re-run the target product build after applying the patch chain.",
        "- Check that each cited file still exists in the new target tree and belongs to the intended product/board/SoC path.",
        "- For runtime features, collect target serial/runtime logs before marking the rule as validated.",
        "",
        "## Risks",
        "",
        "- Evidence may mix committed history, dirty workspace records and binary assets; keep these categories separate when reusing the rule.",
        "- If a cited repository has unknown baseline or large SDK import history, verify whether the change is truly a porting fix rather than vendor import state.",
        "",
        "## Confidence",
        "",
        "medium-high when all cited commits/files/diffs are present; lower if reuse depends primarily on dirty workspace or binary assets.",
        "",
    ])
    return "\n".join(lines)


def write_patterns(kb: Path, dirty_files: list[dict[str, Any]], binary_rows: list[dict[str, str]], noisy_rows: list[dict[str, Any]]) -> None:
    patterns_dir = kb / "patterns"
    patterns_dir.mkdir(parents=True, exist_ok=True)
    (patterns_dir / "evidence_bound_case_pattern.md").write_text(
        "\n".join([
            "# Evidence-Bound Case Pattern",
            "",
            "A reusable case must have a real engineering problem, not just a repo/theme label.",
            "",
            "Required sections:",
            "- Case ID",
            "- Evidence with commits/files/diffs and optional dirty/binary records",
            "- Problem",
            "- Root Cause",
            "- Fix / Handling Pattern",
            "- Reusable Rule",
            "- Applicability",
            "- Non-Applicability",
            "- Verification",
            "- Risks",
            "- Confidence",
            "",
            "Exclusions:",
            "- initial import",
            "- force-sync subject",
            "- .gitattributes-only commits",
            "- pure generated/build outputs unless explicitly treated as dirty/binary risk",
            "",
        ]),
        encoding="utf-8",
    )
    dirty_examples = dirty_files[:20]
    dirty_lines = [
        "# Dirty Workspace Governance Pattern",
        "",
        "Dirty files are local workspace evidence, not committed porting history. They can suggest ongoing work, generated artifacts or local build outputs, but must be converted into clean commits or documented patches before becoming reusable knowledge.",
        "",
        "## Representative Dirty Evidence",
    ]
    for item in dirty_examples:
        dirty_lines.append(f"- `{item.get('repo_path')}/{item.get('path') or item.get('file_path')}` xy_status={dirty_status(item)} change_type={item.get('change_type') or 'unknown'} class={item.get('dirty_content_class') or item.get('classification')}")
    (patterns_dir / "dirty_workspace_governance_pattern.md").write_text("\n".join(dirty_lines) + "\n", encoding="utf-8")

    binary_examples = binary_rows[:25]
    bin_lines = [
        "# Binary / Prebuilt Provenance Pattern",
        "",
        "Binary assets require path, sha256, architecture, possible usage, introduced_by, license risk and redistribution risk. Do not present binary imports as source-level fixes.",
        "",
        "## Representative Binary Evidence",
    ]
    for item in binary_examples:
        bin_lines.append(f"- `{item.get('path') or item.get('file_path')}` kind={item.get('asset_kind') or 'unknown'} sha256={item.get('sha256')} usage={item.get('possible_usage')} runtime={item.get('runtime_dependency')}")
    (patterns_dir / "binary_prebuilt_provenance_pattern.md").write_text("\n".join(bin_lines) + "\n", encoding="utf-8")

    hdf_dirty = [
        item for item in dirty_files
        if any(token in f"{item.get('repo_path','')} {item.get('path','')} {item.get('file_path','')}".lower() for token in ["hdf", "audio", "codec", "dai", "dma"])
        and str(item.get("dirty_content_class") or "") in {"generated", "binary", "build_output", "unknown"}
    ]
    hdf_binary = [
        item for item in binary_rows
        if any(token in f"{item.get('path','')} {item.get('file_path','')}".lower() for token in ["hdf", "audio", "codec", "dai", "dma"])
        and str(item.get("asset_kind") or "") in {"generated_build_metadata", "object_file", "static_library", "generated_config", "unknown"}
    ]
    hdf_lines = [
        "# HDF Audio Generated Build Artifact Risk",
        "",
        "Generated HDF audio `.o`, `.a`, `.cmd`, HCB or untracked build outputs are dirty/binary risk evidence, not committed source adaptation by themselves.",
        "",
        "## Dirty Evidence Samples",
    ]
    for item in hdf_dirty[:30]:
        hdf_lines.append(f"- `{item.get('repo_path')}/{item.get('path') or item.get('file_path')}` xy_status={dirty_status(item)} class={item.get('dirty_content_class') or 'unknown'}")
    hdf_lines.extend(["", "## Binary / Generated Samples"])
    for item in hdf_binary[:30]:
        hdf_lines.append(f"- `{item.get('path') or item.get('file_path')}` kind={item.get('asset_kind') or 'unknown'} usage={item.get('possible_usage') or 'unknown'} sha256={item.get('sha256') or 'missing'}")
    hdf_lines.extend([
        "",
        "## Reuse Rule",
        "",
        "Before reusing HDF audio evidence, require source HCS/HDF/driver commits or regeneration recipes. Treat generated objects and `.cmd` metadata as cleanup/provenance work.",
    ])
    (patterns_dir / "hdf_audio_generated_build_artifact_risk.md").write_text("\n".join(hdf_lines) + "\n", encoding="utf-8")

    noise_lines = [
        "# Rejected / Noise Evidence Pattern",
        "",
        "The following evidence categories are intentionally excluded from reusable cases unless a later LLM/manual review proves subsystem-specific engineering value:",
        "",
        "- initial import",
        "- force sync SDK code",
        "- .gitattributes-only changes",
        "- broad SDK synchronization without board/SoC/driver/build substance",
        "",
        "## Sample Rejected Rows",
    ]
    for row in noisy_rows[:20]:
        noise_lines.append(f"- {row.get('commit_evidence_id')} `{row.get('repo_path')}` {row.get('commit_hash')} reason={row.get('noise_reason')} subject={row.get('subject')}")
    (patterns_dir / "rejected_noise_pattern.md").write_text("\n".join(noise_lines) + "\n", encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--stage-result")
    args = ap.parse_args()
    out = Path(args.out)
    kb = out / "04_knowledge_base"
    cases_dir = kb / "cases"
    patterns_dir = kb / "patterns"
    kb.mkdir(parents=True, exist_ok=True)
    recreate_generated_dir(cases_dir)
    recreate_generated_dir(patterns_dir)

    commit_analysis = read_jsonl(out / "03_semantic_analysis/commit_analysis.jsonl")
    dirty_files = read_jsonl(out / "01_raw_records/dirty_file_records.jsonl")
    binary_rows = read_csv(out / "01_raw_records/binary_asset_records.csv", limit=200000)

    reusable = [row for row in commit_analysis if row.get("is_case_candidate") and not is_noise_row(row)]
    noisy_rows = [row for row in commit_analysis if is_noise_row(row)]

    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in reusable:
        theme = row.get("semantic_theme") or "general_porting"
        if theme in CASE_DEFS:
            grouped[theme].append(row)

    case_paths: list[Path] = []
    idx = 1
    for theme in CASE_ORDER:
        rows = sorted(
            grouped.get(theme, []),
            key=lambda row: (-int(row.get("case_candidate_score") or 0), row.get("repo_path") or "", row.get("commit_hash") or ""),
        )
        if not rows:
            continue
        # keep the case evidence focused; do not combine unrelated repos beyond the theme evidence chain.
        selected = rows[:6]
        dirty = collect_related_dirty(theme, dirty_files)
        binaries = collect_related_binary(theme, binary_rows)
        spec = CASE_DEFS[theme]
        path = cases_dir / f"{idx:02d}_{safe_name(spec['id'].lower())}.md"
        path.write_text(case_markdown(idx, theme, selected, dirty, binaries), encoding="utf-8")
        case_paths.append(path)
        idx += 1
        if idx > 7:
            break

    write_patterns(kb, dirty_files, binary_rows, noisy_rows)

    (kb / "path_module_index.md").write_text(
        "\n".join([
            "# Path / Module Index",
            "",
            "| Path Prefix | Module Meaning | Evidence Handling |",
            "| --- | --- | --- |",
            "| `device/board/seed/t113_evb1` | Board configuration, bootloader overlays, kernel/HDF board files | committed and dirty evidence; verify board identity |",
            "| `device/board/seed/t113_auto` | Alternate/related T113 board target | compare against `t113_evb1`; avoid accidental cross-board reuse |",
            "| `device/soc/allwinner` | Allwinner SoC BSP, common libraries, WiFi/platform integration | committed source plus binary/provenance checks |",
            "| `drivers` | HDF/peripheral and kernel-side driver work | separate committed driver patches from dirty/generated files |",
            "| `vendor/seed/t113_evb1` | Product/vendor configuration and generated HDF blobs | regenerate generated HCB/HCS where possible |",
            "| `third_party/wpa_supplicant` | WiFi runtime component | verify source patch and runtime binary provenance |",
            "| `prebuilts` | toolchain/build-time prebuilts | treat as environment/provenance risk, not source fix |",
            "| `brandy` / `bootloader` | boot/SPL/firmware configuration | require binary hash and source recipe where possible |",
            "",
        ]),
        encoding="utf-8",
    )
    (kb / "board_soc_porting_rules.md").write_text(
        "\n".join([
            "# Board/SoC Porting Rules",
            "",
            "1. Treat `00_config/task_profile.yaml` as authoritative for scenario type. For T113, OpenHarmony runs on ARM; RISC-V/DSP/C906/ARISC artifacts are auxiliary firmware/context unless a formal scope change is produced.",
            "2. Split evidence into initial import, post-import commits, dirty workspace, and binary/prebuilt assets before creating reusable knowledge.",
            "3. Exclude force-sync, .gitattributes-only and pure initial-import commits from cases. Put them in rejected/noise patterns instead.",
            "4. WiFi cases must show source/config evidence and, if runtime binaries are involved, binary provenance evidence.",
            "5. HDF audio cases must show a chain across driver, board/SoC and vendor/HDF configuration; one isolated commit is not enough to claim full bring-up.",
            "6. Product/board/SoC cases must verify productdefine/vendor/device/SoC binding before debugging subsystem behaviour.",
            "7. SoC UAPI include-path fixes are not full product/board/SoC binding unless productdefine, vendor and board evidence is cited.",
            "8. Reboot/EFEX command support is runtime userspace behaviour; do not promote it to bootloader/firmware provenance without binary/config evidence.",
            "9. Binary/prebuilt evidence must include path, asset_kind and sha256; `.gitattributes` is metadata and `.cmd` is generated build metadata.",
            "10. Dirty workspace evidence is not committed history. Preserve `xy_status` and `change_type`, then convert WIP to clean commits or document it as risk.",
            "",
        ]),
        encoding="utf-8",
    )
    source_workarounds = ""
    source_workaround_path = out / "03_semantic_analysis/workaround_items.md"
    if source_workaround_path.exists():
        source_workarounds = source_workaround_path.read_text(encoding="utf-8", errors="ignore")
    (kb / "workaround_items.md").write_text(
        "# Knowledge Base Workaround Items\n\n" + source_workarounds,
        encoding="utf-8",
    )

    outputs = [
        "04_knowledge_base/cases/",
        "04_knowledge_base/patterns/",
        "04_knowledge_base/path_module_index.md",
        "04_knowledge_base/board_soc_porting_rules.md",
        "04_knowledge_base/workaround_items.md",
    ]
    blocking: list[str] = []
    if not case_paths:
        blocking.append("No reusable cases generated after filtering sync/import/noise records.")
    result = {
        "stage": "05_case_kb_builder",
        "status": "blocked" if blocking else "passed",
        "summary": f"Generated {len(case_paths)} selective evidence-bound cases, patterns, and KB support files.",
        "input_files_read": [
            "00_config/task_profile.yaml",
            "01_raw_records/commit_records.jsonl",
            "01_raw_records/file_change_records.jsonl",
            "01_raw_records/dirty_file_records.jsonl",
            "01_raw_records/binary_asset_records.csv",
            "03_semantic_analysis/commit_analysis.jsonl",
            "03_semantic_analysis/repo_analysis/",
            "03_semantic_analysis/subsystem_analysis/",
            "03_semantic_analysis/risk_items.md",
            "03_semantic_analysis/workaround_items.md",
        ],
        "output_files_written": outputs,
        "blocking_issues": blocking,
        "non_blocking_issues": [
            f"Excluded {len(noisy_rows)} sync/import/noise commit analyses from reusable cases.",
        ],
        "next_stage_inputs": outputs,
        "case_count": len(case_paths),
    }
    if args.stage_result:
        Path(args.stage_result).write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
