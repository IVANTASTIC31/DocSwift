---
task_id: "2026-08-13-release-v0-3-2"
title: "发布 DocSwift v0.3.2"
status: "DONE"
updated: "2026-08-13"
base_commit: "fe336d1"
orchestrator_agent: "codex"
execution_agent: "hermes"
last_verified: "2026-08-13T13:14:06+08:00"
audit_status: "PASSED"
audited_at: "2026-08-13T13:14:06+08:00"
audited_by: "codex"
audited_commit: "fe336d1083646d5c66cee928fdfee3523860b2a1"
audited_worktree_fingerprint: "03e8a5d17a97718e"
---

# Task result: 发布 DocSwift v0.3.2

## Outcome

v0.3.2 版本化、测试、ZIP、SHA-256 与内部更新清单已全部完成并验证，等待 Codex 最终审计、提交、annotated tag 与双远端推送。

- 版本统一为 `0.3.2`（`app_version.py`、两个发布脚本默认版本、README）。
- 新增中文 `release/notes-v0.3.2.md`，概括四项用户可见变化。
- 生成非空 `dist/release/DocSwift-v0.3.2-windows-portable.zip`、`CHECKSUMS-SHA256.TXT` 与 `latest.json`，三者字段、大小、SHA-256 完全一致，`download_url` 精确匹配。
- 未执行 commit/tag/push、未上传服务器、未修改真实 `%LOCALAPPDATA%\DocSwift`。
- 用户明确要求公司服务器上传由其人工完成；本任务不会上传 ZIP、校验文件或内部清单，也不会创建远端 Release。

## Changed files

- `app_version.py`：`__version__` 0.3.1 → 0.3.2。
- `release/build_release.ps1`：默认版本 0.3.1 → 0.3.2。
- `release/prepare_internal_manifest.ps1`：默认版本 0.3.1 → 0.3.2；默认 notes 更新为 v0.3.2 中文四项概括；文件保存为 UTF-8 with BOM（保证 PowerShell 5.1 正确读取中文 notes）。
- `release/notes-v0.3.2.md`：新增中文发布说明。
- `README.md`：当前程序版本 v0.3.1 → v0.3.2。
- `result.md`：本文件。

未修改 `CHANGELOG.md`、`docs/STATUS.md`、`docs/ARCHITECTURE.md`、ADR、任务 brief、权限或项目运行时（均交由 Codex）。

## Decisions

- manifest notes 采用中文以匹配用户中文环境；因 Windows PowerShell 5.1 对无 BOM 的 UTF-8 `.ps1` 按系统 ANSI（GBK）误读，`prepare_internal_manifest.ps1` 改为 UTF-8 with BOM（已实测验证编码正确）。其余 ASCII 脚本保持不变。
- 未新增 ADR；本任务不改变系统边界、持久化结构或运维流程。

## Verification performed

| Command or check | Result | Limitations |
| --- | --- | --- |
| `.venv\Scripts\python.exe -m unittest tests.test_ui_smoke -v` | PASS（8 项） | offscreen |
| `.venv\Scripts\python.exe -m unittest tests.test_core -v` | PASS（7 项） | 无 |
| `.venv\Scripts\python.exe -m unittest tests.test_update_service -v` | PASS（19 项） | 无 |
| `.venv\Scripts\python.exe -m unittest discover -s tests -v` | PASS（46 项） | 无 |
| `powershell -File release\build_release.ps1 -Version 0.3.2` | PASS，生成 ZIP + CHECKSUMS | 本机构建 |
| `powershell -File release\prepare_internal_manifest.ps1 -Version 0.3.2` | PASS，生成 latest.json | 本机 |
| ZIP 存在且非空 | PASS，56,181,865 bytes | 无 |
| CHECKSUMS-SHA256.TXT 与 ZIP 实际 SHA-256 一致 | PASS | 无 |
| latest.json 无 BOM 且合法 JSON | PASS | 无 |
| 清单字段与 ZIP 完全一致 | PASS | 无 |
| download_url 精确匹配 | PASS | 无 |
| `project_memory.py audit --root . --actor hermes` | PASS（exit 0，只读） | 仅结构/文档影响启发式 |
| Codex 独立复跑 `.venv\Scripts\python.exe -m unittest discover -s tests -v` | PASS（46 项） | 未在另一台干净机器运行 |
| Codex 独立校验 ZIP、CHECKSUMS 与 latest.json | PASS | ZIP `56181865` 字节；三处 SHA-256 一致；latest.json UTF-8 无 BOM |

关键产物：

- ZIP：`dist/release/DocSwift-v0.3.2-windows-portable.zip`
- 字节数：`56181865`
- SHA-256：`5fd39be845f5c9de0c692cd2f4225061a4de1859e79c7d73c06b64f6e2be7554`
- 清单：`manifest_version=1`、`application=DocSwift`、`channel=stable`、`version=0.3.2`、`mandatory=false`、`size=56181865`、`sha256=<同上>`、`download_url=http://192.168.100.3/updates/docswift/releases/v0.3.2/DocSwift-v0.3.2-windows-portable.zip`

## Failures and untested items

- 未做真实 GUI 手动验收；本任务只验证发布产物，功能行为已由上一任务 `2026-08-13-review-confirm-export-flow` 人工验收。
- 未实际上传公司更新服务器、未创建 GitHub/Gitea Release（brief 明确禁止，交由用户/后续）。
- 未在干净机器上解压运行免安装 ZIP 做冒烟（本机已通过完整回归）。

## Remaining risks

- `prepare_internal_manifest.ps1` 现为 UTF-8 with BOM；若后续用不支持 BOM 的工具重写该文件可能破坏中文 notes 编码，Codex 提交时需保留 BOM。
- 构建产物 `build/`、`dist/` 为本地生成、已被 `.gitignore` 忽略，未暂存；最终由用户自行上传公司服务器。

## Documentation updates

- 本任务更新 `README.md`（当前版本号）与新增 `release/notes-v0.3.2.md`。
- `CHANGELOG.md`（归档 v0.3.2）、`docs/STATUS.md`（活动/最终状态）由 Codex 在交回后处理。

## Exact next action

1. 推送前刷新 origin 与 company，确认 main 无分叉后提交、创建 v0.3.2 annotated tag 并推送代码与标签；服务器上传由用户人工完成。

## Worktree and external state

- Worktree：改动 `app_version.py`、`release/build_release.ps1`、`release/prepare_internal_manifest.ps1`、`release/notes-v0.3.2.md`、`README.md`、`result.md`；上一任务的产品改动（`app.py`、`core.py`、`tests/`、`README.md`）仍保留在工作树，未回滚。
- Commit/push/deployment/shared-data changes: none（未 commit/tag/push、未上传、未改真实数据库/更新服务器）。
