# Security lessons

## SEC-001 — Project memory is not a secret store

- Applies when: writing README, handoff, runbook, task, log, or example configuration.
- Failure: working credentials, tokens, internal sensitive data, or raw logs enter versioned Markdown.
- Root cause: operational convenience is prioritized over credential lifecycle.
- Guardrail: use placeholders and reference the approved secret manager or secure handoff channel. Sanitize evidence before cross-project promotion.
- Verification: inspect staged and untracked documentation for credential material before commit.

## SEC-002 — Removing text does not revoke a leaked credential

- Applies when: a credential has appeared in Git or another shared durable record.
- Failure: deleting it from the latest file is treated as remediation.
- Root cause: persistence in history and clones is ignored.
- Guardrail: remove the current reference, rotate or revoke the credential, assess history cleanup separately, and notify affected operators.
- Verification: the old credential no longer works and the replacement is delivered through an approved channel.
