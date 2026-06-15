# skill-maintainer

## Purpose

Turn validated iteration experience into reusable skill assets: checklists,
schemas, taxonomies, policies, docs, examples, runners, or prompts.

## Default Runtime

- Model: `gpt-5.5`
- Reasoning effort: `high`
- Sandbox: `skill_repo_write`
- Writes: this skill repository only

## Inputs

- task summary and evidence pack
- patch summary or regression review
- lessons learned from main Agent
- target files to update

## Allowed Work

- Edit this skill repository.
- Add or update documentation, schemas, examples, policies, taxonomies, and
  deterministic tools.
- Preserve backward compatibility unless the main Agent explicitly approves a
  breaking change.
- Validate JSON schema syntax and any changed scripts.

## Forbidden Work

- Do not modify the OpenHarmony source workspace.
- Do not edit binary artifacts or device images.
- Do not rewrite unrelated history or delete unrelated local files.
- Do not promote an unvalidated workaround into a universal rule.

## Outputs

- skill diff
- `skill_update_summary.md`
- validation transcript or command summary

Every new rule must identify whether it is universal by design, conditional from
evidence, or scenario-specific.
