"""Download cache with 1-day TTL in system temp directory.

The cache stores downloaded .deb/.rpm files in ``tempfile.gettempdir() /
pkgeter-download-cache/`` with a JSON manifest tracking URL → SHA256 + timestamp.

Usage::

    cache = DownloadCache()
    data = cache.get(url, sha256)
    if data is None:
        data = download_from_network(url)
        cache.put(url, filename, sha256, data)
"""

from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
import time
from pathlib import Path

CACHE_TTL = 86400  # 24 hours in seconds


class DownloadCache:
    """Persistent download cache with 1-day TTL in the system temp directory."""

    def __init__(self, ttl: int = CACHE_TTL) -> None:
        self.cache_dir = Path(tempfile.gettempdir()) / "pkgeter-download-cache"
        self.manifest_path = self.cache_dir / "manifest.json"
        self.ttl = ttl

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _load_manifest(self) -> dict[str, dict]:
        if not self.manifest_path.exists():
            return {}
        try:
            return json.loads(self.manifest_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}

    def _save_manifest(self, manifest: dict[str, dict]) -> None:
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.manifest_path.write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    @staticmethod
    def _cache_filename(url: str) -> str:
        """Deterministic collision-free filename for a given URL."""
        raw = url.rsplit("/", 1)[-1]
        ext = Path(raw).suffix or ".deb"
        hashed = hashlib.sha256(url.encode()).hexdigest()
        return hashed + ext

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get(self, url: str, sha256: str) -> bytes | None:
        """Return cached content for *url* if valid, or ``None``.

        Validity checks:
        * Entry exists in manifest for this *url*
        * Entry is newer than ``ttl``
        * Stored SHA256 matches the given *sha256*
        * Actual cache file exists on disk

        On cache hit, the entry's timestamp is refreshed so it stays
        alive for another ``ttl`` window.
        """
        manifest = self._load_manifest()
        entry = manifest.get(url)
        if not entry:
            return None

        # TTL check
        if time.time() - entry.get("cached_at", 0) > self.ttl:
            return None

        # SHA256 check
        if entry.get("sha256") != sha256:
            return None

        # File existence check
        cache_path = self.cache_dir / entry.get("filename", "")
        if not cache_path.exists():
            return None

        # Refresh timestamp — keeps the entry alive
        entry["cached_at"] = time.time()
        self._save_manifest(manifest)

        return cache_path.read_bytes()

    def put(self, url: str, sha256: str, data: bytes) -> Path:
        """Store *data* in the cache, keyed by *url*.

        Returns the local ``Path`` to the cached file.
        """
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        filename = self._cache_filename(url)
        cache_path = self.cache_dir / filename
        cache_path.write_bytes(data)

        manifest = self._load_manifest()
        manifest[url] = {
            "filename": filename,
            "sha256": sha256,
            "cached_at": time.time(),
        }
        self._save_manifest(manifest)
        return cache_path

    def cleanup(self) -> None:
        """Remove expired entries from the cache.

        Called automatically on normal process exit via ``atexit``.
        Safe to call multiple times — no-op when nothing is expired.
        """
        manifest = self._load_manifest()
        if not manifest:
            return

        now = time.time()
        expired: list[str] = [
            url
            for url, entry in manifest.items()
            if now - entry.get("cached_at", 0) > self.ttl
        ]
        if not expired:
            return

        for url in expired:
            entry = manifest.pop(url)
            path = self.cache_dir / entry.get("filename", "")
            if path.exists():
                path.unlink()
        self._save_manifest(manifest)

    def clear_all(self) -> None:
        """Delete the entire cache directory and manifest."""
        if self.cache_dir.exists():
            shutil.rmtree(self.cache_dir)
