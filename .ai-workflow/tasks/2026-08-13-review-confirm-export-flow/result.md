---
task_id: "2026-08-13-review-confirm-export-flow"
title: "优化校对确认流程与导出表头"
status: "DONE"
updated: "2026-08-13"
base_commit: "fe336d1"
orchestrator_agent: "codex"
execution_agent: "hermes"
last_verified: "2026-08-13T12:26:05+08:00"
audit_status: "PASSED"
audited_at: "2026-08-13T12:26:05+08:00"
audited_by: "codex"
audited_commit: "fe336d1083646d5c66cee928fdfee3523860b2a1"
audited_worktree_fingerprint: "bbd6092ba9e22460"
---

# Task result: 优化校对确认流程与导出表头

## Outcome

四项用户可见行为已实现并通过回归：

1. 校对表长工序内容不再受 `120` 像素行高上限截断；行高按内容（显式换行 + 自动换行）估算，表格竖向滚动条按需显示。
2. 点击“确认当前工艺卡”成功后，按左侧当前排序自动选中下一张 `PENDING` 工艺卡（末尾回绕到首张），并同步刷新右侧详情与预览。
3. 确认最后一张未完成工艺卡后，复用现有 `_export_confirmed` 流程弹出批量导出确认；用户拒绝只取消导出，不撤销确认结果。
4. 生成的 Excel 工序号数据列首行（D1）保持空白，第 2 行起仍写入源工艺卡实际工序号且不重新编号。
5. Codex 审查时补充内容列宽变化后的行高重算，避免用户拖窄面板后软换行再次被截断。

## Changed files

- `app.py`：新增 `_operation_row_height` 替代原 `min(120, ...)` 行高计算，内容列宽变化时重算行高；`operations_table` 明确竖向滚动条策略与滚动模式；`_confirm_current_card` 增加连续确认与最后一张导出入口；新增 `_next_pending_card_id`。
- `core.py`：`generate_template` 不再把工序号列表头写成“工序号”，改为留空（None）。
- `tests/test_core.py`：原 `test_generation_fills_blank_operation_header_and_formats_cells` 改名并改为断言表头空白；新增 `test_atomic_export_keeps_operation_header_blank_and_preserves_numbers`。
- `tests/test_ui_smoke.py`：新增 4 项回归（长内容行高与滚动、确认后切卡、最后一张触发导出、存在未完成卡时不触发导出）。

## Decisions

无新增 ADR；本任务未改变系统边界、持久化结构或运维流程，属于既有行为修正。

## Verification performed

| Command or check | Result | Limitations |
| --- | --- | --- |
| `.venv\Scripts\python.exe -m unittest tests.test_core -v` | PASS（7 项） | 无 |
| `.venv\Scripts\python.exe -m unittest tests.test_ui_smoke -v` | PASS（8 项） | offscreen 平台，未做真实鼠标交互验收 |
| `.venv\Scripts\python.exe -m unittest discover -s tests -v` | PASS（46 项） | 见下方环境注记 |
| Codex 独立复跑上述三条命令 | PASS（UI 8 项、core 7 项、完整 46 项） | `QT_QPA_PLATFORM=offscreen`，未做真实窗口手动验收 |

环境注记：本机 Hermes 桌面环境会注入 `PYTHONPATH`（指向 hermes-agent 目录），其内含的 `tests` 包会遮蔽项目内 `tests`，导致 `tests.test_*` 导入失败。执行上述命令前需 `unset PYTHONPATH`（或在干净环境运行）；项目自身代码无此依赖。

## Failures and untested items

- 未做真实 GUI 手动验收（滚动、按钮可见性、导出对话框交互），仅以 offscreen 自动化断言覆盖。
- 未改动真实 `%LOCALAPPDATA%\DocSwift`；测试全程使用 TemporaryDirectory，UI 测试显式把 `LOCALAPPDATA` 指到临时目录。
- Codex 加固软换行测试时首次用 `setColumnWidth` 模拟缩窄，但内容列为 `Stretch` 模式，实际宽度未改变，测试因此失败；改为测试内临时使用 `Interactive` 模式后通过，随后完整回归再次通过。

## Remaining risks

- 行高估算使用当前列宽与 QFontMetrics，初次布局前列宽取 420px 回退值；内容列宽变化会自动重算。极端字体/缩放下高度仍可能偏保守。
- `_confirm_current_card` 现在会在最后一张确认后立即弹出导出确认框，属于预期交互变更，需 Codex 验收文案与流程。

## Documentation updates

- `README.md`：同步连续确认、自动导出确认、长内容滚动和 D1 空白映射说明。
- `CHANGELOG.md`：记录三类用户可见行为变更。
- `docs/STATUS.md`：由 Codex 在最终审计与关闭任务时更新。

## Exact next action

1. 如需发布这些改动，创建新任务并重新授权 commit 与 push。

## Worktree and external state

- Worktree：已改动 `app.py`、`core.py`、`tests/test_core.py`、`tests/test_ui_smoke.py`；未触碰任务开始前已存在的 `.gitignore`、`README.md` 修改及未跟踪目录（`.agents/`、`.ai-workflow/`、`.claude/`、`.reasonix/`、`.serena/`、`AGENTS.md`、`CHANGELOG.md`、`CLAUDE.md`、`docs/`）。
- Commit/push/deployment/shared-data changes: none（未提交、未推送、未改动真实数据库/更新服务器/发布目标）。
