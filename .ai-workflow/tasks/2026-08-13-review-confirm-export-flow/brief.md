---
task_id: "2026-08-13-review-confirm-export-flow"
title: "优化校对确认流程与导出表头"
status: PLANNED
created: "2026-08-13"
updated: "2026-08-13"
base_commit: "fe336d1"
orchestrator_agent: "codex"
execution_agent: "hermes"
role_policy: "orchestrator-worker"
permission_file_edits: "allow"
permission_dependency_install: "ask"
permission_git_commit: "deny"
permission_git_push: "deny"
permission_git_push_target: "none"
permission_local_database: "deny"
permission_deploy: "deny"
permission_deploy_target: "none"
permission_external_mutation: "deny"
permission_external_scope: "none"
---

# Task brief: 优化校对确认流程与导出表头

## Confirmed facts

- 用户截图显示：校对表中合并后的长工序内容被截断，当前需要双击进入多行编辑窗口才能查看全文。
- `app.py` 当前把校对表长文本行高度限制为最多 `120`，虽已启用自动换行，但无法在表格内直接看全内容。
- `app.py::_confirm_current_card` 当前确认后仍选中原卡，不会切换到下一张 `PENDING` 工艺卡，也不会在最后一张确认后触发导出确认。
- `app.py::_export_confirmed` 已有批量导出确认对话框和原子导出流程，应复用，不另造第二套导出实现。
- `core.py::generate_template` 当前会强制把工序号列首行写成“工序号”；用户要求输出文件该表头为空，但 D 列数据仍保留源工艺卡的实际工序号。
- 当前基线为 `fe336d1`（`v0.3.1`）；最近一次完整验证为 41 项测试通过。

## Goal

让多卡校对流程可以连续完成：长工序内容无需打开编辑弹窗即可在主表中完整查看；确认一张后自动进入下一张待确认卡；全部工艺卡确认完成后打开现有导出确认窗口；生成的 Excel 工序号列表头保持空白。

## Non-goals

- 不改变 Word 识别、连续工序分组、排除项或原始工序号规则。
- 不改变 SQLite 架构、任务数据所有权、批量导出原子性或重复路线替换语义。
- 不改变 Excel 工序号数据列的位置与内容；只调整首行表头显示。
- 不重做校对界面布局，不移除双击多行编辑能力。
- 不修改自动更新、发布或外部服务。

## Acceptance criteria

1. 校对表右侧明确显示竖向滚动条；包含多行且发生自动换行的“工序内容”行按内容需要增高，不再受 `120` 像素上限截断，用户无需双击即可通过主表滚动查看全文。
2. 长行展开后，表格下方的新增、删除、合并、拆分、移动、恢复、重新编辑和确认按钮仍可见可用；表格通过竖向滚动承载超出空间的行。
3. 点击“确认当前工艺卡”成功后，按左侧工艺卡当前排序自动选中下一张 `PENDING` 工艺卡，并同步刷新右侧详情与预览；若当前项后面没有待确认卡但前面仍有，则回到排序中的第一张待确认卡。
4. 仍有待确认卡时不得弹出导出确认窗口；确认流程不得自动确认、跳过或改变其他卡片状态。
5. 当本次确认后任务内所有工艺卡均处于 `CONFIRMED` 或 `EXPORTED` 状态时，调用现有 `_export_confirmed` 流程，显示现有“将 N 张已确认工艺卡统一写入目标 Excel”确认窗口；用户拒绝时只取消导出，不撤销确认结果。
6. 若仍存在 `UNRECOGNIZED`、`QUEUED`、`RECOGNIZING`、`PENDING` 或 `SOURCE_CHANGED` 工艺卡，不得把当前卡误判为“最后一张”并自动进入导出确认。
7. 生成或原子更新 Excel 后，工序号数据列的首行必须为空；该列第 2 行起继续写入源工艺卡实际工序号，且不重新编号。空白 D1 的标准 9 列模板仍按 `D=工序号、E=工序内容` 回退映射。
8. 新增自动化回归覆盖：长文本行完整显示与竖向滚动、确认后选择下一张待确认卡、最后一张确认后触发导出确认、存在未完成卡时不触发导出、Excel 空白工序号表头且数据不丢失。
9. 保持现有 41 项测试通过，并遵守原子导出、源文件不删除和真实 `%LOCALAPPDATA%\DocSwift` 不可修改等项目不变量。

## Existing worktree state

- 任务开始前工作树已存在用户的未提交内容：`.gitignore`、`README.md`，以及未跟踪的 `.agents/`、`.ai-workflow/`、`.claude/`、`.reasonix/`、`.serena/`、`AGENTS.md`、`CHANGELOG.md`、`CLAUDE.md`、`docs/`。
- 上述内容不得删除、回滚或整体暂存；`.reasonix/` 与 `.serena/` 明确属于用户已有目录。
- `start-task` 已创建本任务目录；因项目运行时查找英文 `Active work` 标题而未能自动更新中文 `docs/STATUS.md`，Codex 已负责修复状态指针，worker 不得改写运行时或项目级文档。

## Expected files and interfaces

- `app.py`：校对表行高/滚动策略、确认后的卡片选择与最后一张确认后的导出入口。
- `core.py`：输出工作簿工序号列首行保持空白，数据列映射和写入语义不变。
- `tests/test_ui_smoke.py`：校对表显示、自动切卡和导出触发回归。
- `tests/test_core.py`：空白表头与工序号数据保留回归。
- 本任务 `result.md`：由 Hermes 记录实际改动、验证、未测项、风险和下一步。
- Hermes 不得修改 `brief.md`、`docs/STATUS.md`、`docs/ARCHITECTURE.md`、ADR、`CHANGELOG.md` 或权限字段；这些由 Codex 在交回后按影响更新。

## Validation commands

```powershell
.venv\Scripts\python.exe -m unittest tests.test_ui_smoke -v
.venv\Scripts\python.exe -m unittest tests.test_core -v
.venv\Scripts\python.exe -m unittest discover -s tests -v
```

## Safety and authorization boundaries

- Preserve unrelated changes.
- The structured permission fields in this task's frontmatter are authoritative for this task only.
- Do not carry commit, push, deploy, or external-mutation authorization into another task.
- Do not read or record secrets beyond ordinary task-relevant configured access.

## Documentation impact expected

- `result.md`：必须更新，记录实现与实际测试证据。
- `docs/STATUS.md`：由 Codex 在 Hermes 交回后更新活动状态、验证和下一步。
- `CHANGELOG.md`：4 项均为用户可见行为，由 Codex 在验收后补充。
- `README.md`：现有“D1 为空时自动补全”说明将与新需求冲突，由 Codex 在验收后改为“D1 保持空白但按固定列回退映射”。
- `docs/ARCHITECTURE.md`、ADR、runbook：预计无需更新，本任务不改变系统边界、持久化结构或运维流程。
