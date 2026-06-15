# Replay Eval

Replay evals compare deterministic tool output against historical expected
signals. Keep samples small and evidence-bound; do not copy full build or
serial logs into the skill repository.

## Case Shape

```text
replay_eval/cases/<case_id>/
  case.yaml
```

Minimal `case.yaml`:

```yaml
case_id: build-missing-target
taxonomy: ../../taxonomies/build_error_taxonomy.yaml
logs:
  - /path/to/log_slice_input.log
expected_signatures:
  - gn_missing_label_or_target
```

## Run

```bash
python3 replay_eval/run_eval.py --cases-root replay_eval/cases --out replay_eval/result.yaml
```

The runner reports which expected signatures were found by `tools/log_slice.py`
without asking a model to read full logs.
