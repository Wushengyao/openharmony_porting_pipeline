# Evidence Rules

1. Commit claims must cite `repo_path + commit_hash` from `commit_records.jsonl`.
2. File claims must cite `repo_path + file_path` from `file_change_records.jsonl` or `dirty_file_records.jsonl`.
3. Binary claims must cite `path + sha256` from `binary_asset_records.csv`.
4. Diff claims must cite a path under `01_raw_records/diffs/`.
5. If evidence is absent, write `unknown` or `inference`; do not state it as fact.
6. Workarounds must be separated from best practices.
7. `task_profile.yaml` is authoritative for scenario type unless a formal scope change request is generated.
8. Reusable cases must use one canonical `evidence:` block with `commits`, `files`, `diffs`, and optional `dirty_records`/`binary_records`; do not add a separate validator-only evidence block.
9. Every concrete source path mentioned in case prose must resolve to `file_change_records.jsonl` or `dirty_file_records.jsonl`, or be explicitly marked `unknown`.
10. Dirty and binary records may be attached to a case or feature only by same repo, path prefix, or strong theme keyword match; broad classification-only attachment is risk-only.
