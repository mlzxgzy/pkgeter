"""Debian/APT backend implementation.

Implements :class:`PmBackend` for the Debian package manager (``dpkg`` / ``apt``).
Downloads and caches ``Packages.gz`` metadata from Debian repositories, parses
stanzas into :class:`PackageInfo` objects, and provides utilities for download
URL construction and install script generation.
"""

from __future__ import annotations

import gzip
import sys
from typing import Dict

import httpx

from pkgeter.backend import PmBackend
from pkgeter.db.source_cache import SourceCache
from pkgeter.models import PackageInfo, RepoConfig, parse_depends_line


class DebianBackend(PmBackend):
    """Debian/APT backend.

    Handles Debian-style ``Packages.gz`` metadata, ``Release``-file-based cache
    validation, and deterministic ``.deb`` download URLs.
    """

    # ------------------------------------------------------------------
    # PmBackend interface
    # ------------------------------------------------------------------

    @property
    def name(self) -> str:
        return "apt"

    def download_package_db(
        self,
        repos: list[RepoConfig],
        arch: str,
        timeout: int = 60,
        force_update: bool = False,
    ) -> Dict[str, PackageInfo]:
        """Download metadata from all Debian repos, merge into a single package DB.

        For each repository:

        * For the ``main`` component: uses :class:`SourceCache` (Release-based
          SHA256 caching, same strategy as APT).
        * For other components (or when the cache is unavailable): falls back
          to a direct HTTP download.

        Errors on individual repos/components are silently skipped so that a
        single unavailable repo does not break the whole resolution.
        """
        dbs: list[Dict[str, PackageInfo]] = []

        for repo in repos:
            repo_db = self._download_repo(repo, arch, timeout=timeout, force_update=force_update)
            if repo_db:
                dbs.append(repo_db)

        return self.merge_package_dbs(dbs)

    @staticmethod
    def build_download_url(base_url: str, pkg: PackageInfo) -> str:
        """Construct the remote download URL for a .deb file.

        For Debian, the ``PackageInfo.filename`` stores the relative path from
        the mirror root (e.g. ``pool/main/v/vsftpd/vsftpd_3.0.5-3_amd64.deb``).
        """
        return f"{base_url.rstrip('/')}/{pkg.filename}"

    @staticmethod
    def generate_install_script(
        files: list[str],
        target_packages: list[str],
    ) -> str:
        """Generate a bash install script that uses ``dpkg -i``."""
        pkg_list = " ".join(target_packages)
        deb_cmds = "\n".join(
            f'sudo dpkg -i "{name}"' for name in files
        )
        return (
            "#!/bin/bash\n"
            "# pkgeter - Offline Debian package installation script\n"
            f"# Target packages: {pkg_list}\n"
            "#\n"
            "# Install packages one by one in dependency order.\n"
            "\n"
            'SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"\n'
            'cd "$SCRIPT_DIR"\n'
            f"{deb_cmds}\n"
        )

    # ------------------------------------------------------------------
    # Stanza / Packages.gz parsing (static for easy re-export by compat)
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_deb_stanza(text: str) -> PackageInfo | None:
        """Parse a single Debian package stanza from a ``Packages`` file.

        Returns ``None`` when the stanza does not contain a ``Package`` field.
        """
        text = text.strip()
        pkg = PackageInfo(package="", version="")

        current_key: str | None = None
        current_value: list[str] = []

        def _set_field(key: str, value: str) -> None:
            if key == "Package":
                pkg.package = value
            elif key == "Version":
                pkg.version = value
            elif key == "Architecture":
                pkg.arch = value
            elif key == "Filename":
                pkg.filename = value
            elif key == "SHA256":
                pkg.sha256 = value
            elif key == "Size":
                try:
                    pkg.size = int(value)
                except ValueError:
                    pass
            elif key == "Description":
                pkg.description = value
            elif key == "Provides":
                pkg.provides = [s.strip() for s in value.split(",")]
            elif key == "Depends":
                pkg.depends = parse_depends_line(value)

        for line in text.split("\n"):
            if line.startswith(" ") or line.startswith("\t"):
                if current_key:
                    current_value.append(line.strip())
                continue
            if ":" in line:
                if current_key:
                    _set_field(current_key, " ".join(current_value))
                current_key = line.split(":", 1)[0].strip()
                rest = line.split(":", 1)[1].strip()
                current_value = [rest]
            else:
                current_key = None
                current_value = []

        if current_key and current_value:
            _set_field(current_key, " ".join(current_value))

        return pkg if pkg.package else None

    @staticmethod
    def _parse_packages_gz(data: bytes) -> Dict[str, PackageInfo]:
        """Parse gzip-compressed (or raw) ``Packages`` content into a dict.

        Keys are package names (lowercase), values are :class:`PackageInfo`.
        """
        try:
            raw = gzip.decompress(data)
        except OSError:
            raw = data

        text = raw.decode("utf-8", errors="replace")
        packages: Dict[str, PackageInfo] = {}

        stanzas = text.split("\n\n")
        for stanza in stanzas:
            stanza = stanza.strip()
            if not stanza:
                continue
            info = DebianBackend._parse_deb_stanza(stanza)
            if info and info.package:
                packages[info.package] = info
        return packages

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _download_repo(
        self,
        repo: RepoConfig,
        arch: str,
        *,
        timeout: int = 60,
        force_update: bool = False,
    ) -> Dict[str, PackageInfo] | None:
        """Download and parse *all components* of a single repository."""
        components = repo.components or ["main"]
        repo_db: Dict[str, PackageInfo] = {}

        for component in components:
            try:
                parsed = self._download_component(
                    repo.url, repo.release, component, arch,
                    timeout=timeout, force_update=force_update,
                )
                if parsed:
                    repo_db.update(parsed)
            except Exception:
                # Don't fail entirely just because one component is bad
                continue

        for pkg in repo_db.values():
            pkg.base_url = repo.url
        return repo_db if repo_db else None

    def _download_component(
        self,
        mirror: str,
        release: str,
        component: str,
        arch: str,
        *,
        timeout: int = 60,
        force_update: bool = False,
    ) -> Dict[str, PackageInfo] | None:
        source_id = self.build_source_id("deb", mirror, release, arch, component)

        if component == "main":
            cache_obj = SourceCache(mirror, release, arch)
            if cache_obj.update(timeout=timeout, force_update=force_update):
                action = cache_obj.last_action
                if action == "cache_hit":
                    print(" (cached)", end="", flush=True)
                elif action == "downloaded":
                    print(" (downloaded)", end="", flush=True)

                # Check SQLite cache before parsing
                raw = cache_obj.read_packages_gz()
                if raw is not None:
                    file_sha = cache_obj._file_sha256(cache_obj._packages_gz_path)
                    if file_sha and not force_update and self.cache:
                        if self.cache.is_fresh(source_id, file_sha):
                            loaded = self.cache.load(source_id)
                            if loaded is not None:
                                return loaded
                    # Parse and cache
                    parsed = self._parse_packages_gz(raw)
                    if file_sha and self.cache:
                        self.cache.store(source_id, file_sha, parsed)
                    return parsed

        # Direct HTTP fallback (non-main components, or cache failure)
        print(" (downloading)", end="", flush=True)
        url = self._build_component_url(mirror, release, component, arch)
        with httpx.Client(timeout=timeout) as client:
            resp = client.get(url, follow_redirects=True)
            resp.raise_for_status()
        parsed = self._parse_packages_gz(resp.content)

        # Cache the directly-downloaded result too
        if self.cache:
            import hashlib
            content_sha = hashlib.sha256(resp.content).hexdigest()
            self.cache.store(source_id, content_sha, parsed)

        return parsed

    @staticmethod
    def _build_component_url(
        mirror: str,
        release: str,
        component: str,
        arch: str,
    ) -> str:
        """Build the ``Packages.gz`` URL for an arbitrary component."""
        base = mirror.rstrip("/")
        return f"{base}/dists/{release}/{component}/binary-{arch}/Packages.gz"
