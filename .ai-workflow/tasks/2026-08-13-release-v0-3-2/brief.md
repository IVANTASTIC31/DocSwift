---
task_id: "2026-08-13-release-v0-3-2"
title: "发布 DocSwift v0.3.2"
status: PLANNED
created: "2026-08-13"
updated: "2026-08-13"
base_commit: "fe336d1"
orchestrator_agent: "codex"
execution_agent: "hermes"
role_policy: "orchestrator-worker"
permission_file_edits: "allow"
permission_dependency_install: "ask"
permission_git_commit: "allow"
permission_git_push: "allow"
permission_git_push_target: "origin/main,company/main,origin/v0.3.2,company/v0.3.2"
permission_local_database: "deny"
permission_deploy: "deny"
permission_deploy_target: "none"
permission_external_mutation: "deny"
permission_external_scope: "none"
---

# Task brief: 发布 DocSwift v0.3.2

## Confirmed facts

- 用户已将发布版本锁定为 `0.3.2`，要求创建 annotated tag `v0.3.2`，并将 `main` 与标签同时推送到 GitHub `origin` 和公司 Gitea `company`。
- 上一任务 `2026-08-13-review-confirm-export-flow` 已完成、人工验收通过，Codex 独立完整回归为 46 项通过；当前功能改动尚未提交。
- 当前 `HEAD` 为 `fe336d1`（`v0.3.1`），分支为 `main`；本地不存在 `v0.3.2` 标签。
- 当前 `.venv` 已安装 `PyInstaller==6.16.0`，仓库发布入口是 `release/build_release.ps1` 与 `release/prepare_internal_manifest.ps1`。
- 当前版本来源 `app_version.py`、构建脚本和内部清单脚本均仍为 `0.3.1`。
- 完整提交范围包括功能代码、测试、版本文件、中文文档、项目记忆协议与任务记录；明确排除 `.reasonix/`、`.serena/`、`build/`、`dist/` 和真实用户数据。
- 任务权限允许 Codex 最终提交与推送的唯一目标为 `origin/main`、`company/main`、`origin/v0.3.2`、`company/v0.3.2`；不允许服务器上传或部署。

## Goal

准备并验证 DocSwift v0.3.2 Windows 免安装发布物；由 Hermes 完成版本化、测试、ZIP、SHA-256 和内部更新清单后正式交回 Codex，再由 Codex完成最终审计、提交、annotated tag 和双远端推送。本任务不上传公司更新服务器。

## Non-goals

- 不改变已经人工验收的校对滚动、连续确认、最后一张导出确认和空白工序号表头行为。
- 不改变数据库结构、识别/分组规则、原子导出、更新源地址、包命名、哈希/大小校验或 ZIP 路径穿越防护。
- 不安装或升级依赖，不修改真实 `%LOCALAPPDATA%\DocSwift` 数据。
- 不创建 GitHub/Gitea Release，不上传 ZIP 或 `latest.json` 到公司服务器，不部署任何外部服务。
- Hermes 不执行 commit、tag 或 push；这些动作只能在其正式交回、Codex 最终审计和提交预检通过后执行。

## Acceptance criteria

1. `app_version.py`、发布构建脚本默认版本、内部清单脚本默认版本和 README 当前版本统一为 `0.3.2`；新增中文 `release/notes-v0.3.2.md`。
2. 内部清单默认 notes 准确概括 v0.3.2 的四项用户可见变化；不改变 `BaseUrl`、stable channel、`mandatory=false` 或下载路径格式。
3. 专项 UI、核心、更新服务测试及完整回归全部通过；完整回归不少于 46 项。
4. 构建成功生成非空 `dist/release/DocSwift-v0.3.2-windows-portable.zip` 和 `CHECKSUMS-SHA256.TXT`。
5. `CHECKSUMS-SHA256.TXT` 的文件名和 SHA-256 与 ZIP 实际值完全一致。
6. `dist/release/latest.json` 是 UTF-8 无 BOM 的合法 JSON，且 `manifest_version=1`、`application=DocSwift`、`channel=stable`、`version=0.3.2`、`mandatory=false`；文件名、大小和 SHA-256 与 ZIP 完全一致。
7. `download_url` 精确为 `http://192.168.100.3/updates/docswift/releases/v0.3.2/DocSwift-v0.3.2-windows-portable.zip`。
8. Hermes 在任务结果中记录实际命令、测试数量、ZIP 路径、字节数、SHA-256、清单字段、未测试项与风险，并正式交回 Codex。
9. Codex 最终只暂存授权范围，明确排除 `.reasonix/`、`.serena/`、`build/`、`dist/`，完成当前任务最终审计与 `prepare-commit` 门禁后创建一个连贯提交。
10. Codex 创建 annotated tag `v0.3.2`；推送前分别获取并确认 `origin/main` 与 `company/main` 未出现未知分叉，禁止强推。
11. 推送完成后，两个远端 `main` 指向同一发布提交，两个远端均存在指向该提交的 annotated tag `v0.3.2`；构建产物仅保留本机供用户上传公司服务器。

## Existing worktree state

- 任务开始时 `main` 位于 `fe336d1`，工作树已有上一任务的产品改动：`.gitignore`、`README.md`、`app.py`、`core.py`、`tests/test_core.py`、`tests/test_ui_smoke.py`。
- 未跟踪但计划纳入完整项目提交的正式内容：`.agents/`、`.ai-workflow/`、`.claude/`、`AGENTS.md`、`CHANGELOG.md`、`CLAUDE.md`、`docs/`。
- 未跟踪且必须保留在本机、不得修改或纳入提交：`.reasonix/`、`.serena/`。
- `build/`、`dist/` 为被忽略的构建产物；允许发布脚本在其中替换 v0.3.2 产物，但不得暂存。
- 上一任务审计在创建本任务包后显示为 `STALE` 属于预期；本任务必须建立自己的最终审计收据。

## Expected files and interfaces

- Hermes 预计修改：`app_version.py`、`release/build_release.ps1`、`release/prepare_internal_manifest.ps1`、`release/notes-v0.3.2.md`、`README.md` 和本任务 `result.md`；只有必要时才修改测试。
- `CHANGELOG.md`、`docs/STATUS.md` 和其他项目级状态文档由 Codex 在 Hermes 交回后更新；Hermes 不得修改受保护文档、任务 brief、权限、运行时、ARCHITECTURE 或 ADR。
- 对外接口保持：包名 `DocSwift-v<version>-windows-portable.zip`，内部清单 schema 版本 `1`，应用标识 `DocSwift`。

## Validation commands

```powershell
$env:PYTHONPATH=''
.venv\Scripts\python.exe -m unittest tests.test_ui_smoke -v
.venv\Scripts\python.exe -m unittest tests.test_core -v
.venv\Scripts\python.exe -m unittest tests.test_update_service -v
.venv\Scripts\python.exe -m unittest discover -s tests -v
powershell -NoProfile -ExecutionPolicy Bypass -File release\build_release.ps1 -Version 0.3.2
powershell -NoProfile -ExecutionPolicy Bypass -File release\prepare_internal_manifest.ps1 -Version 0.3.2
```

## Safety and authorization boundaries

- Preserve unrelated changes.
- The structured permission fields in this task's frontmatter are authoritative for this task only.
- Do not carry commit, push, deploy, or external-mutation authorization into another task.
- Do not read or record secrets beyond ordinary task-relevant configured access.

## Documentation impact expected

- `README.md`：Hermes 更新当前版本和 v0.3.2 用户流程说明。
- `release/notes-v0.3.2.md`：Hermes 新增中文发布说明。
- `CHANGELOG.md`：Codex 在交回后将“尚未发布”内容归档为 v0.3.2。
- `docs/STATUS.md`：Codex 维护活动任务、最终验证、提交、标签和双远端推送状态。
- `docs/ARCHITECTURE.md`、ADR、runbook：预计无影响，系统边界、数据流和运维拓扑未变。
