# Stage 04: Semantic Analyzer

Use skill: `openharmony_porting_04_semantic_analyzer`.

This is a fresh isolated Codex session. Do not assume previous chat context. Do not resume or rely on prior conversations. Read only the input files listed here, plus source files only when this stage explicitly requires shell/git inspection. Do not read archived failed runs or previous final reports unless explicitly listed. Write only the required output files. At the end, return a JSON object conforming to `stage_result.schema.json`.

## Input files

- `porting_knowledge_output/00_config/task_profile.yaml`
- `porting_knowledge_output/00_config/operator_context.md` or `.json` if present
- `porting_knowledge_output/01_raw_records/commit_records.jsonl`
- `porting_knowledge_output/01_raw_records/file_change_records.jsonl`
- `porting_knowledge_output/01_raw_records/dirty_file_records.jsonl`
- `porting_knowledge_output/01_raw_records/binary_asset_records.csv`
- `porting_knowledge_output/01_raw_records/diffs/`
- `porting_knowledge_output/03_semantic_analysis/evidence_index.jsonl`
- `porting_knowledge_output/02_statistics/statistics_summary.json`

## Required output files

- `03_semantic_analysis/commit_analysis.jsonl`
- `03_semantic_analysis/repo_analysis/*.md`
- `03_semantic_analysis/subsystem_analysis/*.md`
- `03_semantic_analysis/risk_items.md`
- `03_semantic_analysis/workaround_items.md`

## Method

This stage must do semantic interpretation, not just directory listing. You may run deterministic helper scripts to prepare candidate slices, but the final files must include evidence-grounded engineering interpretation.

Use `operator_context` as optional scenario context and prioritization hints. It can guide attention, but semantic claims still require raw-record evidence. If user hints conflict with evidence, write the conflict as a risk or note.

Required filtering:

- Mark `initial_import` as baseline/import context, not a reusable fix.
- Mark commit subjects containing `force sync sdk code` as sync/noise unless file/diff evidence proves a subsystem-specific engineering change.
- Mark `.gitattributes`-only commits as noise.
- Do not classify foundation/applications `.gitattributes` sync commits as HDF Audio, boot firmware, WiFi, or board config.
- Keep dirty workspace evidence separate from committed history.
- Keep binary/prebuilt evidence separate from source fixes.

## Coverage guidance

For T113-like projects, prioritize:

- product/board/vendor/SoC binding;
- WiFi type/API compatibility and runtime integration;
- HDF Audio driver/board/vendor chain;
- bootloader/firmware/board configuration provenance;
- kernel/driver adaptation;
- binary/prebuilt provenance;
- dirty workspace governance;
- RISC-V auxiliary-core context only as auxiliary firmware/context, not primary runtime architecture.

For RuyiOS/riscv64 projects, prioritize vendor/product, device/board, device/soc, kernel, prebuilts/toolchain, OpenSBI/U-Boot, third_party architecture compatibility.

## Output requirements

`commit_analysis.jsonl` records should include at least:

- `commit_evidence_id`
- `repo_path`
- `commit_hash`
- `origin_type`
- `subject`
- `semantic_theme`
- `noise_reason` when applicable
- `is_case_candidate`
- `case_candidate_score`
- `case_candidate_reasons`
- `evidence_files`
- `evidence_diffs`

Repo and subsystem analysis must include:

- candidate evidence;
- excluded/noise evidence;
- dirty evidence where relevant;
- binary/prebuilt evidence where relevant;
- risks and unknowns.

Subsystem analysis must be feature-level, not only coarse classification buckets. In addition to any broad files such as `board_soc_porting_scope.md`, write feature/topic files when evidence supports them, for example:

- `wifi_runtime_integration.md`
- `wifi_bk7236_driver_chain.md`
- `hdf_audio_chain.md`
- `board_vendor_product_binding.md`
- `bootloader_firmware_provenance.md`
- `dirty_workspace_governance.md`
- `binary_prebuilt_risk.md`

Use concrete feature names from evidence rather than forcing the examples above when the project is not T113-like. A valid run with porting evidence should produce at least three feature-level subsystem files beyond coarse buckets.

Dirty and binary/prebuilt evidence may be attached to a commit, repo, subsystem, or future case only when at least one of these is true:

- same `repo_path`;
- source path prefix overlap;
- strong theme keyword match (for example WiFi/WPA/libnl/dhcpcd/BK7236, HDF/audio/codec/DAI/DMA/HCS, bootloader/U-Boot/SPL/DTS/binary).

Otherwise place dirty/binary records only in risk/governance sections. Do not hang unrelated `.o`, `.cmd`, `package-lock`, or `.gitattributes` samples on a feature candidate just because they share a broad classification bucket.

Case-candidate gating must be conservative:

- `initial_import` is never `is_case_candidate=true`.
- commits whose subject contains `force sync sdk code` are `is_case_candidate=false` unless non-`.gitattributes` evidence proves a specific board/SoC/driver/build change; in that rare case, write the proof in `case_candidate_reasons`.
- `.gitattributes`-only commits are never case candidates.

## Evidence rule

Every non-trivial claim must cite commit/file/diff/dirty/binary evidence. If missing, mark as `unknown` or `inference`.

## Final JSON

Return `stage_result` JSON only in the final answer.
