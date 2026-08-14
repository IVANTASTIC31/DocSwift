---
updated: "2026-08-13"
source_commit: "fe336d1"
status: current
---

# 系统架构

本文描述 `fe336d1`（`v0.3.1`）对应的当前结构，不记录日常开发流水。

## 系统上下文

DocSwift 是供工艺人员在 Windows 电脑上使用的本地桌面工具。用户输入 Word `.docx` 工艺卡和 Excel 模板，在界面中校对识别结果，再生成工单系统可导入的 `.xlsx` 文件。

主要信任边界如下：

- 工艺卡、模板、任务数据库、预览缓存和日志位于用户本机，核心业务流程不上传文档。
- WPS 或 Microsoft Word 的 COM 自动化只用于本机原版 PDF 预览；不可用时降级为内置 HTML/PDF 渲染。
- 网络仅用于用户主动触发的版本检查和下载。更新源优先为公司内部清单，连接失败时回退 GitHub Release。

## 组件与职责

| 组件 | 职责 | 主要接口或数据 |
| --- | --- | --- |
| `app.py` | PySide6 图形界面、命令行入口、单实例保护、后台识别队列和用户交互 | 调用服务层、SQLite 存储、预览与更新服务 |
| `domain.py` | 任务、工艺卡、工序、排除规则和导出记录的领域模型 | `TaskRecord`、`CardRecord`、`EditableOperation` 等 |
| `core.py` | 解析 Word 工艺卡、工序分组/排除、Excel 写入及原子替换 | `parse_process_card`、`group_operations`、`generate_template_atomic` |
| `services.py` | 编排识别、预览定位和已确认卡片批量导出 | `recognize_docx_complete`、`export_confirmed_cards` |
| `project_store.py` | SQLite 架构、事务和任务状态持久化 | `%LOCALAPPDATA%\DocSwift\docswift.db` |
| `preview_service.py` | WPS/Word COM 原版预览、HTML 降级渲染、PDF 内容页定位和缓存 | `%LOCALAPPDATA%\DocSwift\preview-cache` 下的派生文件 |
| `update_service.py` | 内部清单/GitHub 版本检查、下载校验、安全解压、安装与回滚准备 | `UpdateService`、`PreparedUpdate` |
| `logging_config.py` | UTF-8 滚动日志与未捕获异常记录 | `%LOCALAPPDATA%\DocSwift\logs\docswift.log` |
| `release/*.ps1` | Windows 免安装包、校验文件及内部更新清单的生成 | `dist/release` 构建产物 |

## 主要数据流

1. 用户添加工艺卡后，界面把卡片和队列状态写入 SQLite；单后台通道调用 `services.py`。
2. `core.py` 读取 `.docx` 表格并形成原始工序，按内置及用户排除项分组；`preview_service.py` 同步生成预览并定位来源页。预览失败不会丢弃有效的识别结果。
3. 用户在界面中编辑、确认工序，所有状态和人工修改持续写入 SQLite，重启后可恢复。
4. 批量导出时，服务层只选取“已确认且未导出”的卡片，`core.py` 在临时文件中生成结果并原子替换目标 Excel；成功后才更新导出状态。
5. 用户主动检查更新时，更新服务先读取内部清单；仅当内部服务不可用时查询 GitHub。下载包通过名称、大小和 SHA-256 校验后进入独立暂存目录，安装失败可回滚。

## 持久化与数据所有权

- `docswift.db` 是当前任务、卡片状态、编辑后工序、排除项和导出记录的规范来源；使用 SQLite 外键、事务和 WAL。
- 原始 `.docx`、Excel 模板和目标 `.xlsx` 归用户所有。数据库只保存路径、签名、状态和派生结果，删除应用记录不得删除源文件。
- 预览 PDF、日志、更新下载与安装状态是可再生或运维数据，与程序安装目录分离。
- 识别队列只存在于运行进程中；异常退出后遗留的“待识别/识别中”状态会恢复为可重新提交的状态。

## 接口与兼容约束

- 桌面入口：`run.bat`、`DocSwift.vbs` 和 PyInstaller 免安装版 `DocSwift.exe`。
- 命令行入口：`python app.py --card ... --template ... --output ... [--append]`。
- 输入兼容：Word `.docx`；输出与模板为 Excel `.xlsx`，默认从第 2 行写入并优先按中文表头匹配列。
- 更新资产名称固定为 `DocSwift-v<version>-windows-portable.zip`；版本采用三段式语义版本号。
- 内部更新清单格式版本为 `1`，应用标识必须为 `DocSwift`。

## 部署拓扑

开发态在 Windows + Python 3.10 及以上环境运行。发布态由 PyInstaller `--windowed --onedir` 构建成免安装目录，再压缩为 ZIP；用户数据保存在 `%LOCALAPPDATA%\DocSwift`，因此升级时只替换程序目录。更新包可来自公司内部 HTTP 文件服务，GitHub Release 作为不可达时的备用源。

## 不变量与约束

- 工序编号来自源工艺卡，不按输出行数重排。
- 空白工种续行并入上一有名工种；连续步骤在一个内容单元格中逐行保存。
- `待焊` 永久排除，且排除不会改变其余工序编号。
- Excel 导出是原子操作；任一卡失败时原文件保持不变。
- 同一路线重新导出时替换旧行，不产生重复路线。
- 预览属于辅助能力，失败不得破坏已成功的文本识别。
- 自动安装不得作用于源码目录；ZIP 解压必须阻止路径穿越，下载必须验证字节数和 SHA-256。

## 已知架构债务

- `app.py` 同时承担窗口、队列和大量交互编排，文件体积较大；当新增并行任务类型或界面状态继续增加时，应拆分控制器/视图模型边界。
- 内部更新地址硬编码为固定 IP 且使用 HTTP；当公司具备内部域名和证书时，应迁移到 HTTPS 并把环境差异移出代码常量。
- 发布脚本仍能构建包，但旧的一键上传发布流程已退役；启用新的发布工具前，需要补齐经过验证的发布与恢复运行手册。
