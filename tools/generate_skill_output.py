#!/usr/bin/env python3
"""Generate reusable Skill artifacts from KB outputs.

This deterministic fallback now generates full supporting files instead of tiny
summaries.  LLM execution is still preferred for stage 06, but this script
should produce useful artifacts when deterministic mode is explicitly enabled.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def read_text(path: Path, default: str = "") -> str:
    return path.read_text(encoding="utf-8", errors="ignore") if path.exists() else default


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--stage-result")
    args = ap.parse_args()
    out = Path(args.out)
    skill_dir = out / "05_skill_output"
    skill_dir.mkdir(parents=True, exist_ok=True)

    stats = {}
    stats_path = out / "02_statistics/statistics_summary.json"
    if stats_path.exists():
        try:
            stats = json.loads(stats_path.read_text(encoding="utf-8"))
        except Exception:
            stats = {}
    cases = sorted((out / "04_knowledge_base/cases").glob("*.md"))
    case_lines = [f"- `{case.relative_to(out)}`" for case in cases]
    rules = read_text(out / "04_knowledge_base/board_soc_porting_rules.md")
    binary_index_exists = (out / "04_knowledge_base/binary_asset_index.md").exists()

    generated_skill = f"""---
name: openharmony_board_soc_porting_reuse
description: Evidence-bound assistant for reusing OpenHarmony board/SoC porting knowledge across ARM-primary, RISC-V-primary, and heterogeneous auxiliary-core scenarios.
---

# OpenHarmony Board/SoC Porting Reuse Skill

## 1. Applicability

Use this Skill to help analyze, plan, replay, or audit OpenHarmony board/SoC porting work when prior project evidence exists in `porting_knowledge_output/`. This Skill is not T113-only: concrete board, SoC, product, runtime architecture, and auxiliary-core details must come from `task_profile.yaml`, raw records, evidence-backed cases, and optional operator context.

This Skill is suitable for:

- ARM-primary OpenHarmony board/SoC bring-up.
- Product, board, SoC, vendor, kernel, driver, boot, firmware and HDF integration across supported OpenHarmony board/SoC scenarios.
- WiFi, HDF audio, bootloader, firmware, binary/prebuilt and dirty workspace review.
- RISC-V-primary projects only after `task_profile.yaml` marks RISC-V as the OpenHarmony runtime architecture.
- Knowledge reuse where every claim can cite commit, file, dirty, binary or diff evidence.

## 2. Non-Applicability

Do not use this Skill to claim a RISC-V primary port merely because auxiliary firmware or RISC-V-related blobs are present. Do not treat initial import, force-sync SDK commits, `.gitattributes`-only changes, dirty workspace files, or binary imports as reusable source fixes. Do not copy prebuilts or firmware into another project without sha256, provenance, architecture, license and redistribution review.

## 3. Operating Modes

### All-Auto Mode

Run from existing artifacts without asking the user for extra information. Unknown project background, baseline boundaries, porting commit ranges, dirty workspace intent, and binary provenance must remain `unknown` unless evidence exists.

### Human-Collaboration Mode

If `00_config/operator_context.md` or `.json` exists, read it before planning or reusing cases. Treat it as user-supplied hints, not repository evidence. It may clarify:

- current project background;
- before/after porting boundaries;
- known porting and non-porting commits;
- dirty workspace policy;
- binary/prebuilt provenance;
- knowledge priorities for the final Skill.

If the user does not know an answer, preserve `unknown`. If operator context conflicts with manifests, commits, diffs, or raw records, record the conflict and prefer verifiable evidence.

### Interaction Language

When asking the user for collaboration context or follow-up clarification, use Chinese by default. Unknown or uncertain answers are acceptable and should be represented as `unknown` rather than blocking execution.

### Chinese Result Views

Use the Chinese summaries when presenting high-level progress or review results to a human:

- `_stage_results/<stage>.zh.md`
- `06_audit/stage_results.zh.md`
- `06_audit/pipeline_summary.zh.md`

The Chinese Markdown files are human-facing views. JSON stage results and statistics files remain the machine-readable source of truth.

## 4. Required Inputs

- `00_config/task_profile.yaml`
- `00_config/operator_context.md` or `.json` if present
- `01_raw_records/commit_records.jsonl`
- `01_raw_records/file_change_records.jsonl`
- `01_raw_records/dirty_file_records.jsonl`
- `01_raw_records/binary_asset_records.csv`
- `01_raw_records/diffs/`
- `02_statistics/statistics_summary.json`
- `03_semantic_analysis/commit_analysis.jsonl`
- `03_semantic_analysis/repo_analysis/`
- `03_semantic_analysis/subsystem_analysis/`
- `04_knowledge_base/cases/`
- `04_knowledge_base/patterns/`

## 5. Expected Outputs

- A target-specific porting plan with evidence citations.
- A case reuse decision for each relevant knowledge case.
- Patch or investigation recommendations scoped to the target board/SoC.
- Binary/prebuilt provenance checklist.
- Dirty workspace cleanup plan.
- Risk and workaround list separated from reusable rules.

## 6. Source of Truth

Statistics must come from `02_statistics/statistics_summary.json` only. For this run, available counts include:

```json
{json.dumps({k: stats.get(k) for k in sorted(stats) if k.endswith('_count') or k in ['repo_count', 'changed_repo_count']}, ensure_ascii=False, indent=2)}
```

If any report or case disagrees with these counts, treat the report/case as suspect and rerun statistics QC.

## 7. Scenario Taxonomy

### ARM-primary board/SoC

OpenHarmony runs on ARM. Board, SoC, vendor, driver, HDF, kernel, bootloader and product binding are the primary focus. RISC-V/DSP/C906/ARISC assets are auxiliary firmware or heterogeneous context. T113-style projects fall here only when the task profile and evidence show ARM-primary runtime.

### RISC-V-primary distribution

OpenHarmony or the derived distribution runs on RISC-V. Toolchain, target CPU, ABI, OpenSBI/U-Boot, kernel RISC-V support, third_party architecture compatibility and RISC-V runtime validation become primary concerns.

### Heterogeneous auxiliary-core

Auxiliary firmware exists but does not define the OpenHarmony runtime architecture. Treat auxiliary core assets as firmware/provenance/IPC risks unless evidence shows OpenHarmony itself runs there.

### Unknown

Stop and collect manifest, product, board, SoC, kernel, toolchain and runtime-core evidence before reusing cases.

## 8. Execution Workflow

1. Read `task_profile.yaml`. Do not override it without a formal scope-change request.
2. Read `operator_context` if present; preserve unknowns and conflicts explicitly.
3. Load `statistics_summary.json` and copy counts exactly.
4. Read only the cases whose evidence paths match the new target.
5. For each case, verify that every cited commit/file/diff/binary/dirty record exists in raw records.
6. Exclude cases based on force-sync, `.gitattributes`-only, initial import, or generic SDK sync evidence.
7. Map target paths: productdefine → vendor → device/board → device/soc → kernel/HDF → runtime binary/prebuilt.
8. Decide whether each case is directly reusable, reusable with adaptation, risk-only, or not applicable.
9. For reusable cases, generate a narrow action plan with validation commands and expected logs.
10. For dirty workspace evidence, ask for a clean commit or patch before treating it as landed history.
11. For binary/prebuilt evidence, require sha256/provenance/license/redistribution review before reuse.
12. Separate best practices from workarounds.
13. Produce final recommendations with evidence citations.
14. When presenting progress or final status to users, include the Chinese stage/overall summary paths when they exist.

## 9. Evidence Rules

- Commit claims cite `repo_path + commit_hash` from `commit_records.jsonl`.
- File claims cite `repo_path + file_path` from `file_change_records.jsonl` or `dirty_file_records.jsonl`.
- Binary claims cite `path + asset_kind + sha256` from `binary_asset_records.csv`.
- Diff claims cite paths under `01_raw_records/diffs/`.
- If evidence is absent, write `unknown` or `inference`.
- Dirty workspace records are local WIP evidence, not committed history; preserve `xy_status` and `change_type`.
- Workarounds must be labelled and must not be promoted to best practice.

## 10. Case Reuse Rules

Each reusable case must include:

- Problem and symptom.
- Root cause.
- Fix or handling pattern.
- Evidence block with commits/files/diffs and optional dirty/binary records.
- Applicability and non-applicability.
- Verification steps.
- Risks and confidence.

Reject or downgrade cases when:

- the only evidence is force-sync SDK code;
- all cited files are `.gitattributes`;
- title/theme does not match evidence paths;
- binary evidence lacks sha256;
- `.gitattributes` is used as binary/firmware evidence or `.cmd` is treated as an object/static library;
- the case confuses ARM-primary with RISC-V-primary scope.

## 11. Current Case Inputs

{chr(10).join(case_lines) if case_lines else '- No cases were generated; rerun stage 05.'}

## 12. Board/SoC Rules Snapshot

```text
{rules[:5000] if rules else 'No board_soc_porting_rules.md found.'}
```

## 13. Tool Commands

```bash
# Validate raw records and statistics
python3 tools/validate_stage.py --workspace "$PWD" --out porting_knowledge_output --stage 03_statistics_qc --stage-result porting_knowledge_output/_stage_results/03_statistics_qc.json

# Rerun semantic analysis with LLM stage by default
bash tools/run_stage.sh "$PWD" 04_semantic_analyzer

# Use deterministic fallback only when explicitly desired
DETERMINISTIC_SEMANTIC_ANALYZER=1 bash tools/run_stage.sh "$PWD" 04_semantic_analyzer

# Audit final outputs
bash tools/run_stage.sh "$PWD" 07_final_auditor
```

## 14. Failure Handling

- Missing raw record file: stop and rerun raw extraction.
- Statistics mismatch: rerun statistics QC and do not generate cases.
- Empty repo/subsystem analysis: rerun semantic analyzer.
- Template-like cases or mismatched themes: reject cases and rerun case builder with stricter filtering.
- Generated runbook/template/checklist too short: rerun skill generator.
- Auditor reports blocking issues: do not accept the knowledge package.

## 15. Quality Gates

- Raw record counts match statistics.
- Repo and subsystem analyses are non-empty.
- At least one reusable case cites valid commit/file evidence.
- Cases are not based on force-sync, `.gitattributes`-only or initial-import evidence.
- Skill output includes scenario taxonomy, evidence rules, workflow, failure handling, quality gates, examples and anti-examples.
- `agent_runbook.md`, `next_porting_task_template.md`, and `quality_checklist.md` are detailed enough for a fresh agent to operate without chat history.
- Binary asset index present: {binary_index_exists}.

## 16. Examples

### WiFi compatibility

If a case cites WiFi commits that replace non-standard type aliases or adjust libc/toolbox assumptions, reuse it only after checking the target sysroot headers and runtime command behaviour. Verify build success and target-side WiFi service startup.

### HDF audio chain

If a case cites audio/HDF files, require driver, board/SoC and vendor/HDF configuration evidence. A single codec commit without board/vendor binding is incomplete.

### Binary provenance

If a bootloader or firmware blob is involved, record path, sha256, architecture, possible usage, source/introduced_by, license risk and redistribution risk before copying it.

## 17. Anti-Examples

- Claiming T113 is RISC-V-primary because auxiliary firmware exists.
- Creating an HDF audio case from `.gitattributes` or generic SDK sync evidence.
- Calling dirty workspace files committed history.
- Shipping `prebuilts/` wholesale without provenance review.
- Writing a reusable rule from a commit subject without file/diff evidence.
"""

    runbook = """# Agent Runbook: OpenHarmony Board/SoC Porting Reuse

## 1. Start

1. Open `00_config/task_profile.yaml`.
2. Confirm runtime architecture, auxiliary cores, SoC, board, kernel and system type.
3. If `00_config/operator_context.md` exists, read it as optional human-provided hints. Keep unknown answers as unknown and do not treat hints as evidence.
4. Load `02_statistics/statistics_summary.json`; do not invent or recalculate report numbers manually.
5. Read `04_knowledge_base/cases/` only after confirming the scenario.

## 2. Decision Flow

- If the target is ARM-primary, prioritize product/board/vendor/SoC, kernel/HDF, WiFi, audio, bootloader and binary/prebuilt review.
- If the target is RISC-V-primary, switch to architecture/toolchain/kernel/third_party runtime checks and do not reuse ARM board assumptions directly.
- If the target is heterogeneous auxiliary-core, keep auxiliary firmware separate from OpenHarmony runtime architecture.

## 3. Evidence Handling

For every recommendation, attach one of:

- commit evidence: `repo_path + commit_hash`;
- file evidence: `repo_path + file_path`;
- dirty evidence: dirty record path, `xy_status` and `change_type`;
- binary evidence: path, `asset_kind` and sha256;
- diff evidence: patch path under `01_raw_records/diffs/`.

## 4. Case Use

1. Reject cases whose evidence is only initial import, force sync or `.gitattributes`.
2. Check that case title matches evidence paths and subjects.
3. Reclassify binary-heavy cases as provenance/risk items unless source/build recipe exists; `.gitattributes` is metadata and `.cmd` is generated build metadata.
4. Mark every rule as directly reusable, reusable with adaptation, risk-only, or not applicable.

## 5. Validation Commands

```bash
bash tools/run_stage.sh "$PWD" 03_statistics_qc
bash tools/run_stage.sh "$PWD" 04_semantic_analyzer
bash tools/run_stage.sh "$PWD" 05_case_kb_builder
bash tools/run_stage.sh "$PWD" 07_final_auditor
```

## 6. Chinese Result Review

After a full run, inspect:

```bash
sed -n '1,120p' porting_knowledge_output/06_audit/pipeline_summary.zh.md
sed -n '1,120p' porting_knowledge_output/06_audit/stage_results.zh.md
```

## 7. Failure Handling

- Raw files missing: rerun stages 01 and 02.
- Statistics mismatch: rerun stage 03 and inspect `02_statistics/qc_report.md`.
- Empty semantic directories: rerun stage 04; enable deterministic fallback only for debugging.
- Weak cases: rerun stage 05 and inspect `06_audit/blocking_issues.md`.
- Scope contradiction: create `00_config/scope_change_request.md` instead of silently changing the task profile.

## 7. Final Response Requirements

Final recommendations must distinguish fact, inference, reusable rule and risk. They must not rely on previous chat history; all claims should trace back to artifacts in `porting_knowledge_output/`.
"""

    template = """# Next OpenHarmony Porting Task Template

## Target Definition

- OpenHarmony version:
- SoC:
- Board:
- Runtime architecture:
- Auxiliary cores:
- Kernel:
- System type:
- Toolchain:
- Expected product target:

## Inputs

- repo workspace path:
- manifest snapshot:
- upstream baseline:
- downstream state:
- build logs:
- boot/runtime logs:
- board schematics/vendor SDK:
- binary/prebuilt inventory:

## Scenario Classification

Choose one:

- ARM-primary board/SoC
- RISC-V-primary distribution
- heterogeneous auxiliary-core
- unknown

Explain the evidence for the choice.

## Stage Plan

1. Scope classification.
2. Repo/baseline modeling.
3. Raw record extraction.
4. Dirty workspace audit.
5. Binary/prebuilt audit.
6. Statistics QC.
7. Semantic analysis.
8. Case KB generation.
9. Skill generation.
10. Final audit.

## Risk Table

| Risk | Evidence | Owner | Mitigation | Status |
| --- | --- | --- | --- | --- |
| Binary provenance | | | | |
| Dirty workspace | | | | |
| Baseline unknown | | | | |
| Driver/HDF chain incomplete | | | | |
| WiFi runtime mismatch | | | | |

## Daily Record Format

```yaml
date:
actor:
repo_path:
commit_hash:
file_paths:
problem:
root_cause:
fix:
verification:
reusable_rule:
risk:
evidence:
```
"""

    checklist = """# Quality Checklist

## Scope

- [ ] `task_profile.yaml` exists and names runtime architecture.
- [ ] ARM-primary, RISC-V-primary and heterogeneous auxiliary-core cases are not conflated.
- [ ] Any scope change has a written `scope_change_request.md`.

## Raw Records

- [ ] `commit_records.jsonl` exists and has records.
- [ ] `file_change_records.jsonl` covers non-merge post-import commits.
- [ ] `dirty_file_records.jsonl` separates local WIP from committed history and preserves `xy_status` / `change_type`.
- [ ] `binary_asset_records.csv` includes path, asset_kind and sha256.
- [ ] Diff pointers exist for reusable commits where possible.

## Statistics

- [ ] Counts in `statistics_summary.json` match raw records.
- [ ] Reports copy statistics rather than inventing numbers.
- [ ] Initial import, post-import, dirty and binary evidence are counted separately.

## Semantic Analysis

- [ ] `repo_analysis/` is non-empty.
- [ ] `subsystem_analysis/` is non-empty.
- [ ] Force-sync and `.gitattributes` commits are marked noise.
- [ ] Candidate cases have subsystem-specific evidence.

## Cases

- [ ] Every case has Problem, Root Cause, Fix, Reusable Rule, Applicability, Non-Applicability, Verification, Risk and Confidence.
- [ ] Every case has commit/file/diff evidence or is explicitly a dirty/binary risk pattern.
- [ ] No case is based only on initial import, force-sync or `.gitattributes`.
- [ ] Case title matches evidence paths and subjects.
- [ ] SoC UAPI, reboot/EFEX and Cedar VE cases are not mislabeled as full product binding, bootloader provenance or generic driver chains without matching evidence.

## Skill Output

- [ ] `generated_skill.md` contains workflow, evidence rules, case rules, failure handling, quality gates, examples and anti-examples.
- [ ] `agent_runbook.md` contains actionable steps and commands.
- [ ] `next_porting_task_template.md` is usable for a fresh project.
- [ ] `quality_checklist.md` covers raw/stat/semantic/case/skill/audit checks.

## Audit

- [ ] Final auditor reports semantic mismatches, not only missing files.
- [ ] Blocking issues are not suppressed.
- [ ] Non-blocking binary provenance, deterministic fallback and historical pending-stage issues are carried into the final recommendation.
- [ ] Artifact manifest is present.
"""

    (skill_dir / "generated_skill.md").write_text(generated_skill, encoding="utf-8")
    (skill_dir / "agent_runbook.md").write_text(runbook, encoding="utf-8")
    (skill_dir / "next_porting_task_template.md").write_text(template, encoding="utf-8")
    (skill_dir / "quality_checklist.md").write_text(checklist, encoding="utf-8")

    outputs = [
        "05_skill_output/generated_skill.md",
        "05_skill_output/agent_runbook.md",
        "05_skill_output/next_porting_task_template.md",
        "05_skill_output/quality_checklist.md",
    ]
    result = {
        "stage": "06_skill_generator",
        "status": "passed",
        "summary": "Generated complete reusable Skill, runbook, next-task template and quality checklist.",
        "input_files_read": [
            "00_config/task_profile.yaml",
            "02_statistics/statistics_summary.json",
            "03_semantic_analysis/repo_analysis/",
            "03_semantic_analysis/subsystem_analysis/",
            "04_knowledge_base/cases/",
            "04_knowledge_base/patterns/",
            "04_knowledge_base/board_soc_porting_rules.md",
            "04_knowledge_base/binary_asset_index.md",
        ],
        "output_files_written": outputs,
        "blocking_issues": [],
        "non_blocking_issues": [],
        "next_stage_inputs": outputs,
    }
    if args.stage_result:
        Path(args.stage_result).write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
