# Update v2: LLM-refined semantic/case/skill/audit stages

This overlay improves the current `openharmony_porting_pipeline` based on the T113 Codex run review.

## Main changes

1. Stages 04-07 now default to Codex/LLM execution instead of deterministic scripts.
2. Deterministic scripts remain available as explicit fallback:
   - `DETERMINISTIC_SEMANTIC_ANALYZER=1`
   - `DETERMINISTIC_CASE_KB=1`
   - `DETERMINISTIC_SKILL_GENERATOR=1`
   - `DETERMINISTIC_FINAL_AUDIT=1`
3. Semantic fallback now labels initial import, force-sync and `.gitattributes`-only commits as noise.
4. Case fallback now generates fewer, higher-quality cases and rejects sync/noise evidence.
5. Skill fallback now creates substantive runbook/template/checklist files.
6. Final audit now checks semantic mismatches, case quality and support-file length, not only file existence.
7. `validate_stage.py` now blocks template cases, mismatched case themes, tiny runbooks/templates/checklists and final audits with blocking issues.

## Apply

From the repository root:

```bash
cp -r /path/to/openharmony_porting_pipeline_update_v2/tools/* tools/
cp -r /path/to/openharmony_porting_pipeline_update_v2/prompts/* prompts/
```

Then rerun Phase 4-7 using existing raw outputs:

```bash
bash tools/run_stage.sh "$PWD" 04_semantic_analyzer porting_knowledge_output
bash tools/run_stage.sh "$PWD" 05_case_kb_builder porting_knowledge_output
bash tools/run_stage.sh "$PWD" 06_skill_generator porting_knowledge_output
bash tools/run_stage.sh "$PWD" 07_final_auditor porting_knowledge_output
```

For deterministic fallback/debugging:

```bash
DETERMINISTIC_SEMANTIC_ANALYZER=1 bash tools/run_stage.sh "$PWD" 04_semantic_analyzer porting_knowledge_output
DETERMINISTIC_CASE_KB=1 bash tools/run_stage.sh "$PWD" 05_case_kb_builder porting_knowledge_output
DETERMINISTIC_SKILL_GENERATOR=1 bash tools/run_stage.sh "$PWD" 06_skill_generator porting_knowledge_output
DETERMINISTIC_FINAL_AUDIT=1 bash tools/run_stage.sh "$PWD" 07_final_auditor porting_knowledge_output
```
