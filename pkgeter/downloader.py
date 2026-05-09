"""Concurrent .deb downloader with progress reporting."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Callable, Dict, Optional

import httpx


class Downloader:
    """Download .deb files concurrently with optional SHA256 verification."""

    def __init__(
        self,
        mirror: str,
        dest_dir: Path,
        concurrency: int = 5,
        timeout: int = 120,
        progress_callback: Optional[Callable[[str, int, int], None]] = None,
    ):
        self.mirror = mirror.rstrip("/")
        self.dest_dir = dest_dir
        self.concurrency = concurrency
        self.timeout = timeout
        self.progress_callback = progress_callback

    def download_all(
        self,
        packages: Dict[str, tuple[str, str, int]],
    ) -> Dict[str, Path]:
        """Download all .deb files.

        Args:
            packages: dict of package_name -> (remote_filename, sha256, size)
                      where remote_filename is the relative path from mirror root
                      (e.g. "pool/main/v/vsftpd/vsftpd_3.0.5-3_amd64.deb")

        Returns:
            dict of package_name -> local Path to downloaded file
        """
        results: Dict[str, Path] = {}
        total = len(packages)
        completed = 0

        with httpx.Client(timeout=self.timeout) as client:
            for name, (filename, sha256, _size) in packages.items():
                url = f"{self.mirror}/{filename}"
                local_path = self.dest_dir / Path(filename).name

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

                completed += 1
                if self.progress_callback:
                    self.progress_callback(name, completed, total)

        return results
