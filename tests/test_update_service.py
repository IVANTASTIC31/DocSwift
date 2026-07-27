import hashlib
import io
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from update_service import UpdateService, parse_version


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()


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
            info = UpdateService("example/repo").check("0.2.0")
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
            self.assertIsNone(UpdateService("example/repo").check("0.2.0"))

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
            info = UpdateService("example/repo").check("0.2.0")
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


if __name__ == "__main__":
    unittest.main()
