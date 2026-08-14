# Git lessons

## GIT-001 — Separate change history from decision rationale

- Applies when: documenting project history.
- Failure: a handoff copies long Git logs but still cannot explain why a design was selected.
- Root cause: commit history and architectural rationale are treated as the same artifact.
- Guardrail: keep code-level changes in coherent commits; record consequential rationale, alternatives, and consequences in ADRs; link rather than duplicate.
- Verification: a maintainer can find both the implementation commit and the reason for the decision.

## GIT-002 — Preserve reconstructable checkpoints

- Applies when: a repository is developed through many AI-generated changes.
- Failure: one oversized baseline or mixed commit hides feature evolution and regression boundaries.
- Root cause: commits are used as storage snapshots rather than reviewable units.
- Guardrail: commit one coherent outcome with its tests and relevant documentation; keep unrelated work separate.
- Verification: `git log --stat` shows meaningful, bounded steps.
- Exception: an unavoidable initial import may be large; document that it is a retrospective baseline and improve granularity afterward.
