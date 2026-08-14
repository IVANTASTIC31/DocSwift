# Core workflow guardrails

These rules define the project-memory protocol. They are maintained separately from incident-derived lessons and are always compiled into the managed `AGENTS.md` section.

| ID | Guardrail summary |
| --- | --- |
| FLOW-001 | Complete project intake and task authorization before scaffolding an empty project. |
| FLOW-002 | Before creating a new task, close, pause, or explicitly continue the current active task. |
| FLOW-003 | Treat permissions as task-scoped; never carry commit, push, deploy, or external-mutation authorization into another task. |
| FLOW-004 | Run and record a current project-memory audit before preparing a commit or closing work as ready or done. |
| FLOW-005 | When an interactive chooser is unavailable, present the same choices as numbered text without weakening the gate. |
| FLOW-006 | Write every user-facing Markdown document in Chinese; retain technical identifiers in their original form when needed for correctness. |
| FLOW-007 | In orchestrator-worker projects, only the active Agent recorded for the task may perform controlled writes, and every Agent switch requires a fingerprinted handoff and explicit acceptance. |
| FLOW-008 | Treat the project-local runtime, collaboration configuration, task coordination, and their hashes as the portable protocol; refuse guarded work when integrity or actor ownership cannot be verified. |
