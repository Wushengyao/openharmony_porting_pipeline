#!/usr/bin/env python3
"""Deterministic semantic layer generator for OpenHarmony porting pipeline."""

import argparse
import csv
import json
import re
from collections import Counter, defaultdict
from pathlib import Path


def read_jsonl(path):
    rows = []
    if not path.exists():
        return rows
    with path.open(encoding='utf-8', errors='ignore') as f:
        for line in f:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def read_csv(path):
    if not path.exists() or path.stat().st_size == 0:
        return []
    with path.open(encoding='utf-8', errors='ignore', newline='') as f:
        return list(csv.DictReader(f))


def safe_name(value):
    return re.sub(r'[^A-Za-z0-9._-]+', '__', value.strip('/')) or 'root'


def int_value(value):
    try:
        return int(value or 0)
    except Exception:
        return 0


def infer_theme(subject, paths):
    text = ' '.join([subject or '', *paths]).lower()
    rules = [
        ('wifi', ['wifi', 'wpa', 'supplicant', 'bk7236', 'libnl']),
        ('audio_hdf', ['audio', 'codec', 'dai', 'dma', 'hdf']),
        ('boot_firmware', ['bootloader', 'uboot', 'u-boot', 'dts', 'arisc', 'dsp', 'fex']),
        ('hdf_config', ['hdf_config', '.hcs', '.hcb']),
        ('build_integration', ['build.gn', 'bundle.json', 'config.gni', 'gn', 'makefile']),
        ('prebuilt_toolchain', ['prebuilt', 'node_modules', 'llvm', 'clang', 'typescript']),
        ('vendor_product', ['vendor/', 'config.json', 'product']),
        ('kernel_driver', ['kernel', 'driver', '.ko']),
        ('format_sync', ['.gitattributes', 'force sync']),
    ]
    for theme, needles in rules:
        if any(needle in text for needle in needles):
            return theme
    return 'general_porting'


def first_items(items, limit=8):
    return list(items)[:limit]


def md_table(headers, rows):
    lines = [
        '| ' + ' | '.join(headers) + ' |',
        '| ' + ' | '.join(['---'] * len(headers)) + ' |',
    ]
    for row in rows:
        lines.append('| ' + ' | '.join(str(cell).replace('\n', ' ') for cell in row) + ' |')
    return '\n'.join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', required=True)
    ap.add_argument('--stage-result')
    args = ap.parse_args()
    out = Path(args.out)
    sem_dir = out / '03_semantic_analysis'
    repo_dir = sem_dir / 'repo_analysis'
    subsystem_dir = sem_dir / 'subsystem_analysis'
    repo_dir.mkdir(parents=True, exist_ok=True)
    subsystem_dir.mkdir(parents=True, exist_ok=True)

    commits = read_jsonl(out / '01_raw_records/commit_records.jsonl')
    files = read_jsonl(out / '01_raw_records/file_change_records.jsonl')
    dirty_files = read_jsonl(out / '01_raw_records/dirty_file_records.jsonl')
    binary_rows = read_csv(out / '01_raw_records/binary_asset_records.csv')
    stats = {}
    stats_path = out / '02_statistics/statistics_summary.json'
    if stats_path.exists():
        stats = json.loads(stats_path.read_text(encoding='utf-8'))

    files_by_commit = defaultdict(list)
    files_by_repo = defaultdict(list)
    for row in files:
        files_by_commit[row.get('commit_evidence_id')].append(row)
        files_by_repo[row.get('repo_path') or 'unknown'].append(row)

    commits_by_repo = defaultdict(list)
    commits_by_class = defaultdict(list)
    commit_analysis = []
    for row in commits:
        repo = row.get('repo_path') or 'unknown'
        classification = row.get('classification') or 'unknown'
        related_files = files_by_commit.get(row.get('evidence_id'), [])
        related_paths = [item.get('path') or item.get('file_path') or '' for item in related_files]
        theme = infer_theme(row.get('subject'), related_paths)
        evidence_files = [
            {
                'evidence_id': item.get('evidence_id'),
                'repo_path': item.get('repo_path'),
                'file_path': item.get('path') or item.get('file_path'),
            }
            for item in first_items(related_files, 12)
        ]
        analysis = {
            'record_type': 'commit_analysis',
            'commit_evidence_id': row.get('evidence_id'),
            'repo_path': repo,
            'classification': classification,
            'commit_hash': row.get('commit'),
            'origin_type': row.get('origin_type'),
            'subject': row.get('subject'),
            'semantic_theme': theme,
            'porting_relevance': (
                'initial import baseline' if row.get('origin_type') == 'initial_import'
                else f'{theme} change for the target OpenHarmony port'
            ),
            'evidence_commits': [f"{repo}:{row.get('commit')}"],
            'evidence_files': evidence_files,
            'evidence_diffs': [row.get('diff_path')] if row.get('diff_path') else [],
            'changed_files_count': int_value(row.get('changed_files_count')),
            'insertions': int_value(row.get('insertions')),
            'deletions': int_value(row.get('deletions')),
        }
        commit_analysis.append(analysis)
        commits_by_repo[repo].append(analysis)
        commits_by_class[classification].append(analysis)

    dirty_by_repo = defaultdict(list)
    dirty_by_class = defaultdict(list)
    for row in dirty_files:
        repo = row.get('repo_path') or 'unknown'
        classification = row.get('classification') or 'unknown'
        dirty_by_repo[repo].append(row)
        dirty_by_class[classification].append(row)

    binary_by_repo = defaultdict(list)
    binary_by_class = defaultdict(list)
    for row in binary_rows:
        path = row.get('path') or ''
        repo = path.split('/', 1)[0] if path else 'unknown'
        if path.startswith('device/board/'):
            repo = '/'.join(path.split('/')[:5])
        elif path.startswith('device/soc/'):
            repo = '/'.join(path.split('/')[:4])
        elif path.startswith('vendor/'):
            repo = '/'.join(path.split('/')[:3])
        elif path.startswith('arkcompiler/'):
            repo = 'arkcompiler'
        elif path.startswith('developtools/'):
            repo = 'developtools'
        elif path.startswith('third_party/'):
            repo = 'third_party'
        elif path.startswith('drivers/'):
            repo = 'drivers'
        classification_match = re.search(r'(?:^|; )classification=([^;]+)', row.get('analysis_note') or '')
        classification = classification_match.group(1) if classification_match else 'unknown'
        binary_by_repo[repo].append(row)
        binary_by_class[classification].append(row)

    with (sem_dir / 'commit_analysis.jsonl').open('w', encoding='utf-8') as f:
        for row in commit_analysis:
            f.write(json.dumps(row, ensure_ascii=False) + '\n')

    risk_items = [
        '# Risk Items',
        '',
        f"- Statistics source: `02_statistics/statistics_summary.json` records {stats.get('commit_records_count', len(commits))} commits, {stats.get('file_change_records_count', len(files))} file changes, {stats.get('binary_asset_records_count', len(binary_rows))} binary assets, and {stats.get('dirty_file_records_count', len(dirty_files))} dirty files.",
        '- Dirty workspace facts are separated from committed history and must not be treated as landed upstream changes.',
    ]
    runtime_binary_examples = [
        row for row in binary_rows
        if (row.get('runtime_dependency') or '').lower() == 'yes'
    ][:20]
    if runtime_binary_examples:
        risk_items.append('- Runtime binary/prebuilt artifacts require provenance and redistribution review:')
        for row in runtime_binary_examples:
            risk_items.append(
                f"  - `{row.get('path')}` sha256={row.get('sha256')} usage={row.get('possible_usage')} introduced_by={row.get('introduced_by')}"
            )
    large_commits = sorted(
        [row for row in commit_analysis if row['origin_type'] != 'initial_import'],
        key=lambda row: row['insertions'] + row['deletions'],
        reverse=True,
    )[:10]
    if large_commits:
        risk_items.append('- Large downstream diffs should be reviewed before reuse:')
        for row in large_commits:
            risk_items.append(
                f"  - {row['commit_evidence_id']} `{row['repo_path']}` {row['commit_hash']} theme={row['semantic_theme']} diff={row['evidence_diffs'] or ['unknown']}"
            )

    workaround_items = [
        '# Workaround Items',
        '',
        '- Keep workaround notes separate from reusable rules. Items below are evidence-bound observations, not best practices.',
        '- Wi-Fi enablement imports large libnl/wpa_supplicant patch payloads; reuse only after checking whether upstream OpenHarmony already has equivalent support.',
        '- Dirty prebuilt/toolchain trees under `prebuilts/` and Node package trees under `arkcompiler/` may be local build-environment workarounds until provenance is confirmed.',
        '- Generated HDF binary config such as `vendor/seed/t113_evb1/hdf_config/hdf_hcs.hcb` should be regenerated from source HCS where possible rather than edited directly.',
    ]

    all_repos = sorted(set(commits_by_repo) | set(files_by_repo) | set(dirty_by_repo) | set(binary_by_repo))
    for repo in all_repos:
        repo_commits = commits_by_repo.get(repo, [])
        repo_files = files_by_repo.get(repo, [])
        repo_dirty = dirty_by_repo.get(repo, [])
        repo_binary = binary_by_repo.get(repo, [])
        themes = Counter(row['semantic_theme'] for row in repo_commits)
        lines = [
            f'# Repo Analysis: {repo}',
            '',
            md_table(
                ['Metric', 'Value'],
                [
                    ['commit analyses', len(repo_commits)],
                    ['file change records', len(repo_files)],
                    ['dirty file records', len(repo_dirty)],
                    ['binary asset records', len(repo_binary)],
                    ['top themes', ', '.join(f'{key}:{value}' for key, value in themes.most_common(5)) or 'none'],
                ],
            ),
            '',
            '## Evidence Commits',
        ]
        for row in first_items([r for r in repo_commits if r['origin_type'] != 'initial_import'], 12):
            lines.append(
                f"- {row['commit_evidence_id']} `{row['commit_hash']}` theme={row['semantic_theme']} subject={row['subject']} diff={row['evidence_diffs'] or ['unknown']}"
            )
        if not any(r['origin_type'] != 'initial_import' for r in repo_commits):
            lines.append('- None beyond initial import in raw commit records.')
        lines.extend(['', '## Evidence Files'])
        for row in first_items(repo_files, 12):
            lines.append(
                f"- {row.get('evidence_id')} `{row.get('path') or row.get('file_path')}` change={row.get('change_type')} commit={row.get('commit_evidence_id')}"
            )
        if repo_dirty:
            lines.extend(['', '## Dirty Workspace Evidence'])
            for row in first_items(repo_dirty, 12):
                lines.append(
                    f"- {row.get('evidence_id')} `{row.get('path')}` status={row.get('dirty_status')} class={row.get('dirty_content_class')}"
                )
        if repo_binary:
            lines.extend(['', '## Binary/Prebuilt Evidence'])
            for row in first_items(repo_binary, 8):
                lines.append(
                    f"- `{row.get('path')}` sha256={row.get('sha256')} arch={row.get('architecture')} runtime={row.get('runtime_dependency')}"
                )
        lines.extend(['', '## Scope Note', 'Unsupported claims are `unknown`; conclusions above are derived only from listed evidence records.', ''])
        (repo_dir / f'{safe_name(repo)}.md').write_text('\n'.join(lines), encoding='utf-8')

    all_classes = sorted(set(commits_by_class) | set(dirty_by_class) | set(binary_by_class))
    for classification in all_classes:
        rows = commits_by_class.get(classification, [])
        dirty = dirty_by_class.get(classification, [])
        binary = binary_by_class.get(classification, [])
        themes = Counter(row['semantic_theme'] for row in rows)
        lines = [
            f'# Subsystem Analysis: {classification}',
            '',
            md_table(
                ['Metric', 'Value'],
                [
                    ['commit analyses', len(rows)],
                    ['dirty file records', len(dirty)],
                    ['binary asset records', len(binary)],
                    ['top themes', ', '.join(f'{key}:{value}' for key, value in themes.most_common(8)) or 'none'],
                ],
            ),
            '',
            '## Representative Evidence',
        ]
        for row in first_items([r for r in rows if r['origin_type'] != 'initial_import'], 16):
            lines.append(
                f"- {row['commit_evidence_id']} `{row['repo_path']}` {row['commit_hash']} theme={row['semantic_theme']} files={len(row['evidence_files'])}"
            )
        if binary:
            lines.extend(['', '## Binary/Prebuilt Evidence'])
            for row in first_items(binary, 10):
                lines.append(
                    f"- `{row.get('path')}` sha256={row.get('sha256')} usage={row.get('possible_usage')}"
                )
        lines.append('')
        (subsystem_dir / f'{safe_name(classification)}.md').write_text('\n'.join(lines), encoding='utf-8')

    (sem_dir / 'risk_items.md').write_text('\n'.join(risk_items) + '\n', encoding='utf-8')
    (sem_dir / 'workaround_items.md').write_text('\n'.join(workaround_items) + '\n', encoding='utf-8')

    outputs = [
        '03_semantic_analysis/commit_analysis.jsonl',
        '03_semantic_analysis/repo_analysis/',
        '03_semantic_analysis/subsystem_analysis/',
        '03_semantic_analysis/risk_items.md',
        '03_semantic_analysis/workaround_items.md',
    ]
    result = {
        'stage': '04_semantic_analyzer',
        'status': 'passed',
        'summary': f'Generated deterministic semantic analysis for {len(commit_analysis)} commits, {len(all_repos)} repos, and {len(all_classes)} subsystem classes.',
        'input_files_read': [
            '00_config/task_profile.yaml',
            '01_raw_records/commit_records.jsonl',
            '01_raw_records/file_change_records.jsonl',
            '01_raw_records/dirty_file_records.jsonl',
            '01_raw_records/binary_asset_records.csv',
            '01_raw_records/diffs/',
            '03_semantic_analysis/evidence_index.jsonl',
            '02_statistics/statistics_summary.json',
        ],
        'output_files_written': outputs,
        'blocking_issues': [],
        'non_blocking_issues': [
            'Semantic text is generated mechanically from raw records; nuanced hunk-level interpretation should be refined in case construction.',
        ],
        'next_stage_inputs': outputs,
    }
    if args.stage_result:
        Path(args.stage_result).write_text(json.dumps(result, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
