"""Concurrent .deb downloader with progress reporting and cache support."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Callable, Dict, Optional

import httpx

from pkgeter.cache import DownloadCache


class Downloader:
    """Download .deb files concurrently with optional SHA256 verification.

    If a ``DownloadCache`` instance is provided via the *cache* parameter,
    ``download_all`` will check the cache before making HTTP requests and
    store newly-downloaded files in the cache for future reuse.
    """

    def __init__(
        self,
        mirror: str,
        dest_dir: Path,
        concurrency: int = 5,
        timeout: int = 120,
        progress_callback: Optional[Callable[[str, int, int], None]] = None,
        cache: Optional[DownloadCache] = None,
    ):
        self.mirror = mirror.rstrip("/")
        self.dest_dir = dest_dir
        self.concurrency = concurrency
        self.timeout = timeout
        self.progress_callback = progress_callback
        self.cache = cache

    def download_all(
        self,
        packages: Dict[str, tuple[str, str, int]],
    ) -> Dict[str, Path]:
        """Download all package files.

        Args:
            packages: dict of package_name -> (url, sha256, size)
                      where url is the full remote URL to download from.

        Returns:
            dict of package_name -> local Path to downloaded file
        """
        results: Dict[str, Path] = {}
        total = len(packages)
        completed = 0

        with httpx.Client(timeout=self.timeout) as client:
            for name, (url, sha256, _size) in packages.items():
                local_path = self.dest_dir / url.rsplit("/", 1)[-1]

                # --- Cache check ---
                if self.cache and sha256:
                    cached_data = self.cache.get(url, sha256)
                    if cached_data is not None:
                        self.dest_dir.mkdir(parents=True, exist_ok=True)
                        local_path.write_bytes(cached_data)
                        results[name] = local_path
                        completed += 1
                        if self.progress_callback:
                            self.progress_callback(
                                name, completed, total,
                            )
                        continue

                # --- Network download ---
                try:
                    resp = client.get(url, follow_redirects=True)
                    resp.raise_for_status()
                    data = resp.content

                    if sha256:
                        actual_sha = hashlib.sha256(data).hexdigest()
                        if actual_sha != sha256:
                            raise ValueError(
                                f"SHA256 mismatch for {name}: "
                                f"expected {sha256}, got {actual_sha}"
                            )

                    self.dest_dir.mkdir(parents=True, exist_ok=True)
                    local_path.write_bytes(data)
                    results[name] = local_path

                except Exception as e:
                    raise RuntimeError(f"Failed to download {name}: {e}") from e

                # --- Store in cache ---
                if self.cache and sha256:
                    self.cache.put(url, sha256, data)

                completed += 1
                if self.progress_callback:
                    self.progress_callback(name, completed, total)

        return results
