---
name: project-memory-runtime
description: 使用项目内固定运行时执行任务预检、接手、实现结果记录和正式交接。开始或恢复开发任务、准备交接时使用。
---

<!-- project-memory:adapter:start -->
# 项目记忆运行时

先读取项目根目录 `AGENTS.md`、`docs/STATUS.md` 和活动任务的 `coordination.json`。运行：

```text
python .ai-workflow/runtime/project_memory.py preflight --root . --intent resume-task --actor <当前-agent>
```

门禁允许后才能修改。编码 Agent 只实现、测试并更新活动任务 `result.md`；交回时执行 `handoff`。不要复制规则或历史，本入口以项目运行时和普通 Markdown 为权威。
<!-- project-memory:adapter:end -->
