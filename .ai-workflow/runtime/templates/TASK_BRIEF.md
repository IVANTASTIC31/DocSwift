---
task_id: "{{TASK_ID}}"
title: {{TITLE_YAML}}
status: PLANNED
created: "{{DATE}}"
updated: "{{DATE}}"
base_commit: "{{HEAD}}"
orchestrator_agent: "{{ORCHESTRATOR_AGENT}}"
execution_agent: "{{EXECUTION_AGENT}}"
role_policy: "{{ROLE_POLICY}}"
permission_file_edits: "{{PERMISSION_FILE_EDITS}}"
permission_dependency_install: "{{PERMISSION_DEPENDENCY_INSTALL}}"
permission_git_commit: "{{PERMISSION_GIT_COMMIT}}"
permission_git_push: "{{PERMISSION_GIT_PUSH}}"
permission_git_push_target: {{PERMISSION_GIT_PUSH_TARGET_YAML}}
permission_local_database: "{{PERMISSION_LOCAL_DATABASE}}"
permission_deploy: "{{PERMISSION_DEPLOY}}"
permission_deploy_target: {{PERMISSION_DEPLOY_TARGET_YAML}}
permission_external_mutation: "{{PERMISSION_EXTERNAL_MUTATION}}"
permission_external_scope: {{PERMISSION_EXTERNAL_SCOPE_YAML}}
---

# Task brief: {{TITLE}}

## Confirmed facts

<!-- Facts verified from code, Git, tests, or the user. -->

## Goal

<!-- One concrete outcome. -->

## Non-goals

<!-- Explicitly excluded work. -->

## Acceptance criteria

1. <!-- Observable criterion -->

## Existing worktree state

<!-- Record relevant pre-existing changes that must be preserved. -->

## Expected files and interfaces

<!-- Guidance, not permission to overwrite. -->

## Validation commands

```text
<commands verified from the repository>
```

## Safety and authorization boundaries

- Preserve unrelated changes.
- The structured permission fields in this task's frontmatter are authoritative for this task only.
- Do not carry commit, push, deploy, or external-mutation authorization into another task.
- Do not read or record secrets beyond ordinary task-relevant configured access.

## Documentation impact expected

<!-- STATUS / ARCHITECTURE / ADR / runbook / changelog / lesson / none, with reason. -->
