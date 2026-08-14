---
task_id: "2026-08-14-fix-xlsx-import-compatibility"
title: "修复 Excel 导出文件的小黑湖导入兼容性"
status: PLANNED
created: "2026-08-14"
updated: "2026-08-14"
base_commit: "fe336d1"
orchestrator_agent: "codex"
execution_agent: "claude-code"
role_policy: "orchestrator-worker"
permission_file_edits: "allow"
permission_dependency_install: "deny"
permission_git_commit: "allow"
permission_git_push: "allow"
permission_git_push_target: "origin/main,origin/v0.3.2"
permission_local_database: "deny"
permission_deploy: "deny"
permission_deploy_target: "none"
permission_external_mutation: "deny"
permission_external_scope: "none"
---

# Task brief: 修复 Excel 导出文件的小黑湖导入兼容性

## Confirmed facts

- 用户确认“导入工艺路线及明细模板1 .xlsx”可导入小黑湖，而项目生成的“工艺路线导入123456.xlsx”无法导入，并授权按对比结论修改代码。
- 两个工作簿都能正常解析，工作表名、九列表头、主要样式和数据列类型一致，不属于损坏文件。
- 模板数据行的 H、I 空白单元格未物理创建；项目生成文件的 `H2:I100` 被写成 198 个实际空字符串单元格。
- 项目生成文件实际数据止于第 100 行，但工作表维度为 `A1:I129`，并残留第 105、111、117、123、129 行的空物理行记录；模板没有空物理行。
- `core.py` 当前通过 `worksheet.delete_rows(...)` 重建模板数据区，但未清理遗留 `row_dimensions`；同时将 `locked` 和 `work_minutes` 写为 `""`。
- 当前工作树已有上一任务未提交改动，`core.py` 和 `tests/test_core.py` 已包含“工序号表头保持空白”的改动，必须保留。
- 修复后实际生成文件仍导入失败；文件中虽存在一组完全相同但不连续的重复路线，但用户确认将生成文件的同一批内容手工复制到原模板后可以成功导入，因此该内容重复不是本次失败的决定因素。
- 成功模板的文本单元格使用 `xl/sharedStrings.xml` 和 `t="s"`，项目新生成文件没有共享字符串表，590 个文本单元格全部使用 `inlineStr`；Openpyxl 同时重写了工作簿属性、样式索引和批注关系路径，当前应优先定位 OOXML 封装兼容性。
- 用户提供了手工复制后可成功导入的工作簿。与原模板做 ZIP 部件哈希对比后确认：`[Content_Types].xml`、根关系、应用属性、自定义属性、工作簿关系、批注内容、`styles.xml`、主题和工作表关系均与原模板字节级一致；只有 `core.xml`、`sharedStrings.xml`、`workbook.xml`、`sheet1.xml` 和批注 VML 位置发生变化。
- 项目生成文件除主题外几乎重写了全部包部件，并将文本统一改为 `inlineStr`。因此最小兼容性方向是以模板 OOXML 包为底，仅更新数据与必要索引部件，不再让 Openpyxl 重写整个最终文件。

## Goal

让 DocSwift 新生成的 Excel 在保持现有业务数据和格式规则的前提下，不再写入 H、I 列的显式空字符串单元格，并且不保留数据区之外的空物理行，从而提高小黑湖导入兼容性。

## Non-goals

- 不改变工艺路线编号、名称、工种、工序号、工序内容、类型和报工数配比的业务规则。
- 不恢复 D1“工序号”表头；继续保留当前已验收的空白表头行为。
- 不修改真实桌面源文件、真实 `%LOCALAPPDATA%\DocSwift` 数据或外部系统。
- 不部署或上传公司更新服务器，不安装依赖；本次仅允许提交、推送 GitHub `origin/main` 与 `origin/v0.3.2`，并在本地重建 v0.3.2 发布物。

## Acceptance criteria

1. 新生成文件中，H、I 可选字段为空时对应单元格不存在或其值为真正空值，不得序列化为空字符串。
2. 用带有多余模板数据行和自定义行高的模板重建输出后，输出工作表最大有效行与最后一条数据行一致，不残留数据区外的空物理行记录。
3. 现有原子导出、重复路线替换、样式复制、边框、居中换行和 D1 空白表头行为保持不变。
4. 新增或增强回归测试，直接验证空单元格与行尺寸残留问题。
5. `tests.test_core`、相关服务测试和完整回归全部通过。
6. 生成文件应保持黑湖可接受的模板 OOXML 封装；具体标准以“手工粘贴同批内容后可成功导入”的工作簿包级对比为准，不在缺少证据时增加路线去重等无关业务规则。
7. 最终输出的非数据包部件应保持模板兼容：样式、关系、Content Types、应用/自定义属性和批注内容不得因导出被无关重写；文本单元格使用共享字符串表而非 `inlineStr`。

## Existing worktree state

- `HEAD` 为 `fe336d1`；工作树已有 `.gitignore`、`README.md`、`app.py`、`app_version.py`、`core.py`、发布脚本和测试等未提交改动。
- `core.py` 的既有差异是将 D1“工序号”改为空值；`tests/test_core.py` 已相应修改并增加原子导出测试。此次实现必须在这些差异上增量修改。
- 未跟踪的 `.reasonix/`、`.serena/` 与本任务无关，禁止修改、删除或纳入任何操作。
- `.tmp/` 包含本次只读对比产生的临时分析文件，不属于产品改动。

## Expected files and interfaces

- 预计修改 `core.py`、`tests/test_core.py`，必要时补充 `tests/test_services.py`。
- 编码 Agent 只更新本任务 `result.md`；不得修改 `brief.md`、`coordination.json`、`docs/STATUS.md`、架构文档、ADR 或运行时。
- `generate_template(...)` 与 `generate_template_atomic(...)` 的公开调用方式保持不变。

## Validation commands

```powershell
$env:PYTHONPATH=''
.venv\Scripts\python.exe -m unittest tests.test_core -v
.venv\Scripts\python.exe -m unittest tests.test_services -v
.venv\Scripts\python.exe -m unittest discover -s tests -v
```

## Safety and authorization boundaries

- Preserve unrelated changes.
- The structured permission fields in this task's frontmatter are authoritative for this task only.
- Do not carry commit, push, deploy, or external-mutation authorization into another task.
- Do not read or record secrets beyond ordinary task-relevant configured access.
- 用户于 2026-08-14 明确要求将这一版推送 GitHub 后打包；授权范围限于 GitHub `origin/main`、annotated tag `v0.3.2` 与本地发布构建，不包含公司 Gitea、GitHub Release 或服务器上传。

## Documentation impact expected

- `docs/STATUS.md`：Codex 记录活动任务和最终验证结果。
- `CHANGELOG.md`：若修复完成，由 Codex在交回后增加一条中文兼容性修复记录。
- `docs/ARCHITECTURE.md`、ADR、runbook：预计无影响；不改变系统边界或持久化架构。
