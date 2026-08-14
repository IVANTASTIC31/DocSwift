# Project instructions for AI agents

Project memory schema: `4`
Generated from: `maintain-project-memory`

## Managed cross-project guardrails

<!-- project-memory:managed:start -->
<!-- project-memory:profile:a7b2ad6422bd -->
<!-- project-memory:categories:all -->

Core workflow guardrails:
- Complete project intake and task authorization before scaffolding an empty project. `[FLOW-001]`
- Before creating a new task, close, pause, or explicitly continue the current active task. `[FLOW-002]`
- Treat permissions as task-scoped; never carry commit, push, deploy, or external-mutation authorization into another task. `[FLOW-003]`
- Run and record a current project-memory audit before preparing a commit or closing work as ready or done. `[FLOW-004]`
- When an interactive chooser is unavailable, present the same choices as numbered text without weakening the gate. `[FLOW-005]`
- Write every user-facing Markdown document in Chinese; retain technical identifiers in their original form when needed for correctness. `[FLOW-006]`
- In orchestrator-worker projects, only the active Agent recorded for the task may perform controlled writes, and every Agent switch requires a fingerprinted handoff and explicit acceptance. `[FLOW-007]`
- Treat the project-local runtime, collaboration configuration, task coordination, and their hashes as the portable protocol; refuse guarded work when integrity or actor ownership cannot be verified. `[FLOW-008]`

Approved cross-project lessons:
- Inspect and preserve existing worktree changes before editing. `[EDIT-001]`
- Treat verification as evidence: never claim a check that was not run. `[EDIT-002]`
- Use Git for changes and ADRs for rationale; do not duplicate full history in prose. `[GIT-001]`
- Keep commits coherent enough to reconstruct feature evolution. `[GIT-002]`
- Keep live credentials and sensitive raw logs out of project memory. `[SEC-001]`
- If a credential entered Git, remove it from current files and rotate it. `[SEC-002]`
- Assign one canonical owner for volatile facts to prevent drift. `[DOC-001]`
- Use task-ID directories instead of reusable singleton task/result files. `[DOC-002]`
- Update documents by event impact, not mechanically on every commit. `[DOC-003]`
- Recheck ephemeral runtime claims before relying on them. `[DOC-004]`
<!-- project-memory:managed:end -->

## Project-specific instructions

本节来自 DocSwift 仓库实况；同步全局规则时不得覆盖。

### Build and validation

- 开发启动：`run.bat --console`；常规无终端启动使用 `run.bat` 或 `DocSwift.vbs`。
- 测试：`python -m unittest discover -s tests -v`。
- 发布构建：`powershell -NoProfile -ExecutionPolicy Bypass -File release\build_release.ps1 -Version <x.y.z>`。该脚本要求 `.venv` 已安装项目依赖和 `PyInstaller==6.16.0`，且版本必须与 `app_version.py` 一致。
- Lint/typecheck：仓库当前未配置专用命令；不得把未执行的语法检查描述为已通过。

### Product and architecture invariants

- 目标平台是 Windows，最低 Python 版本为 3.10；运行时依赖以 `requirements.txt` 为准。
- Word 工艺卡与 Excel 模板均在本机处理；除用户主动检查或下载更新外，不得引入上传文档的网络路径。
- 工序号必须保留工艺卡原值；空白工种续行归入上一有名工种；每个连续步骤在同一 Excel 内容单元格内独立换行。
- `待焊` 是不可删除且始终启用的内置排除项；排除后不得对其余工序重新编号。
- 批量导出必须保持原子性：失败时原 Excel 不变；重复导出同一路线时替换旧数据而非追加重复项。
- 原始 Word 文件不归应用所有，移除任务记录或卡片时不得删除源文件；已生成 Excel 也不得被反向修改。
- 用户任务数据、预览缓存、日志与更新暂存位于 `%LOCALAPPDATA%\DocSwift`，不得打入发布包或随程序目录替换。
- Link durable decisions to `docs/adr/`; do not duplicate their full rationale here.

### Safety and external actions

- Do not commit, push, deploy, change external services, or mutate shared data without authorization appropriate to the current request.
- Do not discard unknown local changes.
- 测试默认使用临时目录；未经当前任务明确授权，不得改动真实 `%LOCALAPPDATA%\DocSwift\docswift.db`、公司更新服务器或任何发布目标。
- 更新逻辑必须继续校验发布包名称、大小和 SHA-256，并阻止 ZIP 路径穿越；相关改动必须运行 `tests/test_update_service.py` 及完整回归测试。

## Project-memory workflow

Read `docs/STATUS.md` and the active task packet before changing code. Update only the documents affected by the work. On handoff, record actual verification, untested items, risks, and one exact next action.

<!-- project-memory:collaboration:start -->
## 跨 Agent 协作入口

- 编排 Agent：`codex`（模型偏好：`gpt-5.6-sol`）
- 已启用编码 Agent：`claude-code`, `hermes`（模型偏好：`DeepSeek`）
- 每个任务只允许 `coordination.json` 指定的唯一活动 Agent 写入受控内容。
- 编码 Agent 修改前必须运行项目内 `resume-task` 预检；完成实现和测试后填写 `result.md` 并正式交回 Codex。
- 编码 Agent 不得修改任务范围、权限、STATUS、ARCHITECTURE、ADR，不得记录最终审计、关闭 DONE 或准备提交。
- 统一入口：`python .ai-workflow/runtime/project_memory.py <command> --root . --actor <agent>`。
<!-- project-memory:collaboration:end -->
