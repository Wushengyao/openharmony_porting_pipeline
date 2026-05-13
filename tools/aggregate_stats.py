#!/usr/bin/env python3
"""Deterministic statistics/QC generator for OpenHarmony porting pipeline."""

import argparse
import csv
import json
import re
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path


def read_jsonl(path):
    rows = []
    bad = 0
    if not path.exists():
        return rows, bad
    with path.open(encoding='utf-8', errors='ignore') as f:
        for line in f:
            if not line.strip():
                continue
            try:
                rows.append(json.loads(line))
            except Exception:
                bad += 1
    return rows, bad


def read_csv(path):
    if not path.exists() or path.stat().st_size == 0:
        return []
    with path.open(encoding='utf-8', errors='ignore', newline='') as f:
        return list(csv.DictReader(f))


def int_value(value):
    try:
        return int(value or 0)
    except Exception:
        return 0


def file_kind(path):
    suffix = Path(path or '').suffix.lower()
    return suffix if suffix else '<no_ext>'


def classification_from_note(note):
    match = re.search(r'(?:^|; )classification=([^;]+)', note or '')
    return match.group(1) if match else 'unknown'


def longest_repo_match(path, repo_classes):
    for repo_path, classification in sorted(repo_classes.items(), key=lambda item: len(item[0]), reverse=True):
        if path == repo_path or path.startswith(f'{repo_path}/'):
            return repo_path, classification
    return '', ''


def write_csv(path, fieldnames, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', encoding='utf-8', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, '') for key in fieldnames})


def markdown_table(headers, rows):
    lines = [
        '| ' + ' | '.join(headers) + ' |',
        '| ' + ' | '.join(['---'] * len(headers)) + ' |',
    ]
    for row in rows:
        lines.append('| ' + ' | '.join(str(cell) for cell in row) + ' |')
    return '\n'.join(lines)


def duplicate_ids(rows):
    ids = [row.get('evidence_id') for row in rows if row.get('evidence_id')]
    return [key for key, value in Counter(ids).items() if value > 1]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', required=True)
    ap.add_argument('--stage-result')
    args = ap.parse_args()
    out = Path(args.out)
    stats_dir = out / '02_statistics'
    stats_dir.mkdir(parents=True, exist_ok=True)

    repo_rows = read_csv(out / '00_config/repo_revision_map.csv')
    commits, bad_commits = read_jsonl(out / '01_raw_records/commit_records.jsonl')
    files, bad_files = read_jsonl(out / '01_raw_records/file_change_records.jsonl')
    dirty_files, bad_dirty = read_jsonl(out / '01_raw_records/dirty_file_records.jsonl')
    dirty_repos = read_csv(out / '01_raw_records/dirty_repo_records.csv')
    binary_rows = read_csv(out / '01_raw_records/binary_asset_records.csv')

    repo_classes = {
        row.get('repo_path', ''): row.get('classification', 'unknown')
        for row in repo_rows
        if row.get('repo_path')
    }
    repo_stats = defaultdict(lambda: {
        'repo_path': '',
        'classification': 'unknown',
        'commit_records': 0,
        'file_change_records': 0,
        'dirty_file_records': 0,
        'binary_asset_records': 0,
        'insertions': 0,
        'deletions': 0,
    })
    subsystem_stats = defaultdict(lambda: {
        'classification': '',
        'commit_records': 0,
        'file_change_records': 0,
        'dirty_file_records': 0,
        'binary_asset_records': 0,
    })
    file_type_rows = []
    file_type_counter = Counter()

    commit_origin = Counter()
    for row in commits:
        repo_path = row.get('repo_path') or row.get('repo') or 'unknown'
        classification = row.get('classification') or repo_classes.get(repo_path, 'unknown')
        origin = row.get('commit_origin_type') or row.get('origin_type') or 'unknown'
        commit_origin[origin] += 1
        repo_stats[repo_path]['repo_path'] = repo_path
        repo_stats[repo_path]['classification'] = classification
        repo_stats[repo_path]['commit_records'] += 1
        repo_stats[repo_path]['insertions'] += int_value(row.get('insertions'))
        repo_stats[repo_path]['deletions'] += int_value(row.get('deletions'))
        subsystem_stats[classification]['classification'] = classification
        subsystem_stats[classification]['commit_records'] += 1

    file_by_commit = Counter()
    file_insertions_by_commit = defaultdict(lambda: [0, 0])
    for row in files:
        repo_path = row.get('repo_path') or row.get('repo') or 'unknown'
        classification = row.get('classification') or repo_classes.get(repo_path, 'unknown')
        kind = file_kind(row.get('path') or row.get('file_path'))
        commit_id = row.get('commit_evidence_id')
        if commit_id:
            file_by_commit[commit_id] += 1
            file_insertions_by_commit[commit_id][0] += int_value(row.get('insertions'))
            file_insertions_by_commit[commit_id][1] += int_value(row.get('deletions'))
        repo_stats[repo_path]['repo_path'] = repo_path
        repo_stats[repo_path]['classification'] = classification
        repo_stats[repo_path]['file_change_records'] += 1
        repo_stats[repo_path]['insertions'] += int_value(row.get('insertions'))
        repo_stats[repo_path]['deletions'] += int_value(row.get('deletions'))
        subsystem_stats[classification]['classification'] = classification
        subsystem_stats[classification]['file_change_records'] += 1
        file_type_counter[('file_change_records', kind)] += 1

    dirty_by_repo = Counter()
    for row in dirty_files:
        repo_path = row.get('repo_path') or row.get('repo') or 'unknown'
        classification = row.get('classification') or repo_classes.get(repo_path, 'unknown')
        kind = row.get('dirty_content_class') or file_kind(row.get('path') or row.get('file_path'))
        dirty_repo_id = row.get('dirty_repo_evidence_id')
        if dirty_repo_id:
            dirty_by_repo[dirty_repo_id] += 1
        repo_stats[repo_path]['repo_path'] = repo_path
        repo_stats[repo_path]['classification'] = classification
        repo_stats[repo_path]['dirty_file_records'] += 1
        subsystem_stats[classification]['classification'] = classification
        subsystem_stats[classification]['dirty_file_records'] += 1
        file_type_counter[('dirty_file_records', kind)] += 1

    binary_arch = Counter()
    binary_license = Counter()
    binary_redistribution = Counter()
    binary_runtime = Counter()
    binary_repo = Counter()
    for row in binary_rows:
        path = row.get('path') or ''
        repo_path, classification = longest_repo_match(path, repo_classes)
        if not repo_path:
            repo_path = path.split('/', 1)[0] if path else 'unknown'
            classification = classification_from_note(row.get('analysis_note'))
        repo_stats[repo_path]['repo_path'] = repo_path
        repo_stats[repo_path]['classification'] = classification
        repo_stats[repo_path]['binary_asset_records'] += 1
        subsystem_stats[classification]['classification'] = classification
        subsystem_stats[classification]['binary_asset_records'] += 1
        binary_arch[row.get('architecture') or 'unknown'] += 1
        binary_license[row.get('license_risk') or 'unknown'] += 1
        binary_redistribution[row.get('redistribution_risk') or 'unknown'] += 1
        binary_runtime[row.get('runtime_dependency') or 'unknown'] += 1
        binary_repo[repo_path] += 1
        file_type_counter[('binary_asset_records', row.get('file_type') or 'unknown')] += 1

    for (source, kind), count in sorted(file_type_counter.items(), key=lambda item: (item[0][0], -item[1], item[0][1])):
        file_type_rows.append({'source': source, 'file_type': kind, 'count': count})

    blocking_issues = []
    non_blocking_issues = []
    if bad_commits or bad_files or bad_dirty:
        blocking_issues.append(
            f'JSONL parse errors: commits={bad_commits}, file_changes={bad_files}, dirty_files={bad_dirty}'
        )
    for name, rows in [
        ('commit_records', commits),
        ('file_change_records', files),
        ('dirty_file_records', dirty_files),
    ]:
        dups = duplicate_ids(rows)
        if dups:
            blocking_issues.append(f'{name} has duplicate evidence_id values: {dups[:5]}')

    changed_file_mismatches = []
    insertion_mismatches = []
    for row in commits:
        if (row.get('origin_type') or '') == 'initial_import':
            continue
        evidence_id = row.get('evidence_id')
        expected_files = int_value(row.get('changed_files_count'))
        actual_files = file_by_commit[evidence_id]
        if expected_files != actual_files:
            changed_file_mismatches.append(
                f'{evidence_id}:{row.get("repo_path")} expected_files={expected_files} actual_files={actual_files}'
            )
        expected_ins = int_value(row.get('insertions'))
        expected_del = int_value(row.get('deletions'))
        actual_ins, actual_del = file_insertions_by_commit[evidence_id]
        if (expected_ins, expected_del) != (actual_ins, actual_del):
            insertion_mismatches.append(
                f'{evidence_id}:{row.get("repo_path")} commit=+{expected_ins}/-{expected_del} files=+{actual_ins}/-{actual_del}'
            )
    if changed_file_mismatches:
        blocking_issues.append(f'commit/file changed file count mismatch: {changed_file_mismatches[:10]}')
    if insertion_mismatches:
        non_blocking_issues.append(
            'commit shortstat differs from summed file stats for '
            f'{len(insertion_mismatches)} non-initial commit(s): {insertion_mismatches[:5]}'
        )

    dirty_mismatches = []
    for row in dirty_repos:
        evidence_id = row.get('evidence_id')
        expected = int_value(row.get('tracked_dirty_count')) + int_value(row.get('untracked_file_count'))
        actual = dirty_by_repo[evidence_id]
        if expected != actual:
            dirty_mismatches.append(
                f'{evidence_id}:{row.get("repo_path")} expected={expected} actual={actual}'
            )
    if dirty_mismatches:
        blocking_issues.append(f'dirty repo/file count mismatch: {dirty_mismatches[:10]}')

    changed_repos = {
        row.get('repo_path') or row.get('repo')
        for row in files
        if row.get('repo_path') or row.get('repo')
    }
    initial_import_count = commit_origin.get('initial_import', 0)
    post_import_count = sum(
        count for origin, count in commit_origin.items()
        if origin not in ('initial_import', 'merge_commit')
    )
    status = 'blocked' if blocking_issues else 'passed'
    output_files = [
        '02_statistics/statistics_summary.json',
        '02_statistics/statistics_summary.md',
        '02_statistics/repo_change_distribution.csv',
        '02_statistics/file_type_distribution.csv',
        '02_statistics/subsystem_distribution.csv',
        '02_statistics/binary_asset_summary.md',
        '02_statistics/qc_report.md',
    ]
    stats = {
        'stage': '03_statistics_qc',
        'status': status,
        'summary': (
            'Deterministic aggregation completed from raw records: '
            f'{len(commits)} commits, {len(files)} file changes, '
            f'{len(binary_rows)} binary assets, {len(dirty_files)} dirty files.'
        ),
        'commit_records_count': len(commits),
        'file_change_records_count': len(files),
        'binary_asset_records_count': len(binary_rows),
        'dirty_file_records_count': len(dirty_files),
        'repo_count': len(repo_rows) or len(repo_stats),
        'changed_repo_count': len(changed_repos),
        'initial_import_commit_count': initial_import_count,
        'post_import_commit_count': post_import_count,
        'blocking_issues': blocking_issues,
        'non_blocking_issues': non_blocking_issues,
        'output_files_written': output_files,
        'next_stage_inputs': [
            '02_statistics/statistics_summary.json',
            '02_statistics/qc_report.md',
        ],
    }

    (stats_dir / 'statistics_summary.json').write_text(
        json.dumps(stats, indent=2, ensure_ascii=False) + '\n',
        encoding='utf-8',
    )
    (stats_dir / 'statistics_summary.md').write_text(
        '\n'.join([
            '# Statistics Summary',
            '',
            f'Generated at: {datetime.now().astimezone().isoformat(timespec="seconds")}',
            '',
            markdown_table(
                ['Metric', 'Value'],
                [
                    ['commit_records_count', len(commits)],
                    ['file_change_records_count', len(files)],
                    ['binary_asset_records_count', len(binary_rows)],
                    ['dirty_file_records_count', len(dirty_files)],
                    ['repo_count', len(repo_rows) or len(repo_stats)],
                    ['changed_repo_count', len(changed_repos)],
                    ['initial_import_commit_count', initial_import_count],
                    ['post_import_commit_count', post_import_count],
                ],
            ),
            '',
            'All later reports must copy numeric counts from `statistics_summary.json`.',
            '',
        ]),
        encoding='utf-8',
    )
    write_csv(
        stats_dir / 'repo_change_distribution.csv',
        [
            'repo_path',
            'classification',
            'commit_records',
            'file_change_records',
            'dirty_file_records',
            'binary_asset_records',
            'insertions',
            'deletions',
        ],
        sorted(repo_stats.values(), key=lambda row: row['repo_path']),
    )
    write_csv(
        stats_dir / 'file_type_distribution.csv',
        ['source', 'file_type', 'count'],
        file_type_rows,
    )
    write_csv(
        stats_dir / 'subsystem_distribution.csv',
        ['classification', 'commit_records', 'file_change_records', 'dirty_file_records', 'binary_asset_records'],
        sorted(subsystem_stats.values(), key=lambda row: row['classification']),
    )
    (stats_dir / 'binary_asset_summary.md').write_text(
        '\n'.join([
            '# Binary Asset Summary',
            '',
            f'Total binary asset records: {len(binary_rows)}',
            '',
            '## Top Architectures',
            markdown_table(['Architecture', 'Count'], binary_arch.most_common(20)),
            '',
            '## Top Repositories',
            markdown_table(['Repo', 'Count'], binary_repo.most_common(20)),
            '',
            '## License Risk',
            markdown_table(['Risk', 'Count'], binary_license.most_common(20)),
            '',
            '## Redistribution Risk',
            markdown_table(['Risk', 'Count'], binary_redistribution.most_common(20)),
            '',
            '## Runtime Dependency',
            markdown_table(['Runtime Dependency', 'Count'], binary_runtime.most_common(20)),
            '',
        ]),
        encoding='utf-8',
    )
    qc_rows = [
        ['commit_records.jsonl parse errors', bad_commits],
        ['file_change_records.jsonl parse errors', bad_files],
        ['dirty_file_records.jsonl parse errors', bad_dirty],
        ['non-initial commit/file-count mismatches', len(changed_file_mismatches)],
        ['non-initial commit/file shortstat mismatches', len(insertion_mismatches)],
        ['dirty repo/file count mismatches', len(dirty_mismatches)],
        ['blocking issues', len(blocking_issues)],
        ['non-blocking issues', len(non_blocking_issues)],
    ]
    (stats_dir / 'qc_report.md').write_text(
        '\n'.join([
            '# Statistics QC Report',
            '',
            markdown_table(['Check', 'Result'], qc_rows),
            '',
            '## Blocking Issues',
            '',
            '\n'.join(f'- {issue}' for issue in blocking_issues) if blocking_issues else '- None',
            '',
            '## Non-Blocking Issues',
            '',
            '\n'.join(f'- {issue}' for issue in non_blocking_issues) if non_blocking_issues else '- None',
            '',
        ]),
        encoding='utf-8',
    )

    if args.stage_result:
        Path(args.stage_result).write_text(
            json.dumps(stats, indent=2, ensure_ascii=False) + '\n',
            encoding='utf-8',
        )
    print(json.dumps(stats, ensure_ascii=False))


if __name__ == '__main__':
    main()
