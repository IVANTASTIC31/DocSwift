from __future__ import annotations

import hashlib
import json
import ssl
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from app_version import (
    INTERNAL_UPDATE_MANIFEST_URL,
    RELEASE_ASSET_PREFIX,
    REPOSITORY,
)


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
        payload = json.loads(data.decode("utf-8"))
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
