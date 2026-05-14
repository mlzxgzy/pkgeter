"""Cache management for Debian source metadata.

Caches Release and Packages.gz under ``~/.config/pkgeter/sources/`` and uses
SHA256 checksums from the Release file for cache validation (like APT).

Directory layout::

    ~/.config/pkgeter/
        config.yaml
        sources/
            <sanitized_mirror>/
                <release>/
                    <arch>/
                        Release          # Cached Release file
                        Packages.gz      # Cached package index
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Optional

import httpx

from pkgeter.config import CONFIG_PATH

CACHE_ROOT = CONFIG_PATH.parent / "sources"


def _sanitize_mirror(mirror: str) -> str:
    """Convert a mirror URL to a filesystem-safe directory name."""
    name = mirror.removeprefix("https://").removeprefix("http://")
    return name.replace("/", "_").replace(":", "_")


def parse_packages_sha256(release_text: str, arch: str) -> Optional[str]:
    """Extract the SHA256 of ``main/binary-{arch}/Packages.gz`` from a Release file."""
    target = f"main/binary-{arch}/Packages.gz"
    in_sha256 = False
    for line in release_text.splitlines():
        stripped = line.strip()
        if stripped == "SHA256:":
            in_sha256 = True
            continue
        if in_sha256:
            # A blank line or a top-level key signals end of SHA256 section
            if not stripped or (not line[0].isspace() and not stripped.startswith((" ", "\t"))):
                in_sha256 = False
                continue
            parts = stripped.split()
            if len(parts) >= 3 and parts[2] == target:
                return parts[0]
    return None


class SourceCache:
    """Cached Debian source with Release-based checksum validation.

    Usage::

        cache = SourceCache("https://deb.debian.org/debian", "bookworm", "amd64")
        if cache.update():
            data = cache.read_packages_gz()
    """

    def __init__(self, mirror: str, release: str, arch: str):
        self.mirror = mirror.rstrip("/")
        self.release = release
        self.arch = arch
        mirror_dir = _sanitize_mirror(self.mirror)
        self._cache_dir = CACHE_ROOT / mirror_dir / release / arch
        self._release_path = self._cache_dir / "Release"
        self._packages_gz_path = self._cache_dir / "Packages.gz"

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _release_url(self) -> str:
        return f"{self.mirror}/dists/{self.release}/Release"

    def _packages_url(self) -> str:
        return (
            f"{self.mirror}/dists/{self.release}"
            f"/main/binary-{self.arch}/Packages.gz"
        )

    @staticmethod
    def _file_sha256(path: Path) -> Optional[str]:
        if not path.exists():
            return None
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def update(self, timeout: int = 60) -> bool:
        """Ensure the cached Packages.gz is up to date.

        Strategy (mirrors APT):

        1. Always try to download the (small) ``Release`` file.
        2. Extract the expected SHA256 of ``Packages.gz``.
        3. If the cached file has the same hash → fresh, nothing to do.
        4. Otherwise download ``Packages.gz``, verify the hash, cache it.

        Returns ``True`` when a valid (possibly stale) cache is available.
        """
        self._cache_dir.mkdir(parents=True, exist_ok=True)

        # -- 1. Download Release file and extract the expected SHA256 ---
        expected_sha256: Optional[str] = None
        release_downloaded = False

        try:
            with httpx.Client(timeout=timeout) as client:
                resp = client.get(self._release_url(), follow_redirects=True)
                resp.raise_for_status()
            release_data = resp.content
            release_downloaded = True

            expected_sha256 = parse_packages_sha256(
                release_data.decode("utf-8", errors="replace"), self.arch,
            )
            # Cache Release for reference even when parsing fails
            self._release_path.write_bytes(release_data)
        except httpx.HTTPError:
            pass  # Will fall back to cache below

        # -- 2. Check whether cached Packages.gz matches -----------------
        if expected_sha256 is not None:
            cached_sha = self._file_sha256(self._packages_gz_path)
            if cached_sha == expected_sha256:
                return True  # Cache is still fresh

        # -- 3. Download Packages.gz (only if we know the expected hash) --
        if expected_sha256 is not None:
            try:
                with httpx.Client(timeout=timeout) as client:
                    resp = client.get(self._packages_url(), follow_redirects=True)
                    resp.raise_for_status()
                raw = resp.content
            except httpx.HTTPError:
                # Network issue – keep stale cache if we have one
                return self._packages_gz_path.exists()

            if hashlib.sha256(raw).hexdigest() != expected_sha256:
                # Checksum mismatch – don't save corrupt data
                return False

            self._packages_gz_path.write_bytes(raw)
            return True

        # -- 4. Fallback paths (Release unavailable or no SHA256 entry) ---
        if self._packages_gz_path.exists():
            # Stale cache is better than nothing
            return True

        # Last resort: download blindly (Release structure unexpected)
        if release_downloaded:
            try:
                with httpx.Client(timeout=timeout) as client:
                    resp = client.get(self._packages_url(), follow_redirects=True)
                    resp.raise_for_status()
                self._packages_gz_path.write_bytes(resp.content)
                return True
            except httpx.HTTPError:
                return False

        return False

    def read_packages_gz(self) -> Optional[bytes]:
        """Read the cached Packages.gz content."""
        if self._packages_gz_path.exists():
            return self._packages_gz_path.read_bytes()
        return None

    def read_release_text(self) -> Optional[str]:
        """Read the cached Release file text."""
        if self._release_path.exists():
            return self._release_path.read_text(encoding="utf-8", errors="replace")
        return None

    @property
    def is_populated(self) -> bool:
        """Whether both Release and Packages.gz are cached on disk."""
        return self._release_path.exists() and self._packages_gz_path.exists()

    def clear(self) -> None:
        """Remove all cached data for this source."""
        import shutil
        if self._cache_dir.exists():
            shutil.rmtree(self._cache_dir)
