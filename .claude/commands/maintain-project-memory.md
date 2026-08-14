---
description: 使用项目内运行时执行项目记忆预检、任务接手与交接
---

<!-- project-memory:adapter:start -->
# Maintain Project Memory

当前 Agent 标识为 `claude-code`。先读取 `AGENTS.md`、`docs/STATUS.md` 和活动任务包，再运行：

```text
python .ai-workflow/runtime/project_memory.py preflight --root . --intent resume-task --actor claude-code
```

根据门禁结果继续；若有待接受交接，先运行 `handoff --accept`。编码 Agent 只更新代码、测试和任务 `result.md`，完成后正式交回 `codex`。
<!-- project-memory:adapter:end -->
