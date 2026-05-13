# Evidence Rules

1. Commit claims must cite `repo_path + commit_hash` from `commit_records.jsonl`.
2. File claims must cite `repo_path + file_path` from `file_change_records.jsonl` or `dirty_file_records.jsonl`.
3. Binary claims must cite `path + sha256` from `binary_asset_records.csv`.
4. Diff claims must cite a path under `01_raw_records/diffs/`.
5. If evidence is absent, write `unknown` or `inference`; do not state it as fact.
6. Workarounds must be separated from best practices.
7. `task_profile.yaml` is authoritative for scenario type unless a formal scope change request is generated.
