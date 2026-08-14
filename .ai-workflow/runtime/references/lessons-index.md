# Active lesson index

Read this index during initialization and audit. Load only the referenced category needed for the current work.

| ID | Guardrail summary | Category |
| --- | --- | --- |
| EDIT-001 | Inspect and preserve existing worktree changes before editing. | code-editing |
| EDIT-002 | Treat verification as evidence: never claim a check that was not run. | code-editing |
| GIT-001 | Use Git for changes and ADRs for rationale; do not duplicate full history in prose. | git |
| GIT-002 | Keep commits coherent enough to reconstruct feature evolution. | git |
| SEC-001 | Keep live credentials and sensitive raw logs out of project memory. | security |
| SEC-002 | If a credential entered Git, remove it from current files and rotate it. | security |
| DOC-001 | Assign one canonical owner for volatile facts to prevent drift. | documentation |
| DOC-002 | Use task-ID directories instead of reusable singleton task/result files. | documentation |
| DOC-003 | Update documents by event impact, not mechanically on every commit. | documentation |
| DOC-004 | Recheck ephemeral runtime claims before relying on them. | documentation |

Detailed rationale and exceptions live in the category references.
