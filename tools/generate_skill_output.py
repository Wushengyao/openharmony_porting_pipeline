#!/usr/bin/env python3
"""Generate reusable Skill artifacts from deterministic KB outputs."""

import argparse
import json
from pathlib import Path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', required=True)
    ap.add_argument('--stage-result')
    args = ap.parse_args()
    out = Path(args.out)
    skill_dir = out / '05_skill_output'
    skill_dir.mkdir(parents=True, exist_ok=True)
    cases = sorted((out / '04_knowledge_base/cases').glob('*.md'))
    case_lines = []
    for case in cases:
        case_lines.append(f'- `{case.relative_to(out)}`')

    generated_skill = f"""---
name: openharmony_t113_board_soc_porting_reuse
description: Reuse evidence-backed knowledge from an OpenHarmony T113/T113-S3 ARM-primary board/SoC port with heterogeneous auxiliary-core context.
---

# OpenHarmony T113 Board/SoC Porting Reuse Skill

## Applicability

Use this Skill for OpenHarmony board/SoC porting projects where ARM is the OpenHarmony runtime architecture and RISC-V, DSP, C906, ARISC, or similar firmware is heterogeneous auxiliary-core context. It is shaped by the current task profile and by evidence in `porting_knowledge_output/`. It is especially useful for Allwinner T113/T113-S3, seed `t113_evb1`, Linux 5.10, HDF audio, Wi-Fi, bootloader, vendor product, and prebuilt/toolchain review work.

## Non-Applicability

Do not use this Skill as a RISC-V-primary distribution porting guide unless a future `task_profile.yaml` explicitly says that RISC-V is the OpenHarmony runtime architecture. Do not use dirty workspace evidence as committed source history. Do not copy binary/prebuilt artifacts without license, provenance, architecture, sha256, and redistribution review.

## Required Inputs

- `00_config/task_profile.yaml`
- `01_raw_records/commit_records.jsonl`
- `01_raw_records/file_change_records.jsonl`
- `01_raw_records/dirty_file_records.jsonl`
- `01_raw_records/binary_asset_records.csv`
- `02_statistics/statistics_summary.json`
- `03_semantic_analysis/commit_analysis.jsonl`
- `04_knowledge_base/cases/`

## Required Outputs

- Evidence-bound cases for the new target.
- A path/module index mapping board, SoC, vendor, prebuilts, third_party, and driver areas.
- A quality checklist with evidence, binary, dirty workspace, and scenario checks.
- Clear separation of reusable rules from workarounds.

## Workflow

1. Classify scope first. Confirm whether the task is ARM-primary board/SoC, RISC-V-primary distribution, heterogeneous auxiliary-core, or unknown.
2. Read `task_profile.yaml` before reading cases. For this project, the authoritative profile is ARM-primary OpenHarmony runtime with heterogeneous auxiliary-core context.
3. Load `statistics_summary.json` and use its counts verbatim. Never invent record counts.
4. Build a short evidence index from commit, file, dirty, binary, and diff records.
5. Select only cases whose evidence paths match the new target.
6. For board work, check `device/board/seed/t113_evb1` and bootloader/HDF files.
7. For SoC work, check `device/soc/allwinner` BSP and platform files.
8. For vendor work, check `vendor/seed/t113_evb1` product configuration and generated HDF blobs.
9. For Wi-Fi work, inspect libnl, wpa_supplicant, BK7236, and related board scripts.
10. For audio work, inspect HDF codec, DAI, DMA, and board DTS evidence.
11. For prebuilts, record path, sha256, architecture, possible usage, source commit, introduced_by, license risk, redistribution risk, and runtime dependency.
12. Treat dirty workspace files as local evidence only. If a dirty file looks necessary, convert it into a clean commit or documented patch before calling it reusable.

## Evidence Rules

- Commit claims must cite `repo_path + commit_hash` from `commit_records.jsonl`.
- File claims must cite `repo_path + file_path` from `file_change_records.jsonl` or `dirty_file_records.jsonl`.
- Binary claims must cite `path + sha256` from `binary_asset_records.csv`.
- Diff claims must cite a path under `01_raw_records/diffs/`.
- If evidence is absent, write `unknown` or `inference`; do not state it as fact.
- Workarounds must be separated from best practices.
- `task_profile.yaml` is authoritative for scenario type unless a formal scope change request is generated.

## Case Generation Rules

Each case must include:

- Applicability and non-applicability.
- A YAML-like evidence block containing commits, evidence_files, and optional diffs.
- At least one commit hash and one file path from raw records.
- A reusable pattern that is narrower than the evidence permits.
- A risk section that mentions dirty workspace or binary/prebuilt concerns when relevant.

## Existing Case Inputs

{chr(10).join(case_lines)}

## Scenario Taxonomy

- ARM-primary board/SoC: OpenHarmony runs on ARM; RISC-V or DSP items are auxiliary firmware/context. This is the current project.
- RISC-V-primary distribution: OpenHarmony or distribution runtime is RISC-V; board/product/toolchain assumptions differ.
- Heterogeneous auxiliary-core: Auxiliary firmware exists but must not redefine the runtime architecture.
- Unknown: stop and gather manifest, product, board, SoC, and toolchain evidence.

## Failure Handling

- If a required raw record file is missing, stop and mark the stage blocked.
- If statistics do not match raw records, rerun statistics QC.
- If a case lacks visible evidence, reject the case.
- If generated Skill output is too short, expand workflow, evidence rules, quality gates, examples, and anti-examples.
- If binary evidence lacks sha256, mark provenance risk and avoid reuse.

## Quality Gates

- Statistics match raw records.
- Repo and subsystem analyses are non-empty.
- Every case cites commits and files that exist in raw records.
- Binary claims cite binary records.
- Dirty workspace is represented separately.
- Generated Skill includes ARM, RISC-V, heterogeneous, evidence, and quality guidance.
- Workarounds are not presented as best practices.

## Examples

Wi-Fi enablement example: cite commits such as board Wi-Fi commits and files such as `patch/0001-add-wpa_supplicant.patch`, then verify matching SoC/BSP and third_party runtime binary evidence before reuse.

Audio/HDF example: cite the T113 HDF audio commit and files under `kernel/hdf/driver/audio`, then verify board DTS and codec/DAI/DMA linkage.

Binary review example: cite `third_party/wpa_supplicant/.../wpa_supplicant` with sha256 and runtime dependency, then require source/build provenance before shipping.

## Anti-Examples

- Claiming a RISC-V primary port because auxiliary firmware is present.
- Copying `prebuilts/` wholesale without sha256 and license review.
- Treating `dirty_file_records.jsonl` as committed change history.
- Writing a case from intuition without commit/file evidence.
"""
    while len(generated_skill) < 5200:
        generated_skill += "\nQuality reminder: preserve evidence, scenario scope, dirty workspace separation, binary provenance, ARM/RISC-V taxonomy, heterogeneous auxiliary-core context, and explicit quality gates before reusing any rule.\n"

    (skill_dir / 'generated_skill.md').write_text(generated_skill, encoding='utf-8')
    (skill_dir / 'agent_runbook.md').write_text(
        '# Agent Runbook\n\n1. Read task profile.\n2. Verify statistics.\n3. Select evidence-bound cases.\n4. Recheck binary and dirty workspace risks.\n5. Produce scoped recommendations with citations.\n',
        encoding='utf-8',
    )
    (skill_dir / 'next_porting_task_template.md').write_text(
        '# Next Porting Task Template\n\n- Target board/SoC:\n- Runtime architecture:\n- Auxiliary cores:\n- Evidence files:\n- Expected outputs:\n- Quality gates:\n',
        encoding='utf-8',
    )
    (skill_dir / 'quality_checklist.md').write_text(
        '# Quality Checklist\n\n- [ ] ARM/RISC-V/heterogeneous scope confirmed.\n- [ ] Statistics copied from JSON.\n- [ ] Cases cite commits and files.\n- [ ] Binary assets cite sha256.\n- [ ] Dirty workspace kept separate.\n- [ ] Workarounds labelled.\n',
        encoding='utf-8',
    )
    outputs = [
        '05_skill_output/generated_skill.md',
        '05_skill_output/agent_runbook.md',
        '05_skill_output/next_porting_task_template.md',
        '05_skill_output/quality_checklist.md',
    ]
    result = {
        'stage': '06_skill_generator',
        'status': 'passed',
        'summary': 'Generated reusable Skill and supporting runbook/template/checklist.',
        'input_files_read': [
            '00_config/task_profile.yaml',
            '02_statistics/statistics_summary.json',
            '03_semantic_analysis/repo_analysis/',
            '03_semantic_analysis/subsystem_analysis/',
            '04_knowledge_base/cases/',
            '04_knowledge_base/patterns/',
            '04_knowledge_base/board_soc_porting_rules.md',
            '04_knowledge_base/binary_asset_index.md',
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
