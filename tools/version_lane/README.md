# Version Lane Tools

Use the existing four-tree analyzer as the primary implementation:

```bash
python3 tools/compare_four_tree_upgrade.py \
  --old-original /path/to/old_original \
  --old-ported /path/to/old_ported \
  --new-original /path/to/new_original \
  --new-workspace /path/to/new_workspace \
  --out /path/to/out
```

Future wrappers in this directory should stay thin and preserve the same
evidence model: upstream absorbed, directly reusable, manual migration,
conflict, generated output, and binary dependency.
