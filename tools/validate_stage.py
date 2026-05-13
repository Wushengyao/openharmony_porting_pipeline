#!/usr/bin/env python3
import argparse
import csv
from datetime import datetime
import json
import sys
from pathlib import Path


def log(level: str, msg: str) -> None:
    ts = datetime.now().astimezone().strftime('%Y-%m-%dT%H:%M:%S%z')
    print(f'[{ts}] [{level}] {msg}', file=sys.stderr)


def fail(msg: str) -> None:
    log('BLOCKED', msg)
    sys.exit(1)


def warn(msg: str) -> None:
    log('WARN', msg)


def require_file(path: Path) -> None:
    log('CHECK', f'require non-empty file: {path}')
    if not path.exists():
        fail(f"Missing required file: {path}")
    if path.is_file() and path.stat().st_size == 0:
        fail(f"Empty required file: {path}")
    if path.is_file():
        log('OK', f'file present: {path} ({path.stat().st_size} bytes)')


def require_exists(path: Path) -> None:
    log('CHECK', f'require path exists: {path}')
    if not path.exists():
        fail(f"Missing required file: {path}")
    log('OK', f'path present: {path}')


def require_dir(path: Path) -> None:
    log('CHECK', f'require directory: {path}')
    if not path.exists() or not path.is_dir():
        fail(f"Missing required directory: {path}")
    log('OK', f'directory present: {path}')


def require_nonempty_dir(path: Path) -> None:
    require_dir(path)
    entries = list(path.iterdir())
    if not entries:
        fail(f"Empty required directory: {path}")
    log('OK', f'directory non-empty: {path} ({len(entries)} entries)')


def count_jsonl(path: Path) -> int:
    if not path.exists():
        return 0
    n = 0
    with path.open('r', encoding='utf-8', errors='ignore') as f:
        for line in f:
            if line.strip():
                n += 1
    return n


def count_csv_rows(path: Path) -> int:
    if not path.exists() or path.stat().st_size == 0:
        return 0
    with path.open('r', encoding='utf-8', errors='ignore', newline='') as f:
        try:
            return max(0, sum(1 for _ in csv.reader(f)) - 1)
        except Exception:
            return 0


def load_stage_result(path: Path) -> dict:
    require_file(path)
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
    except Exception as e:
        fail(f"Stage result is not JSON: {path}: {e}")
    log(
        'INFO',
        f"stage result loaded: stage={data.get('stage')} status={data.get('status')} "
        f"outputs={len(data.get('output_files_written') or [])}"
    )
    if data.get('status') == 'blocked':
        fail(f"Stage reported blocked: {data.get('blocking_issues')}")
    return data


def validate_case_evidence(out: Path) -> None:
    commits_path = out / '01_raw_records/commit_records.jsonl'
    files_path = out / '01_raw_records/file_change_records.jsonl'
    dirty_files_path = out / '01_raw_records/dirty_file_records.jsonl'
    commit_hashes = set()
    file_keys = set()

    for p in [commits_path]:
        if p.exists():
            with p.open(encoding='utf-8', errors='ignore') as f:
                for line in f:
                    if not line.strip():
                        continue
                    try:
                        obj = json.loads(line)
                    except Exception:
                        continue
                    h = obj.get('commit_hash') or obj.get('hash') or obj.get('commit')
                    rp = obj.get('repo_path') or obj.get('repo')
                    if h:
                        commit_hashes.add(h[:12])
                        commit_hashes.add(h)
    for p in [files_path, dirty_files_path]:
        if p.exists():
            with p.open(encoding='utf-8', errors='ignore') as f:
                for line in f:
                    if not line.strip():
                        continue
                    try:
                        obj = json.loads(line)
                    except Exception:
                        continue
                    fp = obj.get('file_path') or obj.get('path')
                    rp = obj.get('repo_path') or obj.get('repo') or ''
                    if fp:
                        file_keys.add(fp)
                        file_keys.add(f"{rp}/{fp}".strip('/'))

    cases_dir = out / '04_knowledge_base/cases'
    require_nonempty_dir(cases_dir)
    log(
        'INFO',
        f'case evidence index: commit_markers={len(commit_hashes)} file_markers={len(file_keys)}'
    )
    weak = []
    for case in cases_dir.glob('*.md'):
        text = case.read_text(encoding='utf-8', errors='ignore')
        has_commit = any(h and h in text for h in commit_hashes)
        # Keep file check lenient because case may cite path fragments.
        has_file_marker = ('evidence_files' in text or 'Files:' in text or 'file_path' in text or '## 证据' in text)
        if not has_commit or not has_file_marker:
            weak.append(case.name)
    if weak:
        fail(f"Cases without sufficient visible evidence: {', '.join(weak[:10])}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('--workspace', required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--stage', required=True)
    ap.add_argument('--stage-result', required=True)
    args = ap.parse_args()

    out = Path(args.out)
    stage = args.stage
    workspace = Path(args.workspace)
    log('INFO', f'validate start: stage={stage} workspace={workspace} out={out}')
    load_stage_result(Path(args.stage_result))

    if stage == '00_scope_classifier':
        require_file(out / '00_config/task_profile.yaml')
        require_file(out / '00_config/scope_classification_report.md')

    elif stage == '01_repo_baseline_extractor':
        require_file(out / '00_config/repo_revision_map.csv')
        require_file(out / '01_raw_records/repo_list.csv')
        require_file(out / '01_raw_records/repo_status.raw.txt')

    elif stage == '02_raw_record_extractor':
        require_file(out / '01_raw_records/commit_records.jsonl')
        require_file(out / '01_raw_records/file_change_records.jsonl')
        require_file(out / '01_raw_records/binary_asset_records.csv')
        require_file(out / '01_raw_records/dirty_repo_records.csv')
        require_exists(out / '01_raw_records/dirty_file_records.jsonl')
        require_file(out / '01_raw_records/untracked_file_records.csv')
        require_dir(out / '01_raw_records/diffs')
        require_file(out / '03_semantic_analysis/evidence_index.jsonl')
        if count_jsonl(out / '01_raw_records/commit_records.jsonl') == 0:
            fail('commit_records.jsonl has no records')
        if count_jsonl(out / '01_raw_records/file_change_records.jsonl') == 0:
            fail('file_change_records.jsonl has no records')

    elif stage == 'aux_dirty_workspace':
        require_file(out / '01_raw_records/dirty_repo_records.csv')
        require_exists(out / '01_raw_records/dirty_file_records.jsonl')
        require_file(out / '01_raw_records/untracked_file_records.csv')
        require_file(out / '03_semantic_analysis/dirty_workspace_analysis.md')

    elif stage == 'aux_binary_asset_auditor':
        require_file(out / '01_raw_records/binary_asset_records.csv')
        require_file(out / '04_knowledge_base/binary_asset_index.md')
        require_file(out / '04_knowledge_base/binary_risk_report.md')

    elif stage == '03_statistics_qc':
        require_file(out / '02_statistics/statistics_summary.json')
        require_file(out / '02_statistics/statistics_summary.md')
        require_file(out / '02_statistics/qc_report.md')
        try:
            stats = json.loads((out / '02_statistics/statistics_summary.json').read_text(encoding='utf-8'))
        except Exception as e:
            fail(f'statistics_summary.json invalid: {e}')
        actual_commits = count_jsonl(out / '01_raw_records/commit_records.jsonl')
        actual_files = count_jsonl(out / '01_raw_records/file_change_records.jsonl')
        actual_bin = count_csv_rows(out / '01_raw_records/binary_asset_records.csv')
        log(
            'INFO',
            f'raw counts: commits={actual_commits} file_changes={actual_files} binary_assets={actual_bin}'
        )
        log(
            'INFO',
            'summary counts: '
            f"commits={stats.get('commit_records_count')} "
            f"file_changes={stats.get('file_change_records_count')} "
            f"binary_assets={stats.get('binary_asset_records_count')}"
        )
        if stats.get('commit_records_count') != actual_commits:
            fail(f"commit count mismatch: stats={stats.get('commit_records_count')} actual={actual_commits}")
        if stats.get('file_change_records_count') != actual_files:
            fail(f"file change count mismatch: stats={stats.get('file_change_records_count')} actual={actual_files}")
        # Binary records can be huge or schema-dependent. Enforce only if field present.
        if 'binary_asset_records_count' in stats and stats.get('binary_asset_records_count') != actual_bin:
            fail(f"binary asset count mismatch: stats={stats.get('binary_asset_records_count')} actual={actual_bin}")

    elif stage == '04_semantic_analyzer':
        require_file(out / '03_semantic_analysis/commit_analysis.jsonl')
        require_nonempty_dir(out / '03_semantic_analysis/repo_analysis')
        require_nonempty_dir(out / '03_semantic_analysis/subsystem_analysis')
        require_file(out / '03_semantic_analysis/risk_items.md')
        require_file(out / '03_semantic_analysis/workaround_items.md')

    elif stage == '05_case_kb_builder':
        require_nonempty_dir(out / '04_knowledge_base/cases')
        require_file(out / '04_knowledge_base/board_soc_porting_rules.md')
        require_file(out / '04_knowledge_base/path_module_index.md')
        require_file(out / '04_knowledge_base/workaround_items.md')
        validate_case_evidence(out)

    elif stage == '06_skill_generator':
        require_file(out / '05_skill_output/generated_skill.md')
        require_file(out / '05_skill_output/agent_runbook.md')
        require_file(out / '05_skill_output/next_porting_task_template.md')
        require_file(out / '05_skill_output/quality_checklist.md')
        text = (out / '05_skill_output/generated_skill.md').read_text(encoding='utf-8', errors='ignore')
        if len(text) < 5000:
            fail('generated_skill.md is too short to be a complete Skill')
        for needle in ['ARM', 'RISC-V', 'heterogeneous', 'evidence', 'quality']:
            if needle.lower() not in text.lower():
                fail(f'generated_skill.md missing required concept: {needle}')

    elif stage == '07_final_auditor':
        require_file(out / '06_audit/final_audit_report.md')
        require_file(out / '06_audit/blocking_issues.md')
        require_file(out / '06_audit/non_blocking_issues.md')
        require_file(out / '06_audit/artifact_manifest.json')

    else:
        fail(f'Unknown stage: {stage}')

    log('INFO', f'validate complete: stage={stage}')
    print(f'[OK] {stage}')

if __name__ == '__main__':
    main()
