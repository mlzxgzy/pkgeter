"""RPM/DNF backend implementation.

Implements :class:`PmBackend` for the RPM package manager (``rpm`` / ``dnf`` / ``yum``).
Downloads and caches ``repomd.xml`` / ``primary.xml.gz`` metadata from RPM repositories,
parses XML into :class:`PackageInfo` objects, and provides utilities for download
URL construction and install script generation.
"""

from __future__ import annotations

import gzip
import hashlib
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Dict

import httpx

from pkgeter.backend import PmBackend
from pkgeter.config import CONFIG_PATH
from pkgeter.models import Dependency, PackageInfo, RepoConfig

# XML namespaces used in RPM repository metadata.
NS = {
    "repo": "http://linux.duke.edu/metadata/repo",
    "rpm": "http://linux.duke.edu/metadata/common",
    "rpm-format": "http://linux.duke.edu/metadata/rpm",
}


class RpmBackend(PmBackend):
    """RPM/DNF backend.

    Handles RPM-style ``repomd.xml`` / ``primary.xml.gz`` metadata, file-based
    SHA256 caching, and deterministic ``.rpm`` download URLs.
    """

    # ------------------------------------------------------------------
    # PmBackend interface
    # ------------------------------------------------------------------

    @property
    def name(self) -> str:
        return "rpm"

    def download_package_db(
        self,
        repos: list[RepoConfig],
        arch: str,
        timeout: int = 60,
    ) -> Dict[str, PackageInfo]:
        """Download metadata from all RPM repos, merge into a single package DB.

        For each repository:

        * Downloads ``repomd.xml`` to discover the location and SHA256 of the
          primary metadata file.
        * Checks a per-repo file cache (``~/.config/pkgeter/sources/rpm/``)
          and skips the download when the cached file's SHA256 matches.
        * Downloads ``primary.xml.gz``, verifies its SHA256, caches it, and
          parses it into :class:`PackageInfo` objects.

        Errors on individual repos are silently skipped so that a single
        unavailable repo does not break the whole resolution.
        """
        dbs: list[Dict[str, PackageInfo]] = []

        for repo in repos:
            try:
                repo_db = self._download_repo(repo, timeout=timeout)
                if repo_db:
                    dbs.append(repo_db)
            except Exception:
                continue

        return self.merge_package_dbs(dbs)

    @staticmethod
    def build_download_url(base_url: str, pkg: PackageInfo) -> str:
        """Construct the remote download URL for an RPM file.

        For RPM repositories, the ``PackageInfo.filename`` stores the relative
        path from the repository root (e.g. ``Packages/openssl-1.1.1k-7.el8_9.x86_64.rpm``).
        """
        return f"{base_url.rstrip('/')}/{pkg.filename}"

    @staticmethod
    def generate_install_script(
        files: list[str],
        target_packages: list[str],
    ) -> str:
        """Generate a bash install script that uses ``rpm -ivh``."""
        pkg_list = " ".join(target_packages)
        rpm_cmds = "\n".join(
            f'sudo rpm -ivh "{name}"' for name in files
        )
        return (
            "#!/bin/bash\n"
            "# pkgeter - Offline RPM package installation script\n"
            f"# Target packages: {pkg_list}\n"
            "#\n"
            "# Install packages one by one in dependency order.\n"
            "\n"
            'SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"\n'
            'cd "$SCRIPT_DIR"\n'
            f"{rpm_cmds}\n"
        )

    # ------------------------------------------------------------------
    # XML Parsing
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_repomd(xml_data: str) -> tuple[str, str]:
        """Parse ``repomd.xml``, extract the primary metadata href and SHA256.

        Returns a ``(href, sha256)`` tuple where *href* is the relative path
        to the primary metadata (e.g. ``repodata/abc123-primary.xml.gz``).
        """
        root = ET.fromstring(xml_data)
        data_el = root.find("repo:data[@type='primary']", NS)
        if data_el is None:
            raise ValueError("No primary data element found in repomd.xml")
        href_el = data_el.find("repo:location", NS)
        href = href_el.get("href", "") if href_el is not None else ""
        checksum_el = data_el.find("repo:checksum", NS)
        sha256 = checksum_el.text if checksum_el is not None else ""
        return href, sha256

    @staticmethod
    def _parse_primary(gz_data: bytes) -> Dict[str, PackageInfo]:
        """Parse gzip-compressed ``primary.xml.gz`` into a package database.

        Keys are package names (as-is, RPM style), values are
        :class:`PackageInfo`.
        """
        raw = gzip.decompress(gz_data)
        root = ET.fromstring(raw)

        packages: Dict[str, PackageInfo] = {}
        for pkg_el in root.findall("rpm:package", NS):
            name_el = pkg_el.find("rpm:name", NS)
            if name_el is None or not name_el.text:
                continue

            name = name_el.text

            arch_el = pkg_el.find("rpm:arch", NS)
            arch = arch_el.text if arch_el is not None else ""

            ver_el = pkg_el.find("rpm:version", NS)
            epoch = ver_el.get("epoch", "0") if ver_el is not None else "0"
            ver = ver_el.get("ver", "") if ver_el is not None else ""
            rel = ver_el.get("rel", "") if ver_el is not None else ""

            if epoch and epoch != "0":
                version = f"{epoch}:{ver}-{rel}"
            else:
                version = f"{ver}-{rel}"

            loc_el = pkg_el.find("rpm:location", NS)
            filename = loc_el.get("href", "") if loc_el is not None else ""

            chk_el = pkg_el.find("rpm:checksum", NS)
            sha256 = chk_el.text if chk_el is not None and chk_el.text else ""

            format_el = pkg_el.find("rpm:format", NS)
            depends: list[list[Dependency]] = []
            provides: list[str] = []

            if format_el is not None:
                requires_el = format_el.find("rpm-format:requires", NS)
                if requires_el is not None:
                    for entry in requires_el.findall("rpm-format:entry", NS):
                        dep_name = entry.get("name", "")
                        if dep_name:
                            depends.append([Dependency(name=dep_name)])

                provides_el = format_el.find("rpm-format:provides", NS)
                if provides_el is not None:
                    for entry in provides_el.findall("rpm-format:entry", NS):
                        prov_name = entry.get("name", "")
                        if prov_name and prov_name == name:
                            provides.append(prov_name)

            packages[name] = PackageInfo(
                package=name,
                version=version,
                arch=arch,
                filename=filename,
                sha256=sha256,
                depends=depends,
                provides=provides,
            )

        return packages

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _download_repo(
        self,
        repo: RepoConfig,
        *,
        timeout: int = 60,
    ) -> Dict[str, PackageInfo] | None:
        """Download and parse a single RPM repository's metadata."""
        base_url = repo.url.rstrip("/")
        repomd_url = f"{base_url}/repodata/repomd.xml"

        with httpx.Client(timeout=timeout) as client:
            resp = client.get(repomd_url, follow_redirects=True)
            resp.raise_for_status()
        repomd_xml = resp.text

        href, expected_sha256 = self._parse_repomd(repomd_xml)

        # Per-repo file cache
        sanitized = re.sub(r"[^a-zA-Z0-9]", "_", base_url)
        cache_dir = CONFIG_PATH.parent / "sources" / "rpm" / sanitized
        cache_path = cache_dir / "primary.xml.gz"

        # Check cache: if cached file's SHA256 matches, skip download
        if cache_path.exists():
            cached_sha256 = hashlib.sha256(cache_path.read_bytes()).hexdigest()
            if cached_sha256 == expected_sha256:
                return self._parse_primary(cache_path.read_bytes())

        # Download primary.xml.gz
        primary_url = f"{base_url}/{href}"
        with httpx.Client(timeout=timeout) as client:
            resp = client.get(primary_url, follow_redirects=True)
            resp.raise_for_status()

        data = resp.content

        # Verify SHA256
        actual_sha256 = hashlib.sha256(data).hexdigest()
        if actual_sha256 != expected_sha256:
            raise ValueError(
                f"SHA256 mismatch for {primary_url}: "
                f"expected {expected_sha256}, got {actual_sha256}"
            )

        # Save to cache
        cache_dir.mkdir(parents=True, exist_ok=True)
        cache_path.write_bytes(data)

        return self._parse_primary(data)


class DnfBackend(RpmBackend):
    """DNF backend — identical to RPM, but reports ``name == 'dnf'``."""

    @property
    def name(self) -> str:
        return "dnf"
