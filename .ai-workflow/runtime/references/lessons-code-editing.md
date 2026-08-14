# Code-editing lessons

## EDIT-001 — Preserve the existing worktree

- Applies when: editing an existing repository, especially a dirty worktree.
- Failure: an agent treats pre-existing changes as disposable or replaces a file wholesale.
- Root cause: no baseline inspection and no distinction between task changes and user changes.
- Guardrail: run `git status --short`, inspect relevant diffs, patch narrowly, and recheck the diff afterward.
- Verification: unrelated paths and hunks remain unchanged.
- Exception: discard only the exact changes the user explicitly authorizes removing.

## EDIT-002 — Protect verification integrity

- Applies when: reporting builds, tests, deployments, migrations, or runtime behavior.
- Failure: documentary language implies success although a check was skipped or only inferred.
- Root cause: expected behavior is confused with observed evidence.
- Guardrail: record the exact command, exit result, and meaningful limitation; label skipped checks as unverified.
- Verification: every success claim has corresponding current-turn evidence.
