# Stage 05: Case KB Builder

Use skill: `openharmony_porting_05_case_kb_builder`.

This is a fresh isolated Codex session. Do not assume previous chat context. Do not resume or rely on prior conversations. Read only the input files listed here. Do not read archived failed runs or previous final reports unless explicitly listed. Write only the required output files. At the end, return a JSON object conforming to `stage_result.schema.json`.

## Input files

- `porting_knowledge_output/00_config/task_profile.yaml`
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

## Strict exclusions

Do not create reusable cases from:

- `initial_import` only;
- `force sync sdk code` only;
- `.gitattributes`-only commits;
- pure SDK sync without board/SoC/driver/build evidence;
- generic foundation/applications changes that do not touch the claimed subsystem.

Such records may be mentioned only in rejected/noise patterns or risks.

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

Every reusable case must include a YAML-like evidence block with commits/files/diffs and optional dirty/binary records. Each case must have:

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

Do not write template sentences such as “the area carries changes” or “claims are limited to the evidence block above.” Explain the engineering pattern.

## Theme consistency gate

- HDF/Audio case evidence must include audio/HDF/codec/DAI/DMA/HCS/HCB/speaker-related paths or subjects.
- WiFi case evidence must include WiFi/WPA/supplicant/libnl/dhcpcd/BK7236/wireless-related paths or subjects.
- Boot/firmware case evidence must include bootloader/brandy/U-Boot/SPL/ARISC/DSP/FEX/DTS/binary-related paths or subjects.
- Product/board/SoC case evidence must include productdefine/vendor/device/board/device/soc/config-related paths or subjects.

## Final JSON

Return `stage_result` JSON only in the final answer.
