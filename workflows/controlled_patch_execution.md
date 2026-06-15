# Controlled Patch Execution

`patch-writer` may edit an OpenHarmony source workspace only when all are true:

- writer lock is recorded;
- task schema validates;
- allowed write roots are explicit;
- `policies/path_whitelist.yaml` permits the scope or main Agent approved the
  exception;
- validation plan is present;
- high-risk approval exists when required.

After editing, the writer returns:

- changed file list;
- diff summary;
- risk items;
- validation requested;
- any dependency debt.

The main Agent runs risk scanners before build or flash.
