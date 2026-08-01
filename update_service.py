from __future__ import annotations

import hashlib
import json
import os
import shutil
import ssl
import subprocess
import sys
import urllib.error
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from app_version import (
    INTERNAL_UPDATE_MANIFEST_URL,
    RELEASE_ASSET_PREFIX,
    REPOSITORY,
)
from subprocess_visibility import hidden_window_options


GENERIC_REQUEST_HEADERS = {
    "Accept": "application/json, application/octet-stream;q=0.9, */*;q=0.8",
    "User-Agent": "DocSwift-Updater",
}
GITHUB_REQUEST_HEADERS = {
    **GENERIC_REQUEST_HEADERS,
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
}
DOWNLOAD_CHUNK_SIZE = 1024 * 1024


class UpdateError(RuntimeError):
    """An update could not be checked or downloaded safely."""


@dataclass(frozen=True, slots=True)
class ReleaseAsset:
    name: str
    download_url: str
    size: int
    sha256: str


@dataclass(frozen=True, slots=True)
class UpdateInfo:
    version: str
    tag_name: str
    notes: str
    release_url: str
    published_at: str
    asset: ReleaseAsset
    source: str


@dataclass(frozen=True, slots=True)
class PreparedUpdate:
    info: UpdateInfo
    archive_path: Path
    staging_directory: Path


def parse_version(value: str) -> tuple[int, int, int]:
    normalized = value.strip().lower()
    if normalized.startswith("v"):
        normalized = normalized[1:]
    core = normalized.split("-", 1)[0].split("+", 1)[0]
    parts = core.split(".")
    if len(parts) != 3 or any(not part.isdigit() for part in parts):
        raise ValueError(f"不支持的版本号：{value}")
    return tuple(int(part) for part in parts)  # type: ignore[return-value]


def _open_url(request: urllib.request.Request, timeout: float):
    return urllib.request.urlopen(
        request,
        timeout=timeout,
        context=ssl.create_default_context(),
    )


def _request_bytes(
    url: str,
    timeout: float = 15.0,
    headers: dict[str, str] | None = None,
) -> bytes:
    request = urllib.request.Request(
        url,
        headers=headers or GENERIC_REQUEST_HEADERS,
    )
    try:
        with _open_url(request, timeout) as response:
            return response.read()
    except urllib.error.HTTPError as exc:
        raise UpdateError(f"更新服务器返回错误：HTTP {exc.code}") from exc
    except urllib.error.URLError as exc:
        reason = getattr(exc, "reason", exc)
        raise UpdateError(f"无法连接更新服务器：{reason}") from exc
    except TimeoutError as exc:
        raise UpdateError("连接更新服务器超时。") from exc


def _decode_json(data: bytes) -> dict[str, object]:
    try:
        payload = json.loads(data.decode("utf-8-sig"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise UpdateError("更新服务器返回了无法解析的数据。") from exc
    if not isinstance(payload, dict):
        raise UpdateError("更新服务器返回的数据格式无效。")
    return payload


def _validated_sha256(value: object) -> str:
    candidate = str(value or "").strip().lower()
    if len(candidate) != 64 or any(
        character not in "0123456789abcdef" for character in candidate
    ):
        raise UpdateError("最新版缺少有效的 SHA-256 校验信息，已拒绝下载。")
    return candidate


def _asset_digest(
    asset: dict[str, object],
    assets: list[dict[str, object]],
) -> str:
    digest = str(asset.get("digest") or "")
    if digest.lower().startswith("sha256:"):
        return _validated_sha256(digest.split(":", 1)[1])

    checksum_asset = next(
        (
            candidate
            for candidate in assets
            if str(candidate.get("name") or "").upper() == "CHECKSUMS-SHA256.TXT"
        ),
        None,
    )
    if checksum_asset is None:
        raise UpdateError("最新版缺少 SHA-256 校验信息，已拒绝下载。")
    checksum_url = str(checksum_asset.get("browser_download_url") or "")
    checksum_text = _request_bytes(checksum_url).decode(
        "utf-8",
        errors="replace",
    )
    wanted_name = str(asset.get("name") or "")
    for line in checksum_text.splitlines():
        parts = line.strip().split(maxsplit=1)
        if len(parts) != 2 or Path(parts[1].lstrip("*")).name != wanted_name:
            continue
        return _validated_sha256(parts[0])
    raise UpdateError(f"校验文件中找不到 {wanted_name} 的 SHA-256。")


class UpdateService:
    def __init__(
        self,
        repository: str = REPOSITORY,
        manifest_url: str | None = INTERNAL_UPDATE_MANIFEST_URL,
    ) -> None:
        self.repository = repository
        self.manifest_url = manifest_url
        self.latest_release_api = (
            f"https://api.github.com/repos/{repository}/releases/latest"
        )

    def check(self, current_version: str) -> UpdateInfo | None:
        internal_error: UpdateError | None = None
        if self.manifest_url:
            try:
                return self._check_internal(current_version)
            except UpdateError as exc:
                internal_error = exc

        try:
            return self._check_github(current_version)
        except UpdateError as public_error:
            if internal_error is None:
                raise
            raise UpdateError(
                "无法获取更新："
                f"公司服务器（{internal_error}）；"
                f"GitHub 备用源（{public_error}）。"
            ) from public_error

    def _check_internal(self, current_version: str) -> UpdateInfo | None:
        assert self.manifest_url is not None
        payload = _decode_json(_request_bytes(self.manifest_url))
        if int(payload.get("manifest_version") or 0) != 1:
            raise UpdateError("公司服务器的版本清单格式不受支持。")
        if str(payload.get("application") or "") != "DocSwift":
            raise UpdateError("公司服务器返回了其他应用的版本清单。")

        version_value = str(payload.get("version") or "")
        try:
            latest = parse_version(version_value)
            current = parse_version(current_version)
        except ValueError as exc:
            raise UpdateError(str(exc)) from exc
        if latest <= current:
            return None

        version = ".".join(str(part) for part in latest)
        expected_name = (
            f"{RELEASE_ASSET_PREFIX}-v{version}-windows-portable.zip"
        )
        download_url = str(payload.get("download_url") or "")
        manifest_base = self.manifest_url.rsplit("/", 1)[0] + "/"
        if not download_url.startswith(manifest_base):
            raise UpdateError("公司服务器的更新包地址不在受信任目录中。")
        if Path(urlsplit(download_url).path).name != expected_name:
            raise UpdateError(
                "公司服务器的更新包名称与版本不一致："
                f"应为 {expected_name}"
            )
        try:
            size = int(payload.get("size") or 0)
        except (TypeError, ValueError) as exc:
            raise UpdateError("公司服务器的更新包大小无效。") from exc
        if size <= 0:
            raise UpdateError("公司服务器未提供有效的更新包大小。")

        return UpdateInfo(
            version=version,
            tag_name=f"v{version}",
            notes=str(payload.get("notes") or "本次发布未填写更新说明。"),
            release_url=str(payload.get("release_url") or ""),
            published_at=str(payload.get("published_at") or ""),
            asset=ReleaseAsset(
                name=expected_name,
                download_url=download_url,
                size=size,
                sha256=_validated_sha256(payload.get("sha256")),
            ),
            source="公司服务器",
        )

    def _check_github(self, current_version: str) -> UpdateInfo | None:
        try:
            payload = _decode_json(
                _request_bytes(
                    self.latest_release_api,
                    headers=GITHUB_REQUEST_HEADERS,
                )
            )
        except UpdateError as exc:
            if "HTTP 404" in str(exc):
                raise UpdateError("GitHub 尚未发布可供更新的正式版本。") from exc
            raise

        tag_name = str(payload.get("tag_name") or "")
        try:
            latest = parse_version(tag_name)
            current = parse_version(current_version)
        except ValueError as exc:
            raise UpdateError(str(exc)) from exc
        if latest <= current:
            return None

        version = ".".join(str(part) for part in latest)
        expected_name = (
            f"{RELEASE_ASSET_PREFIX}-v{version}-windows-portable.zip"
        )
        assets = [
            item
            for item in payload.get("assets", [])
            if isinstance(item, dict)
        ]
        asset = next(
            (item for item in assets if item.get("name") == expected_name),
            None,
        )
        if asset is None:
            raise UpdateError(
                "发现了新版本，但发布页缺少 Windows 更新包："
                f"{expected_name}"
            )
        download_url = str(asset.get("browser_download_url") or "")
        if not download_url.startswith("https://"):
            raise UpdateError("最新版更新包的下载地址无效。")

        return UpdateInfo(
            version=version,
            tag_name=tag_name,
            notes=str(payload.get("body") or "本次发布未填写更新说明。"),
            release_url=str(payload.get("html_url") or ""),
            published_at=str(payload.get("published_at") or ""),
            asset=ReleaseAsset(
                name=expected_name,
                download_url=download_url,
                size=int(asset.get("size") or 0),
                sha256=_asset_digest(asset, assets),
            ),
            source="GitHub 备用源",
        )

    def download(self, info: UpdateInfo, root: Path) -> Path:
        version_root = root / f"v{info.version}"
        version_root.mkdir(parents=True, exist_ok=True)
        archive_path = version_root / info.asset.name
        partial_path = archive_path.with_suffix(f"{archive_path.suffix}.part")
        partial_path.unlink(missing_ok=True)

        digest = hashlib.sha256()
        downloaded = 0
        request = urllib.request.Request(
            info.asset.download_url,
            headers=GENERIC_REQUEST_HEADERS,
        )
        try:
            with _open_url(request, 45.0) as response, partial_path.open("wb") as output:
                while True:
                    chunk = response.read(DOWNLOAD_CHUNK_SIZE)
                    if not chunk:
                        break
                    output.write(chunk)
                    digest.update(chunk)
                    downloaded += len(chunk)
        except (OSError, urllib.error.URLError, TimeoutError) as exc:
            partial_path.unlink(missing_ok=True)
            raise UpdateError(f"下载更新包失败：{exc}") from exc

        if info.asset.size and downloaded != info.asset.size:
            partial_path.unlink(missing_ok=True)
            raise UpdateError(
                f"更新包下载不完整：应为 {info.asset.size} 字节，"
                f"实际为 {downloaded} 字节。"
            )
        if digest.hexdigest().lower() != info.asset.sha256.lower():
            partial_path.unlink(missing_ok=True)
            raise UpdateError(
                "更新包 SHA-256 校验失败，文件可能不完整或已被篡改。"
            )
        partial_path.replace(archive_path)
        return archive_path

    def download_and_prepare(self, info: UpdateInfo, root: Path) -> PreparedUpdate:
        version_root = root / f"v{info.version}"
        if version_root.exists():
            shutil.rmtree(version_root)
        version_root.mkdir(parents=True)
        archive_path = self.download(info, root)
        staging_directory = version_root / "staging"
        self._extract_safely(archive_path, staging_directory)
        if not (staging_directory / "DocSwift.exe").is_file():
            raise UpdateError("免安装版更新包结构不正确，缺少 DocSwift.exe。")
        return PreparedUpdate(info, archive_path, staging_directory)

    @staticmethod
    def _extract_safely(archive_path: Path, destination: Path) -> None:
        destination.mkdir(parents=True, exist_ok=True)
        destination_root = destination.resolve()
        try:
            with zipfile.ZipFile(archive_path) as archive:
                for member in archive.infolist():
                    resolved = (destination / member.filename).resolve()
                    if (
                        resolved != destination_root
                        and destination_root not in resolved.parents
                    ):
                        raise UpdateError(
                            "更新包包含不安全的文件路径，已停止解压。"
                        )
                archive.extractall(destination)
        except (OSError, zipfile.BadZipFile) as exc:
            raise UpdateError(f"无法解压更新包：{exc}") from exc

    def launch_portable_installer(
        self,
        prepared: PreparedUpdate,
        data_directory: Path,
    ) -> None:
        if not getattr(sys, "frozen", False):
            raise UpdateError("当前是源码运行模式，不能自动覆盖项目文件。")

        executable = Path(sys.executable).resolve()
        target = executable.parent
        staging = prepared.staging_directory.resolve()
        data_directory = data_directory.resolve()
        if not (staging / executable.name).is_file():
            raise UpdateError("更新暂存目录中缺少 DocSwift.exe。")
        if data_directory == target or target in data_directory.parents:
            raise UpdateError(
                "程序安装目录包含任务数据库。为避免误删用户数据，"
                "当前安装位置不支持自动替换。"
            )
        try:
            probe = target.parent / f".docswift-update-write-test-{os.getpid()}"
            probe.write_text("ok", encoding="ascii")
            probe.unlink()
        except OSError as exc:
            raise UpdateError("程序所在目录没有写入权限，无法自动更新。") from exc

        updater_root = data_directory / "updates" / "installer"
        updater_root.mkdir(parents=True, exist_ok=True)
        script_path = updater_root / "apply-update.ps1"
        marker_path = updater_root / "startup-success.marker"
        log_path = updater_root / "update.log"
        marker_path.unlink(missing_ok=True)
        script_path.write_text(_POWERSHELL_UPDATER, encoding="utf-8-sig")
        command = [
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(script_path),
            "-OldPid",
            str(os.getpid()),
            "-Target",
            str(target),
            "-Staging",
            str(staging),
            "-ExecutableName",
            executable.name,
            "-Marker",
            str(marker_path),
            "-LogFile",
            str(log_path),
            "-CleanupDirectory",
            str(prepared.archive_path.parent),
        ]
        try:
            subprocess.Popen(
                command,
                cwd=str(updater_root),
                close_fds=True,
                **hidden_window_options(),
            )
        except OSError as exc:
            raise UpdateError(f"无法启动更新辅助程序：{exc}") from exc


_POWERSHELL_UPDATER = r"""
param(
    [Parameter(Mandatory=$true)][int]$OldPid,
    [Parameter(Mandatory=$true)][string]$Target,
    [Parameter(Mandatory=$true)][string]$Staging,
    [Parameter(Mandatory=$true)][string]$ExecutableName,
    [Parameter(Mandatory=$true)][string]$Marker,
    [Parameter(Mandatory=$true)][string]$LogFile,
    [Parameter(Mandatory=$true)][string]$CleanupDirectory
)
$ErrorActionPreference = "Stop"

function Write-UpdateLog([string]$Message) {
    $line = "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') | $Message"
    Add-Content -LiteralPath $LogFile -Value $line -Encoding UTF8
}

$backup = "$Target.previous"
$newProcess = $null
$backupCreated = $false
try {
    Write-UpdateLog "Waiting for application pid=$OldPid"
    try { Wait-Process -Id $OldPid -Timeout 120 -ErrorAction SilentlyContinue } catch {}
    if (Get-Process -Id $OldPid -ErrorAction SilentlyContinue) {
        throw "旧程序在120秒内没有退出"
    }
    if (-not (Test-Path -LiteralPath $Staging -PathType Container)) {
        throw "更新暂存目录不存在：$Staging"
    }
    if (Test-Path -LiteralPath $backup) {
        Remove-Item -LiteralPath $backup -Recurse -Force
    }
    Move-Item -LiteralPath $Target -Destination $backup
    $backupCreated = $true
    Move-Item -LiteralPath $Staging -Destination $Target
    Remove-Item -LiteralPath $Marker -Force -ErrorAction SilentlyContinue
    $newExe = Join-Path $Target $ExecutableName
    $newProcess = Start-Process -FilePath $newExe -ArgumentList @("--update-success-marker", $Marker) -WorkingDirectory $Target -PassThru
    Write-UpdateLog "Started new version pid=$($newProcess.Id)"

    $ready = $false
    for ($index = 0; $index -lt 120; $index++) {
        if (Test-Path -LiteralPath $Marker -PathType Leaf) {
            $ready = $true
            break
        }
        if ($newProcess.HasExited) {
            break
        }
        Start-Sleep -Milliseconds 500
        $newProcess.Refresh()
    }
    if (-not $ready) {
        throw "新版程序没有在60秒内完成启动确认"
    }
    Remove-Item -LiteralPath $backup -Recurse -Force
    Remove-Item -LiteralPath $Marker -Force -ErrorAction SilentlyContinue
    Write-UpdateLog "Update completed successfully"
    if (Test-Path -LiteralPath $CleanupDirectory) {
        Remove-Item -LiteralPath $CleanupDirectory -Recurse -Force -ErrorAction SilentlyContinue
    }
    exit 0
}
catch {
    Write-UpdateLog "Update failed: $($_.Exception.Message)"
    try {
        if ($newProcess -and -not $newProcess.HasExited) {
            Stop-Process -Id $newProcess.Id -Force -ErrorAction SilentlyContinue
        }
        if ($backupCreated -and (Test-Path -LiteralPath $backup)) {
            if (Test-Path -LiteralPath $Target) {
                Remove-Item -LiteralPath $Target -Recurse -Force
            }
            Move-Item -LiteralPath $backup -Destination $Target
            $oldExe = Join-Path $Target $ExecutableName
            Start-Process -FilePath $oldExe -WorkingDirectory $Target
            Write-UpdateLog "Previous version restored and restarted"
        } else {
            Write-UpdateLog "Old installation was not moved; no rollback needed"
        }
    }
    catch {
        Write-UpdateLog "Rollback failed: $($_.Exception.Message)"
    }
    exit 1
}
""".strip()
