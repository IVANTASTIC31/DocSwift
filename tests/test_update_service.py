import hashlib
import io
import json
import shutil
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
import zipfile

from update_service import (
    PreparedUpdate,
    ReleaseAsset,
    UpdateError,
    UpdateInfo,
    UpdateService,
    _decode_json,
    parse_version,
)


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()


def zip_bytes(files: dict[str, bytes]) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        for name, content in files.items():
            archive.writestr(name, content)
    return output.getvalue()


def update_info(archive: bytes) -> UpdateInfo:
    return UpdateInfo(
        version="0.3.0",
        tag_name="v0.3.0",
        notes="测试更新",
        release_url="",
        published_at="",
        asset=ReleaseAsset(
            name="DocSwift-v0.3.0-windows-portable.zip",
            download_url="https://example.invalid/update.zip",
            size=len(archive),
            sha256=hashlib.sha256(archive).hexdigest(),
        ),
        source="测试源",
    )


class DecodeJsonTest(unittest.TestCase):
    def test_accepts_plain_utf8(self) -> None:
        payload = _decode_json(b'{"key": "value"}')
        self.assertEqual({"key": "value"}, payload)

    def test_accepts_utf8_with_bom(self) -> None:
        bom = b"\xef\xbb\xbf"
        payload = _decode_json(bom + b'{"key": "value"}')
        self.assertEqual({"key": "value"}, payload)

    def test_accepts_bom_only_manifest(self) -> None:
        bom = b"\xef\xbb\xbf"
        body = json.dumps(
            {
                "manifest_version": 1,
                "application": "DocSwift",
                "version": "0.3.0",
                "published_at": "2026-07-31T08:32:00+08:00",
                "download_url": (
                    "http://192.168.100.3/updates/docswift/releases/v0.3.0/"
                    "DocSwift-v0.3.0-windows-portable.zip"
                ),
                "sha256": "b" * 64,
                "size": 456,
                "notes": "BOM test",
            }
        ).encode("utf-8")
        payload = _decode_json(bom + body)
        self.assertEqual("DocSwift", payload["application"])
        self.assertEqual("0.3.0", payload["version"])

    def test_rejects_invalid_json(self) -> None:
        with self.assertRaises(UpdateError):
            _decode_json(b"not json")

    def test_rejects_non_object_json(self) -> None:
        with self.assertRaises(UpdateError):
            _decode_json(b"[1, 2, 3]")
        with self.assertRaises(UpdateError):
            _decode_json(b'"string"')
        with self.assertRaises(UpdateError):
            _decode_json(b"42")

    def test_rejects_malformed_utf8(self) -> None:
        with self.assertRaises(UpdateError):
            _decode_json(b"\xff\xfe{\"key\": \"value\"}")


_POWERSHELL_AVAILABLE = bool(shutil.which("powershell.exe"))


@unittest.skipUnless(_POWERSHELL_AVAILABLE, "powershell.exe not available")
class ManifestGeneratorTest(unittest.TestCase):
    def test_generated_manifest_has_no_bom_and_is_valid_json(self) -> None:
        project_root = Path(__file__).resolve().parent.parent
        source_script = project_root / "release" / "prepare_internal_manifest.ps1"
        if not source_script.is_file():
            self.skipTest("prepare_internal_manifest.ps1 not found")

        with TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)

            # Recreate the expected directory layout inside tmp so the
            # script never touches the real project tree.
            release_dir = tmp_path / "release"
            release_dir.mkdir()
            script = release_dir / "prepare_internal_manifest.ps1"
            shutil.copy2(source_script, script)

            dist_release = tmp_path / "dist" / "release"
            dist_release.mkdir(parents=True)
            dummy_zip = dist_release / "DocSwift-v0.3.0-windows-portable.zip"
            dummy_zip.write_bytes(b"fake release package")

            result = subprocess.run(
                [
                    "powershell.exe",
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    str(script),
                    "-Version",
                    "0.3.0",
                    "-BaseUrl",
                    "http://192.168.100.3/updates/docswift",
                    "-Notes",
                    "BOM regression test",
                ],
                cwd=str(tmp_path),
                capture_output=True,
                text=True,
                timeout=30,
            )
            self.assertEqual(
                0,
                result.returncode,
                f"PowerShell exited {result.returncode}: {result.stderr}",
            )

            manifest = dist_release / "latest.json"
            if not manifest.is_file():
                candidates = list(tmp_path.rglob("latest.json"))
                if not candidates:
                    self.fail(
                        "PowerShell script did not produce latest.json "
                        f"under {tmp_path}"
                    )
                manifest = candidates[0]

            raw = manifest.read_bytes()

            # Assert no UTF-8 BOM
            self.assertNotEqual(
                b"\xef\xbb\xbf",
                raw[:3],
                "latest.json must not start with UTF-8 BOM",
            )

            # Assert valid JSON
            try:
                doc = json.loads(raw.decode("utf-8"))
            except (json.JSONDecodeError, UnicodeDecodeError) as exc:
                self.fail(f"latest.json is not valid JSON: {exc}")

            self.assertIsInstance(doc, dict)
            self.assertEqual(1, doc.get("manifest_version"))
            self.assertEqual("DocSwift", doc.get("application"))


class UpdateServiceTest(unittest.TestCase):
    def test_parse_version(self) -> None:
        self.assertEqual((1, 2, 3), parse_version("v1.2.3"))
        self.assertEqual((1, 2, 3), parse_version("1.2.3-beta"))
        with self.assertRaises(ValueError):
            parse_version("1.2")

    def test_check_finds_expected_release_asset(self) -> None:
        payload = {
            "tag_name": "v0.3.0",
            "body": "更新说明",
            "html_url": "https://github.com/example/releases/tag/v0.3.0",
            "published_at": "2026-07-27T00:00:00Z",
            "assets": [
                {
                    "name": "DocSwift-v0.3.0-windows-portable.zip",
                    "browser_download_url": "https://example.invalid/update.zip",
                    "size": 123,
                    "digest": f"sha256:{'a' * 64}",
                }
            ],
        }
        with patch(
            "update_service._request_bytes",
            return_value=json.dumps(payload).encode("utf-8"),
        ):
            info = UpdateService(
                "example/repo",
                manifest_url=None,
            ).check("0.2.0")
        self.assertIsNotNone(info)
        assert info is not None
        self.assertEqual("0.3.0", info.version)
        self.assertEqual("a" * 64, info.asset.sha256)

    def test_check_returns_none_for_current_release(self) -> None:
        payload = {"tag_name": "v0.2.0", "assets": []}
        with patch(
            "update_service._request_bytes",
            return_value=json.dumps(payload).encode("utf-8"),
        ):
            self.assertIsNone(
                UpdateService(
                    "example/repo",
                    manifest_url=None,
                ).check("0.2.0")
            )

    def test_download_verifies_sha256(self) -> None:
        archive = b"valid update archive"
        payload = {
            "tag_name": "v0.3.0",
            "body": "",
            "html_url": "https://github.com/example/releases/tag/v0.3.0",
            "published_at": "",
            "assets": [
                {
                    "name": "DocSwift-v0.3.0-windows-portable.zip",
                    "browser_download_url": "https://example.invalid/update.zip",
                    "size": len(archive),
                    "digest": f"sha256:{hashlib.sha256(archive).hexdigest()}",
                }
            ],
        }
        with patch(
            "update_service._request_bytes",
            return_value=json.dumps(payload).encode("utf-8"),
        ):
            info = UpdateService(
                "example/repo",
                manifest_url=None,
            ).check("0.2.0")
        assert info is not None
        with TemporaryDirectory() as temporary_directory, patch(
            "update_service._open_url",
            return_value=FakeResponse(archive),
        ):
            result = UpdateService().download(
                info,
                Path(temporary_directory),
            )
            self.assertEqual(archive, result.read_bytes())
            self.assertFalse(result.with_suffix(".zip.part").exists())

    def test_download_prepares_portable_package(self) -> None:
        archive = zip_bytes(
            {
                "DocSwift.exe": b"binary",
                "_internal/library.bin": b"dependency",
            }
        )
        with TemporaryDirectory() as temporary_directory, patch(
            "update_service._open_url",
            return_value=FakeResponse(archive),
        ):
            prepared = UpdateService().download_and_prepare(
                update_info(archive),
                Path(temporary_directory),
            )

            self.assertTrue(prepared.archive_path.is_file())
            self.assertEqual(
                b"binary",
                (prepared.staging_directory / "DocSwift.exe").read_bytes(),
            )
            self.assertTrue(
                (
                    prepared.staging_directory
                    / "_internal"
                    / "library.bin"
                ).is_file()
            )

    def test_safe_extract_rejects_parent_directory_member(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            archive_path = root / "unsafe.zip"
            archive_path.write_bytes(zip_bytes({"../outside.txt": b"no"}))
            with self.assertRaisesRegex(UpdateError, "不安全"):
                UpdateService._extract_safely(
                    archive_path,
                    root / "staging",
                )

    def test_portable_installer_starts_hidden_helper(self) -> None:
        archive = zip_bytes({"DocSwift.exe": b"new"})
        info = update_info(archive)
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            target = root / "DocSwift"
            target.mkdir()
            executable = target / "DocSwift.exe"
            executable.write_bytes(b"old")
            staging = root / "staging"
            staging.mkdir()
            (staging / executable.name).write_bytes(b"new")
            prepared = PreparedUpdate(
                info,
                root / info.asset.name,
                staging,
            )
            calls: list[tuple[list[str], dict[str, object]]] = []

            with (
                patch.object(
                    __import__("update_service").sys,
                    "frozen",
                    True,
                    create=True,
                ),
                patch.object(
                    __import__("update_service").sys,
                    "executable",
                    str(executable),
                ),
                patch(
                    "update_service.subprocess.Popen",
                    side_effect=lambda command, **kwargs: calls.append(
                        (command, kwargs)
                    ),
                ),
            ):
                UpdateService().launch_portable_installer(
                    prepared,
                    root / "data",
                )

            self.assertTrue(calls)
            command, options = calls[0]
            self.assertEqual("powershell.exe", command[0])
            self.assertIn("-OldPid", command)
            self.assertIn("-Staging", command)
            self.assertEqual(
                str(root / "data" / "updates" / "installer"),
                options["cwd"],
            )
            self.assertTrue(
                (
                    root
                    / "data"
                    / "updates"
                    / "installer"
                    / "apply-update.ps1"
                ).is_file()
            )

    def test_portable_installer_protects_user_data(self) -> None:
        archive = zip_bytes({"DocSwift.exe": b"new"})
        info = update_info(archive)
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            target = root / "DocSwift"
            target.mkdir()
            executable = target / "DocSwift.exe"
            executable.write_bytes(b"old")
            staging = root / "staging"
            staging.mkdir()
            (staging / executable.name).write_bytes(b"new")
            prepared = PreparedUpdate(
                info,
                root / info.asset.name,
                staging,
            )
            with (
                patch.object(
                    __import__("update_service").sys,
                    "frozen",
                    True,
                    create=True,
                ),
                patch.object(
                    __import__("update_service").sys,
                    "executable",
                    str(executable),
                ),
            ):
                with self.assertRaisesRegex(UpdateError, "任务数据库"):
                    UpdateService().launch_portable_installer(
                        prepared,
                        target / "data",
                    )

    def test_internal_manifest_is_preferred(self) -> None:
        manifest_url = (
            "http://192.168.100.3/updates/docswift/latest.json"
        )
        payload = {
            "manifest_version": 1,
            "application": "DocSwift",
            "version": "0.3.0",
            "published_at": "2026-07-31T08:32:00+08:00",
            "download_url": (
                "http://192.168.100.3/updates/docswift/releases/v0.3.0/"
                "DocSwift-v0.3.0-windows-portable.zip"
            ),
            "sha256": "b" * 64,
            "size": 456,
            "notes": "内部版本",
        }
        with patch(
            "update_service._request_bytes",
            return_value=json.dumps(payload).encode("utf-8"),
        ) as request:
            info = UpdateService(manifest_url=manifest_url).check("0.2.0")

        self.assertIsNotNone(info)
        assert info is not None
        self.assertEqual("0.3.0", info.version)
        self.assertEqual("公司服务器", info.source)
        self.assertEqual("b" * 64, info.asset.sha256)
        request.assert_called_once_with(manifest_url)

    def test_current_internal_version_does_not_query_public_source(self) -> None:
        manifest_url = (
            "http://192.168.100.3/updates/docswift/latest.json"
        )
        payload = {
            "manifest_version": 1,
            "application": "DocSwift",
            "version": "0.2.0",
        }
        with patch(
            "update_service._request_bytes",
            return_value=json.dumps(payload).encode("utf-8"),
        ) as request:
            result = UpdateService(manifest_url=manifest_url).check("0.2.0")

        self.assertIsNone(result)
        request.assert_called_once_with(manifest_url)

    def test_github_is_used_when_internal_server_is_unavailable(self) -> None:
        manifest_url = (
            "http://192.168.100.3/updates/docswift/latest.json"
        )
        github_payload = {
            "tag_name": "v0.3.0",
            "body": "公网备用版本",
            "html_url": "https://github.com/example/releases/tag/v0.3.0",
            "published_at": "2026-07-31T00:00:00Z",
            "assets": [
                {
                    "name": "DocSwift-v0.3.0-windows-portable.zip",
                    "browser_download_url": "https://example.invalid/update.zip",
                    "size": 123,
                    "digest": f"sha256:{'c' * 64}",
                }
            ],
        }

        def response(url: str, *_args, **_kwargs) -> bytes:
            if url == manifest_url:
                raise UpdateError("内部服务器离线")
            return json.dumps(github_payload).encode("utf-8")

        with patch("update_service._request_bytes", side_effect=response):
            info = UpdateService(
                "example/repo",
                manifest_url=manifest_url,
            ).check("0.2.0")

        self.assertIsNotNone(info)
        assert info is not None
        self.assertEqual("GitHub 备用源", info.source)

    def test_internal_manifest_rejects_untrusted_download_url(self) -> None:
        manifest_url = (
            "http://192.168.100.3/updates/docswift/latest.json"
        )
        payload = {
            "manifest_version": 1,
            "application": "DocSwift",
            "version": "0.3.0",
            "download_url": (
                "http://example.invalid/DocSwift-v0.3.0-windows-portable.zip"
            ),
            "sha256": "d" * 64,
            "size": 123,
        }
        github_error = UpdateError("公网不可用")
        with patch(
            "update_service._request_bytes",
            side_effect=[
                json.dumps(payload).encode("utf-8"),
                github_error,
            ],
        ):
            with self.assertRaisesRegex(
                UpdateError,
                "公司服务器.*受信任目录.*GitHub",
            ):
                UpdateService(
                    "example/repo",
                    manifest_url=manifest_url,
                ).check("0.2.0")


if __name__ == "__main__":
    unittest.main()
