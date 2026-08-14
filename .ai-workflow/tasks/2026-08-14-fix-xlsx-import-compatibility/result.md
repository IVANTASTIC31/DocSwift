---
task_id: "2026-08-14-fix-xlsx-import-compatibility"
title: "修复 Excel 导出文件的小黑湖导入兼容性"
status: READY_FOR_REVIEW
updated: "2026-08-14"
base_commit: "fe336d1"
orchestrator_agent: "codex"
execution_agent: "claude-code"
last_verified: "2026-08-14T12:19:20+08:00"
audit_status: "PASSED"
audited_at: "2026-08-14T12:19:20+08:00"
audited_by: "Codex"
audited_commit: "3a8bacd6ab37a62b8899f1134ca5364785661d20"
audited_worktree_fingerprint: "9b34e1b9acfe21be"
---

# Task result: 修复 Excel 导出文件的小黑湖导入兼容性

## Outcome

已完成 Excel 数据与 OOXML 封装兼容性修复：

1. H、I 可选字段不再写入空字符串，改为真正空值；保存后的工作表 XML 中，对应单元格不得使用 `s`、`str`、`inlineStr` 字符串类型且不得包含值节点。
2. 使用模板重建数据区时，在 `delete_rows` 后同步清理数据起始行及之后的遗留 `row_dimensions`，生成文件的物理行止于最后一条有效数据。
3. 重复导出替换尾部路线时，若新路线行数少于旧路线，删除旧路线后同步清理当前有效行之外的尾部 `row_dimensions`，避免追加后重新出现空物理行。
4. Openpyxl 仅在临时工作簿中执行现有数据、样式和行高计算；最终文件以原模板 ZIP 包为容器，只替换活动工作表的数据区、维度/筛选必要信息和 `sharedStrings.xml`，不再让 Openpyxl 重写完整最终包。
5. 最终文本单元格统一使用共享字符串索引 `t="s"`，不含 `inlineStr`；模板已具备合格数据样式时复用原样式索引，并移除空白 H/I 物理单元格。
6. 首次生成和重复原子导出均走相同的包保真层；未增加路线去重或其他业务规则。

使用用户提供的实际模板做只读诊断生成后，除 `xl/worksheets/sheet1.xml` 与 `xl/sharedStrings.xml` 外，模板所有既有 ZIP 部件内容哈希均保持不变；Openpyxl 可正常重新打开输出。

## Changed files

- `core.py`：保留既有 H/I 真空值、行尺寸清理和 D1 空白修复；新增模板包读取、活动工作表定位、共享字符串转换、模板数据样式复用、必要关系/Content Types 回退及原子重打包逻辑。`generate_template(...)` 与 `generate_template_atomic(...)` 的公开调用方式不变。
- `tests/test_core.py`：保留既有 XML/行尺寸回归；新增带批注、关系、主题和共享字符串的生产型模板 fixture，以及首次/重复原子导出的包部件哈希、`t="s"`、H/I 不存在、Openpyxl 可读和批注保留测试。
- `.ai-workflow/tasks/2026-08-14-fix-xlsx-import-compatibility/result.md`：记录本次实现、验证、限制与交接信息。

## Decisions

无新增 ADR；实现仍属于现有本地 Excel 导出边界内的序列化兼容修正，不改变公开接口、持久化结构或业务规则。

## Verification performed

| Command or check | Result | Limitations |
| --- | --- | --- |
| `$env:PYTHONPATH=''; .venv\Scripts\python.exe -m unittest tests.test_core -v` | PASS（11 项） | 使用临时工作簿，未连接小黑湖 |
| `$env:PYTHONPATH=''; .venv\Scripts\python.exe -m unittest tests.test_services -v` | PASS（2 项） | 使用临时数据库和工作簿 |
| `$env:PYTHONPATH=''; .venv\Scripts\python.exe -m unittest discover -s tests -v` | PASS（50 项） | GUI 测试为 offscreen；未做真实小黑湖导入 |
| `git diff --check` | PASS | 输出仅有既有 LF/CRLF 转换警告，无空白错误 |
| 用户实际模板只读诊断生成并比较 ZIP 部件 SHA-256 | PASS | 仅 `sheet1.xml` 与 `sharedStrings.xml` 变化；诊断输出已清理，未上传小黑湖 |
| `powershell -NoProfile -ExecutionPolicy Bypass -File release\build_release.ps1 -Version 0.3.2` | PASS | 本机 Windows/PyInstaller 6.16.0 构建 |
| `powershell -NoProfile -ExecutionPolicy Bypass -File release\prepare_internal_manifest.ps1 -Version 0.3.2` | PASS | 仅生成本地内部更新清单，未上传服务器 |
| `$env:PYTHONPATH=''; .venv\Scripts\python.exe -m unittest tests.test_update_service -v`（v0.3.3） | PASS（19 项） | 使用模拟网络和临时目录 |
| `$env:PYTHONPATH=''; .venv\Scripts\python.exe -m unittest discover -s tests -v`（v0.3.3） | PASS（50 项） | GUI 测试为 offscreen；未做真实小黑湖导入 |
| `powershell -NoProfile -ExecutionPolicy Bypass -File release\build_release.ps1 -Version 0.3.3` | PASS | 本机 Windows/PyInstaller 6.16.0 构建 |
| `powershell -NoProfile -ExecutionPolicy Bypass -File release\prepare_internal_manifest.ps1 -Version 0.3.3` | PASS | 清单为 UTF-8 无 BOM；未上传服务器 |

以上检查均由 Codex 在接受正式交接后独立复跑；实际模板验证同时确认 ZIP 部件集合不变、存在 `xl/sharedStrings.xml`、工作表不含 `inlineStr`，且 H2/I2 为真空值。

## Failures and untested items

- 本轮包保真实现和新增测试未出现最终失败；开发中曾发现 Openpyxl 生成的数据行样式引用超出模板 `styles.xml`，随后改为在模板样式满足细边框、居中和换行条件时复用原样式/行样式，实际模板诊断及包级回归均通过。
- 未将本轮新输出实际上传小黑湖；任务没有外部系统变更权限。
- 已重建 `DocSwift-v0.3.2-windows-portable.zip`；大小为 `56279351` 字节，SHA-256 为 `5ebbbfc012e294e8a80ef29b49a264081a97df5bf982667e5542e51f617b201d`，与 `CHECKSUMS-SHA256.TXT` 和 `latest.json` 一致。
- 为使已安装 v0.3.2 的客户端能够识别更新，已将本次修复提升为 v0.3.3。新包 `DocSwift-v0.3.3-windows-portable.zip` 大小为 `56277659` 字节，SHA-256 为 `667d1ccb8cca2773fd823694c141790e12dbe5911e057cde3ffe6e3cb86a190a`；ZIP、`CHECKSUMS-SHA256.TXT` 与 `latest.json` 一致，压缩包包含 `DocSwift.exe`。

## Remaining risks

- 自动化已覆盖手工成功文件所揭示的包级差异，但小黑湖是最终兼容性判据，仍需用户用本轮新生成文件实际导入确认。
- 对缺少共享字符串关系或缺少合格数据样式的非标准模板，代码会最小补充关系/Content Types 或采用 Openpyxl 临时样式；用户实际模板已具备共享字符串和合格样式，因此走字节保真路径。

## Documentation updates

- Worker 阶段仅更新本任务 `result.md`；Codex 接受交接后更新 `docs/STATUS.md`，在用户授权发布时补充 `CHANGELOG.md` 和发布说明，并为同版本客户端可识别更新新增 `release/notes-v0.3.3.md`。

## Exact next action

1. Codex 创建 v0.3.3 发布提交与 annotated tag 并推送 GitHub；用户随后将 v0.3.3 ZIP、校验文件和 `latest.json` 人工上传公司更新服务器，再由同事从 v0.3.2 点击“检查更新”验收。

## Worktree and external state

- Worktree：本任务增量仅涉及 `core.py`、`tests/test_core.py` 和本 `result.md`；任务开始前已有的其他已修改及未跟踪文件均保留，未删除或覆盖；本轮诊断临时输出已删除。
- Commit/push/deployment/shared-data changes：发布提交 `7d179cb` 与 annotated tag `v0.3.2` 已推送 GitHub `origin`；v0.3.3 本地发布包及清单已生成，等待提交和 GitHub 推送。未上传服务器，未改动真实 `%LOCALAPPDATA%\DocSwift`、桌面 Excel 源文件或小黑湖。
