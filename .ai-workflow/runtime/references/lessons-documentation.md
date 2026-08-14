# Documentation lessons

## DOC-001 — Give volatile facts one canonical owner

- Applies when: version, port, stage, active task, or deployment state appears in multiple files.
- Failure: documents disagree and an incoming agent cannot identify the current value.
- Root cause: the same fact is copied instead of linked.
- Guardrail: choose one owning document and let other documents link to it.
- Verification: repository search finds either one value or clearly generated mirrors.

## DOC-002 — Give every task a stable identity

- Applies when: multiple agents or sessions use task briefs and results.
- Failure: a singleton `task.md` and `result.md` describe different tasks after overwrite or reuse.
- Root cause: task identity is encoded only in mutable filenames or headings.
- Guardrail: store both files under `.ai-workflow/tasks/<task-id>/` and repeat the ID in metadata.
- Verification: brief and result task IDs match.

## DOC-003 — Update by impact, not ritual

- Applies when: deciding whether a code change requires documentation.
- Failure: every commit causes meaningless edits to many Markdown files, creating noise and merge conflicts.
- Root cause: document updates are tied to commit frequency rather than information ownership.
- Guardrail: use the event-routing matrix and update only affected owners.
- Verification: each documentation diff represents a real changed fact, decision, procedure, or user-visible outcome.

## DOC-004 — Runtime claims expire

- Applies when: handoffs mention running services, ports, deployed builds, or passing checks.
- Failure: a later agent trusts a stale operational claim.
- Root cause: ephemeral observations are written as timeless facts.
- Guardrail: include `last_verified`, the verification command, and environment; recheck before acting.
- Verification: current executable evidence matches the document.
