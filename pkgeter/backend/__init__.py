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
