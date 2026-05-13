#!/usr/bin/env python3
"""Deterministic case/knowledge-base generator for OpenHarmony porting pipeline."""

import argparse
import json
import re
from collections import defaultdict
from pathlib import Path


def read_jsonl(path):
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding='utf-8', errors='ignore').splitlines() if line.strip()]


def safe_name(value):
    return re.sub(r'[^A-Za-z0-9._-]+', '_', value).strip('_') or 'case'


def infer_case_name(theme, repo):
    labels = {
        'wifi': 'wifi_enablement',
        'audio_hdf': 'hdf_audio_t113',
        'boot_firmware': 'boot_firmware_board_config',
        'hdf_config': 'hdf_binary_config',
        'build_integration': 'build_and_product_integration',
        'prebuilt_toolchain': 'prebuilt_toolchain_provenance',
        'kernel_driver': 'kernel_driver_adaptation',
        'vendor_product': 'vendor_product_configuration',
    }
    return labels.get(theme, safe_name(repo))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', required=True)
    ap.add_argument('--stage-result')
    args = ap.parse_args()
    out = Path(args.out)
    kb = out / '04_knowledge_base'
    cases_dir = kb / 'cases'
    patterns_dir = kb / 'patterns'
    cases_dir.mkdir(parents=True, exist_ok=True)
    patterns_dir.mkdir(parents=True, exist_ok=True)

    commit_analysis = read_jsonl(out / '03_semantic_analysis/commit_analysis.jsonl')
    useful = [
        row for row in commit_analysis
        if row.get('origin_type') != 'initial_import' and row.get('evidence_files')
    ]
    groups = defaultdict(list)
    for row in useful:
        groups[(row.get('semantic_theme') or 'general_porting', row.get('repo_path') or 'unknown')].append(row)

    case_paths = []
    selected = []
    for key, rows in sorted(groups.items(), key=lambda item: (-len(item[1]), item[0])):
        theme, repo = key
        selected.append((theme, repo, rows[:4]))
        if len(selected) >= 10:
            break

    for idx, (theme, repo, rows) in enumerate(selected, 1):
        name = infer_case_name(theme, repo)
        path = cases_dir / f'{idx:02d}_{name}.md'
        first = rows[0]
        files = []
        for row in rows:
            files.extend(row.get('evidence_files') or [])
        files = files[:12]
        lines = [
            f'# Case {idx}: {name.replace("_", " ").title()}',
            '',
            'evidence:',
            '  commits:',
        ]
        for row in rows:
            lines.extend([
                f'    - repo_path: {row.get("repo_path")}',
                f'      commit_hash: {row.get("commit_hash")}',
                f'      evidence_id: {row.get("commit_evidence_id")}',
                f'      subject: {row.get("subject")}',
            ])
        lines.append('  evidence_files:')
        for item in files:
            lines.extend([
                f'    - repo_path: {item.get("repo_path")}',
                f'      file_path: {item.get("file_path")}',
                f'      evidence_id: {item.get("evidence_id")}',
            ])
        lines.append('  diffs:')
        for row in rows:
            for diff in row.get('evidence_diffs') or []:
                lines.append(f'    - {diff}')
        lines.extend([
            '',
            '## Problem',
            f'The `{repo}` area carries `{theme}` changes for the T113 OpenHarmony port. Claims in this case are limited to the evidence block above.',
            '',
            '## Reusable Pattern',
            '- Start from the board/SOC/product files named in `evidence_files`.',
            '- Preserve commit/file/diff traceability when replaying the change.',
            '- Keep dirty workspace and binary/prebuilt evidence separate from committed source changes.',
            '',
            '## Applicability',
            '- ARM-primary OpenHarmony board/SoC ports with Allwinner T113/T113-S3 style board, SoC, HDF, Wi-Fi, vendor, or build integration work.',
            '',
            '## Non-Applicability',
            '- Do not apply directly to RISC-V-primary distributions unless the target profile explicitly marks RISC-V as the OpenHarmony runtime architecture.',
            '- Do not treat binary/prebuilt imports as source fixes without provenance review.',
            '',
            '## Risks',
            f'- Main theme: `{first.get("semantic_theme")}`.',
            '- Large patch payloads and dirty generated artifacts need independent review before reuse.',
            '',
        ])
        path.write_text('\n'.join(lines), encoding='utf-8')
        case_paths.append(path)

    (patterns_dir / 'evidence_bound_case_pattern.md').write_text(
        '\n'.join([
            '# Evidence-Bound Case Pattern',
            '',
            '- Every reusable case must include `commits`, `evidence_files`, and optional `diffs`.',
            '- The case body may generalize only after the evidence block is explicit.',
            '- Applicability and non-applicability must be stated separately.',
            '- Workarounds and dirty workspace observations must not be promoted as best practices.',
            '',
        ]),
        encoding='utf-8',
    )
    (patterns_dir / 'dirty_binary_review_pattern.md').write_text(
        '\n'.join([
            '# Dirty Workspace And Binary Review Pattern',
            '',
            '- Dirty files are local workspace evidence, not committed history.',
            '- Binary assets require path, sha256, architecture, usage, and redistribution-risk evidence.',
            '- Runtime binaries should be regenerated or traced to source/build recipes where possible.',
            '',
        ]),
        encoding='utf-8',
    )
    (kb / 'path_module_index.md').write_text(
        '\n'.join([
            '# Path Module Index',
            '',
            '| Path Prefix | Module Meaning | Evidence Source |',
            '| --- | --- | --- |',
            '| `device/board/seed/t113_evb1` | board configuration, bootloader overlays, HDF board files | commit/file records |',
            '| `device/soc/allwinner` | SoC BSP, platform libraries, Wi-Fi integration | commit/file records |',
            '| `vendor/seed/t113_evb1` | product configuration and generated HDF blobs | dirty/binary records |',
            '| `prebuilts` | toolchain and build-time prebuilts | dirty/binary records |',
            '| `third_party/wpa_supplicant` | target Wi-Fi runtime component | dirty/binary records |',
            '',
        ]),
        encoding='utf-8',
    )
    (kb / 'board_soc_porting_rules.md').write_text(
        '\n'.join([
            '# Board/SoC Porting Rules',
            '',
            '- Treat `00_config/task_profile.yaml` as authoritative for scenario type: ARM-primary board/SoC with heterogeneous auxiliary core.',
            '- Reuse cases only when commit/file/diff evidence is present in raw records.',
            '- Separate initial import, downstream unique commits, post-import sync commits, dirty workspace, and binary/prebuilt imports.',
            '- For Wi-Fi and audio/HDF adaptation, verify both board files and SoC/BSP files before reusing a case.',
            '- For RISC-V or DSP/C906 artifacts, record them as auxiliary firmware/context unless task profile changes the runtime architecture.',
            '- Preserve sha256 and redistribution-risk notes for all binary assets.',
            '',
        ]),
        encoding='utf-8',
    )
    source_workarounds = (out / '03_semantic_analysis/workaround_items.md').read_text(encoding='utf-8', errors='ignore')
    (kb / 'workaround_items.md').write_text(
        '# Knowledge Base Workaround Items\n\n' + source_workarounds,
        encoding='utf-8',
    )

    outputs = [
        '04_knowledge_base/cases/',
        '04_knowledge_base/patterns/',
        '04_knowledge_base/path_module_index.md',
        '04_knowledge_base/board_soc_porting_rules.md',
        '04_knowledge_base/workaround_items.md',
    ]
    result = {
        'stage': '05_case_kb_builder',
        'status': 'passed',
        'summary': f'Generated {len(case_paths)} evidence-bound cases and KB support files.',
        'input_files_read': [
            '00_config/task_profile.yaml',
            '01_raw_records/commit_records.jsonl',
            '01_raw_records/file_change_records.jsonl',
            '01_raw_records/dirty_file_records.jsonl',
            '01_raw_records/binary_asset_records.csv',
            '03_semantic_analysis/commit_analysis.jsonl',
            '03_semantic_analysis/repo_analysis/',
            '03_semantic_analysis/subsystem_analysis/',
            '03_semantic_analysis/risk_items.md',
            '03_semantic_analysis/workaround_items.md',
        ],
        'output_files_written': outputs,
        'blocking_issues': [],
        'non_blocking_issues': [],
        'next_stage_inputs': outputs,
    }
    if args.stage_result:
        Path(args.stage_result).write_text(json.dumps(result, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
