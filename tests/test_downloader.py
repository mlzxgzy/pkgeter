"""Tests for downloader (mocked HTTP)."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from pkgeter.downloader import Downloader


def test_downloader_creates_dir(tmp_path):
    dest = tmp_path / "debs"
    pkg_data = {
        "libc6": (
            "https://example.com/debian/pool/main/libc6/libc6_2.36-9_amd64.deb",
            "abc" * 21 + "a",
            1024,
        ),
    }

    with patch("httpx.Client") as MockClient:
        instance = MockClient.return_value.__enter__.return_value
        mock_resp = MagicMock()
        mock_resp.content = b"fake-deb-content"
        mock_resp.raise_for_status = MagicMock()
        instance.get.return_value = mock_resp

        import hashlib
        real_sha = hashlib.sha256(b"fake-deb-content").hexdigest()
        pkg_data["libc6"] = (
            "https://example.com/debian/pool/main/libc6/libc6_2.36-9_amd64.deb",
            real_sha,
            1024,
        )

        d = Downloader(mirror="https://example.com/debian", dest_dir=dest, timeout=10)
        results = d.download_all(pkg_data)

        assert "libc6" in results
        assert results["libc6"].exists()
        assert results["libc6"].read_bytes() == b"fake-deb-content"


def test_downloader_sha256_mismatch(tmp_path):
    dest = tmp_path / "debs"
    pkg_data = {
        "libc6": (
            "https://example.com/debian/pool/main/libc6/libc6_2.36-9_amd64.deb",
            "x" * 64,
            1024,
        ),
    }

    with patch("httpx.Client") as MockClient:
        instance = MockClient.return_value.__enter__.return_value
        mock_resp = MagicMock()
        mock_resp.content = b"fake-deb-content"
        mock_resp.raise_for_status = MagicMock()
        instance.get.return_value = mock_resp

        d = Downloader(mirror="https://example.com/debian", dest_dir=dest, timeout=10)
        with pytest.raises(RuntimeError, match="SHA256 mismatch"):
            d.download_all(pkg_data)
