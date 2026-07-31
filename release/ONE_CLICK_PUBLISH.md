# DocSwift 一键发布工具

`publish.ps1` 把原来的手工发布步骤收口为一条命令：

1. 更新 `app_version.py` 和 README 中的版本号。
2. 运行语法检查和完整回归测试。
3. 构建 Windows 免安装 ZIP。
4. 生成 SHA-256、`CHECKSUMS-SHA256.TXT` 和 `latest.json`。
5. 提交源码、创建版本标签，只推送到公司 Gitea 的 `company/main`。
6. 创建或复用 Gitea 发布版，上传 ZIP 和校验文件。
7. 先把 ZIP 与清单上传到 Ubuntu 临时目录。
8. 校验服务器上的 ZIP 后，最后替换公开的 `latest.json`。
9. 从员工访问地址重新检查版本、哈希和文件大小。

脚本不会推送 GitHub 或 Gitee。

## 一、首次使用前的准备

### 1. 确认 Python 构建环境

项目目录需要存在 `.venv`，并安装 `requirements.txt` 和 PyInstaller：

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pip install pyinstaller==6.16.0
```

### 2. 配置到 Ubuntu 的 SSH 密钥

如果还没有密钥：

```powershell
ssh-keygen -t ed25519
```

将公钥加入服务器：

```powershell
Get-Content "$env:USERPROFILE\.ssh\id_ed25519.pub" |
  ssh rooter@192.168.100.3 "umask 077; mkdir -p ~/.ssh; cat >> ~/.ssh/authorized_keys"
```

验证无密码访问：

```powershell
ssh -o BatchMode=yes rooter@192.168.100.3 "echo SSH_OK"
```

必须直接返回 `SSH_OK`。脚本故意使用 `BatchMode=yes`，密钥未配置好时会立即
失败，不会发布到一半再停下来等待密码。

### 3. 允许 rooter 管理 DocSwift 更新目录

仅首次在 Ubuntu 执行：

```bash
sudo chown -R rooter:rooter /srv/docswift-updates
sudo chmod -R u=rwX,go=rX /srv/docswift-updates
```

这里只授予 DocSwift 更新目录权限，不需要给发布脚本开放通用免密 `sudo`。

### 4. 创建 Gitea API 令牌

在公司 Gitea 的个人设置中创建能够写入仓库和发布版的 API 令牌。不要把令牌
写进项目文件或聊天记录。

在 Windows“编辑用户环境变量”中新增：

```text
变量名：DOCSWIFT_GITEA_TOKEN
变量值：Gitea 生成的令牌
```

重新打开 PowerShell 后确认变量存在，但不要打印完整内容：

```powershell
if ($env:DOCSWIFT_GITEA_TOKEN) { "TOKEN_OK" } else { "TOKEN_MISSING" }
```

### 5. 检查发布配置

非敏感配置位于 `release\publish.config.psd1`，包括：

- 公司 Git 远端：`company`
- Gitea 地址和仓库名
- Ubuntu 地址、用户及更新目录
- 员工访问的更新地址

服务器地址或账号变化时只需修改此文件。

## 二、每次发布

### 1. 编写发布说明

复制上一版说明并修改，例如：

```text
release\notes-v0.3.1.md
```

### 2. 仅检查发布计划

```powershell
powershell -ExecutionPolicy Bypass -File .\release\publish.ps1 `
  -Version 0.3.1 `
  -NotesFile .\release\notes-v0.3.1.md `
  -PlanOnly
```

`PlanOnly` 只检查工具、仓库、配置和待提交文件，不修改源码，不提交，不上传。

### 3. 正式发布

```powershell
powershell -ExecutionPolicy Bypass -File .\release\publish.ps1 `
  -Version 0.3.1 `
  -NotesFile .\release\notes-v0.3.1.md
```

脚本会显示版本、当前分支、目标仓库、服务器和 Git 变更。只有准确输入：

```text
RELEASE v0.3.1
```

才会开始执行。

无人值守时可加 `-Yes`，日常人工发布不建议使用：

```powershell
.\release\publish.ps1 -Version 0.3.1 `
  -NotesFile .\release\notes-v0.3.1.md -Yes
```

## 三、失败后的处理

发布脚本采用可重试设计：

- 已存在且指向当前提交的 Git 标签会复用。
- 已创建的 Gitea 发布版会复用。
- Gitea 中大小一致的发布文件会跳过。
- 大小不同的同名发布文件会替换。
- Ubuntu 的公开 `latest.json` 在 ZIP 上传并通过 SHA-256 校验后才更新。

修复网络、权限或配置问题后，重新执行相同命令即可。不要手工删除正确的标签。

## 四、常用可选参数

| 参数 | 用途 |
| --- | --- |
| `-PlanOnly` | 只检查，不产生修改 |
| `-Yes` | 跳过人工确认 |
| `-SkipGitPublish` | 临时跳过提交、标签和 Git 推送 |
| `-SkipGiteaRelease` | 临时跳过 Gitea 发布版 |
| `-SkipServerUpload` | 临时跳过 Ubuntu 更新服务 |
| `-CommitMessage "..."` | 自定义发布提交信息 |
| `-Notes "..."` | 直接传入简短发布说明 |

正常正式发布不要使用三个 `Skip` 参数。

## 五、安全约束

- 版本号必须使用 `1.2.3` 格式。
- 发布前必须通过全部测试和本地清单校验。
- 标签已指向其他提交时立即停止，不会移动旧标签。
- 只推送 `company` 远端。
- API 令牌只从环境变量读取。
- SSH 只允许非交互式密钥登录。
- 员工更新清单最后发布，避免暴露不完整版本。
