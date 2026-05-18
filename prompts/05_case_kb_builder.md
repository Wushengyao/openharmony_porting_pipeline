# Stage 05: Case KB Builder

Use skill: `openharmony_porting_05_case_kb_builder`.

This is a fresh isolated Codex session. Do not assume previous chat context. Do not resume or rely on prior conversations. Read only the input files listed here. Do not read archived failed runs or previous final reports unless explicitly listed. Write only the required output files. At the end, return a JSON object conforming to `stage_result.schema.json`.

## Input files

- `porting_knowledge_output/00_config/task_profile.yaml`
- `porting_knowledge_output/00_config/operator_context.md` or `.json` if present
- `porting_knowledge_output/01_raw_records/commit_records.jsonl`
- `porting_knowledge_output/01_raw_records/file_change_records.jsonl`
- `porting_knowledge_output/01_raw_records/dirty_file_records.jsonl`
- `porting_knowledge_output/01_raw_records/binary_asset_records.csv`
- `porting_knowledge_output/03_semantic_analysis/commit_analysis.jsonl`
- `porting_knowledge_output/03_semantic_analysis/repo_analysis/`
- `porting_knowledge_output/03_semantic_analysis/subsystem_analysis/`
- `porting_knowledge_output/03_semantic_analysis/risk_items.md`
- `porting_knowledge_output/03_semantic_analysis/workaround_items.md`

## Required output files

- `04_knowledge_base/cases/*.md`
- `04_knowledge_base/patterns/*.md`
- `04_knowledge_base/path_module_index.md`
- `04_knowledge_base/board_soc_porting_rules.md`
- `04_knowledge_base/workaround_items.md`

## Output ownership boundary

Stage 05 owns only the required files listed above. Do not delete, rename, replace, or "clean up" files written by earlier stages, even when they are also under `04_knowledge_base/`. In particular, preserve:

- `04_knowledge_base/binary_asset_index.md`
- `04_knowledge_base/binary_risk_report.md`

Those files are declared by `aux_binary_asset_auditor` and must remain present for final artifact validation. If they look stale or unrelated to Stage 05, mention that as a non-blocking note; do not remove them.

## Strict exclusions

Do not create reusable cases from:

- `initial_import` only;
- `force sync sdk code` only;
- `.gitattributes`-only commits;
- pure SDK sync without board/SoC/driver/build evidence;
- generic foundation/applications changes that do not touch the claimed subsystem.

Such records may be mentioned only in rejected/noise patterns or risks.

Operator context can influence which evidence-backed cases are prioritized, but it cannot by itself create a reusable case. If the user says a commit is a porting commit and raw records disagree or lack evidence, mark it as unresolved context.

## Preferred case set for T113-like projects

Generate fewer, higher-quality cases. Prefer 5 to 7 cases, such as:

1. WiFi vendor code type/libc/toolbox compatibility.
2. WiFi BSP/third_party/runtime integration chain.
3. HDF Audio multi-repo chain.
4. Product/board/vendor/SoC binding.
5. Bootloader/firmware/board binary provenance.
6. Kernel/driver adaptation with dirty workspace separation.
7. Build/product integration if evidence supports it.

## Case evidence gate

Every reusable case must include exactly one canonical YAML-like `## Evidence` block. Do not add a second `Validator Evidence` block. The validator reads the same evidence humans read.

Use this schema:

```yaml
evidence:
  commits:
    - repo_path: device/board/seed/t113_auto
      commit_hash: cd98bf141bed4cd8eb8de0687225b11ea0d92917
      subject: "K1:sun8iw20p1:P2:wifi:add wifi function"
  files:
    - repo_path: device/board/seed/t113_auto
      file_path: BUILD.gn
      record_id: "file_change:..."
  diffs:
    - 01_raw_records/diffs/commit__device_board_seed_t113_auto__cd98bf141bed.patch
  dirty_records:
    - repo_path: vendor/seed/t113_evb1
      file_path: hdf_config/.built-in.a.cmd
      relation: risk_only
  binary_records:
    - path: drivers/hdf_core/adapter/khdf/linux/model/audio/built-in.a
      sha256: "..."
      relation: risk_only
```

Rules for the evidence block:

- every `commit_hash` must exist in `commit_records.jsonl`;
- every `file_path` must exist in `file_change_records.jsonl` or `dirty_file_records.jsonl`, paired with the stated `repo_path`;
- every source path mentioned anywhere in the case body must also appear in the canonical evidence block or be explicitly marked `unknown`;
- do not mention unsupported files such as `feature.json` unless that path exists in raw or dirty records;
- do not use wildcard-only evidence for the main case claim.

Each case must have:

- YAML frontmatter with `schema_version`, `case_id`, `title`, `porting_phase`, `subsystem`, `problem_type`, `reuse_level`, `evidence_level`, and `confidence`;
- Case ID;
- Problem;
- Root Cause;
- Fix / Handling Pattern;
- Reusable Rule;
- Applicability;
- Non-Applicability;
- Verification;
- Risks;
- Confidence.

The frontmatter is consumed by Stage 08 `08_meta_input_exporter`. Keep it aligned with the body evidence and never set `reuse_level: universal` in a single-scenario case; use `universal_candidate`, `conditional`, `scenario_specific`, `risk_only`, or `workaround`.

Do not write template sentences such as “the area carries changes” or “claims are limited to the evidence block above.” Explain the engineering pattern.

Dirty/binary association must be precise. Attach dirty or binary records to a case only when same repo, path prefix, or strong theme keywords match the case. If not, put them in `workaround_items.md`, `binary_risk_report.md`, or a risk-only note, not in the case evidence.

## Theme consistency gate

- HDF/Audio case evidence must include audio/HDF/codec/DAI/DMA/HCS/HCB/speaker-related paths or subjects.
- WiFi case evidence must include WiFi/WPA/supplicant/libnl/dhcpcd/BK7236/wireless-related paths or subjects.
- Boot/firmware case evidence must include bootloader/brandy/U-Boot/SPL/ARISC/DSP/FEX/DTS/binary-related paths or subjects.
- Product/board/SoC case evidence must include productdefine/vendor/device/board/device/soc/config-related paths or subjects.

If a candidate mixes multiple feature themes (for example speaker PA pin, WiFi module compile support, and board DTS), split it into separate cases or explicitly label it as a board hardware binding pattern and keep evidence grouped by subtheme.

## Final JSON

Return `stage_result` JSON only in the final answer.
