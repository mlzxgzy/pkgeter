"""Tests for Debian source cache (Release + Packages.gz caching)."""

from __future__ import annotations

import hashlib
from pathlib import Path
from unittest.mock import patch

import httpx

from pkgeter.db.source_cache import SourceCache, _sanitize_mirror, parse_packages_sha256

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

SAMPLE_RELEASE = """\
Origin: Debian
Label: Debian
Suite: stable
Codename: bookworm
Date: Sat, 01 Jan 2024 00:00:00 UTC
Architectures: amd64 arm64
Components: main contrib non-free
SHA256:
  1111111111111111111111111111111111111111111111111111111111111111 1234 main/binary-amd64/Packages.gz
  2222222222222222222222222222222222222222222222222222222222222222 5678 main/binary-arm64/Packages.gz
  3333333333333333333333333333333333333333333333333333333333333333 9012 main/binary-amd64/Packages.xz

SHA512:
  444444444444444444444444444444444444444444444444444444444444444444444444444444444444444444444444 1234 main/binary-amd64/Packages.gz
"""


def make_dummy_gz(content: bytes = b"dummy") -> bytes:
    import gzip
    return gzip.compress(content)


def sha256_of(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _fake_release_content(arch: str, gz_hash: str) -> str:
    return f"""\
SHA256:
  {gz_hash} 1234 main/binary-{arch}/Packages.gz
"""


class _MockResponse:
    def __init__(self, content: bytes, status: int = 200):
        self.content = content
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("error", request=None, response=self)


class _MockClient:
    """Simulates httpx.Client, returning pre-configured responses per URL."""

    def __init__(self, responses: dict):
        self._responses = responses

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def get(self, url: str, **kwargs):
        if url in self._responses:
            return self._responses[url]
        return _MockResponse(b"not found", 404)


def make_cache(cache_dir: Path) -> SourceCache:
    """Create a SourceCache with its cache root redirected to *cache_dir*."""
    cache = SourceCache("https://deb.debian.org/debian", "bookworm", "amd64")
    cache._cache_dir = cache_dir
    cache._release_path = cache_dir / "Release"
    cache._packages_gz_path = cache_dir / "Packages.gz"
    return cache


# ---------------------------------------------------------------------------
# _sanitize_mirror
# ---------------------------------------------------------------------------


class TestSanitizeMirror:
    def test_https(self):
        assert _sanitize_mirror("https://deb.debian.org/debian") == "deb.debian.org_debian"

    def test_http(self):
        assert _sanitize_mirror("http://ftp.debian.org/debian") == "ftp.debian.org_debian"

    def test_with_port(self):
        assert _sanitize_mirror("https://mirror.example.com:8080/debian") == "mirror.example.com_8080_debian"


# ---------------------------------------------------------------------------
# parse_packages_sha256
# ---------------------------------------------------------------------------


class TestParsePackagesSha256:
    def test_amd64(self):
        expected = "1111111111111111111111111111111111111111111111111111111111111111"
        assert parse_packages_sha256(SAMPLE_RELEASE, "amd64") == expected

    def test_arm64(self):
        expected = "2222222222222222222222222222222222222222222222222222222222222222"
        assert parse_packages_sha256(SAMPLE_RELEASE, "arm64") == expected

    def test_not_found(self):
        assert parse_packages_sha256(SAMPLE_RELEASE, "i386") is None

    def test_empty_release(self):
        assert parse_packages_sha256("", "amd64") is None

    def test_no_sha256_section(self):
        text = "Origin: Debian\nCodename: bookworm\n"
        assert parse_packages_sha256(text, "amd64") is None


# ---------------------------------------------------------------------------
# SourceCache — update & read with mocked HTTP
# ---------------------------------------------------------------------------


class TestSourceCacheUpdate:
    def test_fresh_download(self, tmp_path: Path):
        """First run: downloads Release, then Packages.gz, caches both."""
        dummy_gz = make_dummy_gz(b"package data")
        gz_sha = sha256_of(dummy_gz)
        release_text = _fake_release_content("amd64", gz_sha)

        cache = make_cache(tmp_path)
        with patch(
            "pkgeter.db.source_cache.httpx.Client",
            return_value=_MockClient({
                cache._release_url(): _MockResponse(release_text.encode()),
                cache._packages_url(): _MockResponse(dummy_gz),
            }),
        ):
            assert cache.update() is True
            assert cache.is_populated
            assert cache.read_packages_gz() == dummy_gz

        # Verify Release file cached
        assert (tmp_path / "Release").exists()
        assert (tmp_path / "Release").read_text() == release_text

    def test_cached_fresh(self, tmp_path: Path):
        """Second run: Release matches cached → no re-download of Packages.gz."""
        dummy_gz = make_dummy_gz(b"package data")
        gz_sha = sha256_of(dummy_gz)
        release_text = _fake_release_content("amd64", gz_sha)

        (tmp_path / "Release").write_text(release_text)
        (tmp_path / "Packages.gz").write_bytes(dummy_gz)

        cache = make_cache(tmp_path)
        with patch(
            "pkgeter.db.source_cache.httpx.Client",
            return_value=_MockClient({
                cache._release_url(): _MockResponse(release_text.encode()),
                # No Packages.gz URL needed — cached matches expected hash
            }),
        ):
            assert cache.update() is True
            assert cache.read_packages_gz() == dummy_gz

    def test_cached_stale(self, tmp_path: Path):
        """Release has new SHA256 → re-download Packages.gz."""
        old_gz = make_dummy_gz(b"old data")
        new_gz = make_dummy_gz(b"new data")
        new_sha = sha256_of(new_gz)
        release_text = _fake_release_content("amd64", new_sha)

        (tmp_path / "Packages.gz").write_bytes(old_gz)  # stale

        cache = make_cache(tmp_path)
        with patch(
            "pkgeter.db.source_cache.httpx.Client",
            return_value=_MockClient({
                cache._release_url(): _MockResponse(release_text.encode()),
                cache._packages_url(): _MockResponse(new_gz),
            }),
        ):
            assert cache.update() is True
            assert cache.read_packages_gz() == new_gz

    def test_release_fails_uses_stale(self, tmp_path: Path):
        """Release download fails → use stale cache if available."""
        dummy_gz = make_dummy_gz(b"stale but usable")
        (tmp_path / "Release").write_text("stale release")
        (tmp_path / "Packages.gz").write_bytes(dummy_gz)

        cache = make_cache(tmp_path)
        with patch(
            "pkgeter.db.source_cache.httpx.Client",
            return_value=_MockClient({}),
        ):
            assert cache.update() is True
            assert cache.read_packages_gz() == dummy_gz

    def test_release_fails_no_cache(self, tmp_path: Path):
        """Release download fails and no cache → returns False."""
        cache = make_cache(tmp_path)
        with patch(
            "pkgeter.db.source_cache.httpx.Client",
            return_value=_MockClient({}),
        ):
            assert cache.update() is False

    def test_sha256_mismatch(self, tmp_path: Path):
        """Downloaded Packages.gz has wrong SHA256 → returns False, doesn't save."""
        bad_gz = make_dummy_gz(b"bad data")
        wrong_sha = "f" * 64
        release_text = _fake_release_content("amd64", wrong_sha)

        cache = make_cache(tmp_path)
        with patch(
            "pkgeter.db.source_cache.httpx.Client",
            return_value=_MockClient({
                cache._release_url(): _MockResponse(release_text.encode()),
                cache._packages_url(): _MockResponse(bad_gz),
            }),
        ):
            assert cache.update() is False
            assert not cache.is_populated

    def test_packages_download_fails_stale(self, tmp_path: Path):
        """Release says new hash, but Packages.gz download fails → keep stale."""
        dummy_gz = make_dummy_gz(b"stale data")
        new_hash = "a" * 64
        release_text = _fake_release_content("amd64", new_hash)

        (tmp_path / "Release").write_text(release_text)
        (tmp_path / "Packages.gz").write_bytes(dummy_gz)

        cache = make_cache(tmp_path)
        with patch(
            "pkgeter.db.source_cache.httpx.Client",
            return_value=_MockClient({
                cache._release_url(): _MockResponse(release_text.encode()),
                # Packages.gz URL not in dict → 404
            }),
        ):
            assert cache.update() is True  # stale fallback
            assert cache.read_packages_gz() == dummy_gz


# ---------------------------------------------------------------------------
# clear()
# ---------------------------------------------------------------------------


class TestClear:
    def test_clears_directory(self, tmp_path: Path):
        (tmp_path / "Release").write_text("data")
        (tmp_path / "Packages.gz").write_bytes(b"data")

        cache = make_cache(tmp_path)
        assert cache.is_populated
        cache.clear()
        assert not tmp_path.exists()

    def test_non_existent(self, tmp_path: Path):
        cache = make_cache(tmp_path)
        cache.clear()  # Should not raise


# ---------------------------------------------------------------------------
# is_populated
# ---------------------------------------------------------------------------


class TestIsPopulated:
    def test_true(self, tmp_path: Path):
        (tmp_path).mkdir(parents=True, exist_ok=True)
        (tmp_path / "Release").write_text("r")
        (tmp_path / "Packages.gz").write_bytes(b"p")
        assert make_cache(tmp_path).is_populated is True

    def test_false(self, tmp_path: Path):
        assert make_cache(tmp_path).is_populated is False

    def test_only_release(self, tmp_path: Path):
        (tmp_path).mkdir(parents=True, exist_ok=True)
        (tmp_path / "Release").write_text("r")
        assert make_cache(tmp_path).is_populated is False


# ---------------------------------------------------------------------------
# read_release_text
# ---------------------------------------------------------------------------


class TestReadRelease:
    def test_reads_cached(self, tmp_path: Path):
        (tmp_path).mkdir(parents=True, exist_ok=True)
        (tmp_path / "Release").write_text("Origin: Debian")
        assert make_cache(tmp_path).read_release_text() == "Origin: Debian"

    def test_missing(self, tmp_path: Path):
        assert make_cache(tmp_path).read_release_text() is None
