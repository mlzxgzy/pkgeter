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
import time
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

# Pattern to detect RPM rich dependency expressions (boolean operators)
_RICH_DEP_SPLIT = re.compile(r"\s+(?:and|or|if)\s+")


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
        force_update: bool = False,
    ) -> Dict[str, PackageInfo]:
        """Download metadata from all RPM repos, merge into a single package DB.

        For each repository:

        * Downloads ``repomd.xml`` to discover the location and SHA256 of the
          primary metadata file and (optionally) filelists.
        * Checks a per-repo file cache (``~/.config/pkgeter/sources/rpm/``)
          and skips the download when the cached file's SHA256 matches.
        * Downloads ``primary.xml.gz``, verifies its SHA256, caches it, and
          parses it into :class:`PackageInfo` objects.
        * Downloads ``filelists.xml.gz`` when available and builds a
          :class:`ProvidesIndex` for O(1) dependency resolution.

        Errors on individual repos are silently skipped so that a single
        unavailable repo does not break the whole resolution.
        """
        dbs: list[Dict[str, PackageInfo]] = []
        self._filelists_cache_paths: list[Path] = []

        for repo in repos:
            try:
                repo_db = self._download_repo(repo, timeout=timeout, force_update=force_update)
                if repo_db:
                    dbs.append(repo_db)
            except Exception:
                continue

        merged = self.merge_package_dbs(dbs)

        # Build provides index from primary.xml provides + filelists.xml.gz
        from pkgeter.deps.provides_index import ProvidesIndex
        self.provides_index = ProvidesIndex()
        self.provides_index.build_from_packages(merged)
        for fl_path in self._filelists_cache_paths:
            try:
                self.provides_index.add_filelists(fl_path.read_bytes())
            except Exception:
                pass

        return merged

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
            "#\n"
            '# Auto-detect sudo availability\n'
            'if ! command -v sudo >/dev/null 2>&1; then\n'
            '    sudo() { "$@"; }\n'
            'fi\n'
            "\n"
            'SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"\n'
            'cd "$SCRIPT_DIR"\n'
            f"{rpm_cmds}\n"
        )

    # ------------------------------------------------------------------
    # XML Parsing
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_repomd(xml_data: str) -> dict[str, tuple[str, str]]:
        """Parse ``repomd.xml``, extract metadata locations.

        Returns a dict mapping data type → ``(href, sha256)``.
        Always includes ``'primary'``; may include ``'filelists'``.
        Raises :class:`ValueError` when ``primary`` is missing.
        """
        root = ET.fromstring(xml_data)
        result: dict[str, tuple[str, str]] = {}
        for dtype in ("primary", "filelists"):
            data_el = root.find(f"repo:data[@type='{dtype}']", NS)
            if data_el is not None:
                href_el = data_el.find("repo:location", NS)
                href = href_el.get("href", "") if href_el is not None else ""
                checksum_el = data_el.find("repo:checksum", NS)
                sha256 = checksum_el.text if checksum_el is not None else ""
                result[dtype] = (href, sha256)
        if "primary" not in result:
            raise ValueError("No primary data element found in repomd.xml")
        return result

    @staticmethod
    def _parse_rpm_rich_requires(expr: str) -> list[list[Dependency]] | None:
        """Parse an RPM rich dependency expression into AND/OR groups.

        RPM rich deps use boolean expressions wrapped in parentheses:

        * ``(pkgA >= 1.0 or pkgB >= 2.0)`` → OR alternatives in one group
        * ``(pkgA and pkgB)`` → separate AND groups
        * ``(pkgA if pkgB)`` → conditional, both required (treated as AND)

        Returns ``None`` when *expr* is a plain dependency name, not a
        rich expression.  Version constraints within each clause are
        stripped since the resolver does not perform version matching.
        """
        if not (expr.startswith("(") and expr.endswith(")")):
            return None

        inner = expr[1:-1].strip()

        # Must contain at least one boolean operator to be a rich dep
        m = _RICH_DEP_SPLIT.search(inner)
        if not m:
            return None

        op = m.group(0).strip()
        clauses = [c.strip() for c in _RICH_DEP_SPLIT.split(inner) if c.strip()]
        if not clauses:
            return None

        # Extract the bare package name from each clause, dropping any
        # version constraint (e.g. ``python3dist(requests) < 2.11``
        # → ``python3dist(requests)``).
        names: list[str] = []
        for clause in clauses:
            name_part = re.split(
                r"\s+(?:>=|<=|!=|[<>=])\s+", clause, maxsplit=1,
            )[0].strip()
            names.append(name_part)

        if op == "or":
            # OR: a single AND-group with multiple alternatives
            return [[Dependency(name=n) for n in names]]

        # "and" or "if": each clause is individually required
        return [[Dependency(name=n)] for n in names]

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
                            rich = RpmBackend._parse_rpm_rich_requires(dep_name)
                            if rich is not None:
                                depends.extend(rich)
                            else:
                                depends.append([Dependency(name=dep_name)])

                provides_el = format_el.find("rpm-format:provides", NS)
                if provides_el is not None:
                    for entry in provides_el.findall("rpm-format:entry", NS):
                        prov_name = entry.get("name", "")
                        if prov_name:
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
        force_update: bool = False,
    ) -> Dict[str, PackageInfo] | None:
        """Download and parse a single RPM repository's metadata."""
        base_url = repo.url.rstrip("/")
        sanitized = re.sub(r"[^a-zA-Z0-9]", "_", base_url)
        cache_dir = CONFIG_PATH.parent / "sources" / "rpm" / sanitized
        cache_path = cache_dir / "primary.xml.gz"
        fl_cache_path = cache_dir / "filelists.xml.gz"

        source_id = self.build_source_id("rpm", base_url, repo.release, repo.arch or "")

        packages: Dict[str, PackageInfo] | None = None
        repomd_meta: dict[str, tuple[str, str]] | None = None

        # 1-hour cache cooldown – skip HTTP entirely when the cache is fresh
        if not force_update and cache_path.exists():
            age = time.time() - cache_path.stat().st_mtime
            if age < 3600:
                # Check SQLite cache first
                file_sha = hashlib.sha256(cache_path.read_bytes()).hexdigest()
                if self.cache and self.cache.is_fresh(source_id, file_sha):
                    loaded = self.cache.load(source_id)
                    if loaded is not None:
                        packages = loaded
                if packages is None:
                    packages = self._parse_primary(cache_path.read_bytes())
                    if self.cache:
                        self.cache.store(source_id, file_sha, packages)

        # Need to fetch repomd.xml
        if packages is None:
            repomd_url = f"{base_url}/repodata/repomd.xml"
            with httpx.Client(timeout=timeout) as client:
                resp = client.get(repomd_url, follow_redirects=True)
                resp.raise_for_status()
            repomd_meta = self._parse_repomd(resp.text)
            href, expected_sha256 = repomd_meta["primary"]

            # Check cache: if cached file's SHA256 matches, skip download
            if cache_path.exists():
                cached_sha256 = hashlib.sha256(cache_path.read_bytes()).hexdigest()
                if cached_sha256 == expected_sha256:
                    if self.cache and not force_update and self.cache.is_fresh(source_id, expected_sha256):
                        loaded = self.cache.load(source_id)
                        if loaded is not None:
                            packages = loaded
                    if packages is None:
                        packages = self._parse_primary(cache_path.read_bytes())
                        if self.cache:
                            self.cache.store(source_id, expected_sha256, packages)

            # Download primary.xml.gz
            if packages is None:
                primary_url = f"{base_url}/{href}"
                with httpx.Client(timeout=timeout) as client:
                    resp = client.get(primary_url, follow_redirects=True)
                    resp.raise_for_status()

                data = resp.content
                actual_sha256 = hashlib.sha256(data).hexdigest()
                if actual_sha256 != expected_sha256:
                    raise ValueError(
                        f"SHA256 mismatch for {primary_url}: "
                        f"expected {expected_sha256}, got {actual_sha256}"
                    )
                cache_dir.mkdir(parents=True, exist_ok=True)
                cache_path.write_bytes(data)
                packages = self._parse_primary(data)
                if self.cache:
                    self.cache.store(source_id, expected_sha256, packages)

        if packages is None:
            return None

        for pkg in packages.values():
            pkg.base_url = repo.url

        # --- filelists.xml.gz ---
        # Use cached filelists if available and fresh
        if not force_update and fl_cache_path.exists():
            self._filelists_cache_paths.append(fl_cache_path)
        elif repomd_meta and "filelists" in repomd_meta:
            fl_href, fl_expected_sha = repomd_meta["filelists"]
            try:
                fl_url = f"{base_url}/{fl_href}"
                with httpx.Client(timeout=timeout) as client:
                    resp = client.get(fl_url, follow_redirects=True)
                    resp.raise_for_status()
                fl_data = resp.content
                actual_sha = hashlib.sha256(fl_data).hexdigest()
                if not fl_expected_sha or actual_sha == fl_expected_sha:
                    cache_dir.mkdir(parents=True, exist_ok=True)
                    fl_cache_path.write_bytes(fl_data)
                    self._filelists_cache_paths.append(fl_cache_path)
            except Exception:
                pass  # filelists is optional, don't break on failure

        return packages


class DnfBackend(RpmBackend):
    """DNF backend — identical to RPM, but reports ``name == 'dnf'``."""

    @property
    def name(self) -> str:
        return "dnf"
