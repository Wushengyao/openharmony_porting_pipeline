#!/usr/bin/env python3
"""Deterministic final audit for OpenHarmony porting pipeline outputs."""

import argparse
import hashlib
import json
from pathlib import Path


def sha256(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def count_jsonl(path):
    if not path.exists():
        return 0
    return sum(1 for line in path.read_text(encoding='utf-8', errors='ignore').splitlines() if line.strip())


def count_csv(path):
    if not path.exists() or path.stat().st_size == 0:
        return 0
    with path.open(encoding='utf-8', errors='ignore') as f:
        return max(0, sum(1 for _ in f) - 1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', required=True)
    ap.add_argument('--stage-result')
    args = ap.parse_args()
    out = Path(args.out)
    audit_dir = out / '06_audit'
    audit_dir.mkdir(parents=True, exist_ok=True)
    blocking = []
    non_blocking = []

    stats = json.loads((out / '02_statistics/statistics_summary.json').read_text(encoding='utf-8'))
    actual = {
        'commit_records_count': count_jsonl(out / '01_raw_records/commit_records.jsonl'),
        'file_change_records_count': count_jsonl(out / '01_raw_records/file_change_records.jsonl'),
        'binary_asset_records_count': count_csv(out / '01_raw_records/binary_asset_records.csv'),
        'dirty_file_records_count': count_jsonl(out / '01_raw_records/dirty_file_records.jsonl'),
    }
    for key, value in actual.items():
        if stats.get(key) != value:
            blocking.append(f'{key} mismatch: stats={stats.get(key)} actual={value}')

    required = [
        '00_config/task_profile.yaml',
        '02_statistics/statistics_summary.json',
        '03_semantic_analysis/commit_analysis.jsonl',
        '03_semantic_analysis/risk_items.md',
        '04_knowledge_base/board_soc_porting_rules.md',
        '05_skill_output/generated_skill.md',
    ]
    for item in required:
        path = out / item
        if not path.exists() or path.stat().st_size == 0:
            blocking.append(f'missing or empty artifact: {item}')

    skill_text = (out / '05_skill_output/generated_skill.md').read_text(encoding='utf-8', errors='ignore')
    for needle in ['ARM', 'RISC-V', 'heterogeneous', 'evidence', 'quality']:
        if needle.lower() not in skill_text.lower():
            blocking.append(f'generated Skill missing concept: {needle}')
    if len(skill_text) < 5000:
        blocking.append('generated Skill is shorter than 5000 characters')

    cases = sorted((out / '04_knowledge_base/cases').glob('*.md'))
    if not cases:
        blocking.append('no cases generated')
    for case in cases:
        text = case.read_text(encoding='utf-8', errors='ignore')
        if 'commit_hash:' not in text or 'evidence_files:' not in text:
            blocking.append(f'case lacks visible evidence block: {case.name}')

    files = []
    for path in sorted(out.rglob('*')):
        if path.is_file():
            files.append({
                'path': str(path.relative_to(out)),
                'size': path.stat().st_size,
                'sha256': sha256(path),
            })
    (audit_dir / 'artifact_manifest.json').write_text(
        json.dumps({'files': files}, indent=2, ensure_ascii=False) + '\n',
        encoding='utf-8',
    )
    report_lines = [
        '# Final Audit Report',
        '',
        f'- Files in manifest: {len(files)}',
        f'- Blocking issues: {len(blocking)}',
        f'- Non-blocking issues: {len(non_blocking)}',
        '- Statistics checked against raw records.',
        '- Cases checked for visible evidence blocks.',
        '- Generated Skill checked for required concepts and length.',
        '',
        '## Recommendation',
        'accept' if not blocking else 'rerun_failed_stages',
        '',
    ]
    (audit_dir / 'final_audit_report.md').write_text('\n'.join(report_lines), encoding='utf-8')
    (audit_dir / 'blocking_issues.md').write_text(
        '# Blocking Issues\n\n' + ('\n'.join(f'- {item}' for item in blocking) if blocking else '- None') + '\n',
        encoding='utf-8',
    )
    (audit_dir / 'non_blocking_issues.md').write_text(
        '# Non-Blocking Issues\n\n' + ('\n'.join(f'- {item}' for item in non_blocking) if non_blocking else '- None') + '\n',
        encoding='utf-8',
    )
    result = {
        'stage': '07_final_auditor',
        'status': 'blocked' if blocking else 'passed',
        'summary': f'Final audit completed with {len(blocking)} blocking and {len(non_blocking)} non-blocking issues.',
        'blocking_issue_count': len(blocking),
        'non_blocking_issue_count': len(non_blocking),
        'blocking_issues': blocking,
        'non_blocking_issues': non_blocking,
        'output_files_written': [
            '06_audit/final_audit_report.md',
            '06_audit/blocking_issues.md',
            '06_audit/non_blocking_issues.md',
            '06_audit/artifact_manifest.json',
        ],
        'recommendation': 'rerun_failed_stages' if blocking else 'accept',
    }
    if args.stage_result:
        Path(args.stage_result).write_text(json.dumps(result, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
