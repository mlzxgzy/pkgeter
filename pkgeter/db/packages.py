"""Backward-compat shim — import from :mod:`pkgeter.backend.debian` instead.

All parsing logic has moved to :class:`pkgeter.backend.debian.DebianBackend`.
This module re-exports the relevant symbols so that existing callers and tests
keep working without modification.
"""

from __future__ import annotations

import sys
from typing import Dict

import httpx

from pkgeter.backend.debian import DebianBackend
from pkgeter.models import PackageInfo

# ---------------------------------------------------------------------------
# Re-export parsing helpers from the backend
# ---------------------------------------------------------------------------

parse_packages_file = DebianBackend._parse_packages_gz
"""Parse gzip (or raw) Packages data into ``dict[str, PackageInfo]``."""

_parse_stanza = DebianBackend._parse_deb_stanza
"""Parse a single Debian package stanza string."""

# ---------------------------------------------------------------------------
# Convenience / legacy functions kept for backward compat
# ---------------------------------------------------------------------------


def build_packages_url(mirror: str, release: str, arch: str) -> str:
    """Build the URL for ``main/binary-{arch}/Packages.gz`` on a Debian mirror."""
    mirror = mirror.rstrip("/")
    return f"{mirror}/dists/{release}/main/binary-{arch}/Packages.gz"


def download_packages_gz(url: str, timeout: int = 60) -> bytes:
    """Download ``Packages.gz`` from a Debian mirror (no caching)."""
    with httpx.Client(timeout=timeout) as client:
        resp = client.get(url, follow_redirects=True)
        resp.raise_for_status()
        return resp.content


def download_package_db(
    mirror: str,
    release: str,
    arch: str,
    use_cache: bool = True,
    timeout: int = 60,
) -> Dict[str, PackageInfo]:
    """High-level: download (or load from cache) Packages.gz and parse.

    When *use_cache* is ``True`` (default), the function stores downloaded files
    under ``~/.config/pkgeter/sources/`` and uses SHA256 checksums from the
    Debian ``Release`` file to avoid re-downloading unchanged data (like APT).
    """
    if use_cache:
        from pkgeter.db.source_cache import SourceCache

        cache = SourceCache(mirror, release, arch)
        if cache.update(timeout=timeout):
            raw = cache.read_packages_gz()
            if raw is not None:
                return parse_packages_file(raw)
        # Cache update/download failed – fall through to direct download
        print(
            "Warning: cache unavailable, falling back to direct download",
            file=sys.stderr,
        )

    url = build_packages_url(mirror, release, arch)
    raw = download_packages_gz(url, timeout)
    return parse_packages_file(raw)
