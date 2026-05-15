"""Backend abstraction for package managers (apt, dnf/yum)."""

from __future__ import annotations

from abc import ABC, abstractmethod

from pkgeter.models import PackageInfo, RepoConfig


class PmBackend(ABC):
    """Abstract interface for package manager backends."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Backend identifier, e.g. 'debian', 'rpm'."""
        ...

    @abstractmethod
    def download_package_db(
        self,
        repos: list[RepoConfig],
        arch: str,
        timeout: int = 60,
        force_update: bool = False,
    ) -> dict[str, PackageInfo]:
        """Download metadata from all repos, merge into a single package DB."""
        ...

    @abstractmethod
    def build_download_url(self, base_url: str, pkg: PackageInfo) -> str:
        """Construct the remote download URL for a package file."""
        ...

    @abstractmethod
    def generate_install_script(
        self, files: list[str], target_packages: list[str],
    ) -> str:
        """Generate shell script for offline installation."""
        ...

    def merge_package_dbs(
        self, dbs: list[dict[str, PackageInfo]],
    ) -> dict[str, PackageInfo]:
        """Merge multiple package DBs. Later repos override earlier ones."""
        merged: dict[str, PackageInfo] = {}
        for db in dbs:
            merged.update(db)
        return merged

    @property
    def cache(self) -> "PackageCache | None":
        """Lazily-initialized SQLite package cache."""
        if not hasattr(self, "_cache"):
            try:
                from pkgeter.db.package_cache import PackageCache
                self._cache: PackageCache | None = PackageCache()
            except Exception:
                self._cache = None
        return self._cache

    @staticmethod
    def build_source_id(backend_type: str, url: str, release: str, arch: str, component: str = "") -> str:
        """Build a unique source identifier for the cache."""
        sanitized = url.removeprefix("https://").removeprefix("http://").rstrip("/")
        parts = [backend_type, sanitized, release, arch]
        if component:
            parts.append(component)
        return ":".join(parts)
