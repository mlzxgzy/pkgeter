"""Pure-Python apt repository metadata generation — no external tools required."""

from __future__ import annotations

import gzip
import time
from typing import Dict

from pkgeter.models import PackageInfo


def _format_stanza(pkg: PackageInfo) -> str:
    """Format a single PackageInfo into a Debian control stanza."""
    lines = [
        f"Package: {pkg.package}",
        f"Version: {pkg.version}",
        f"Architecture: {pkg.arch}",
        f"Filename: {pkg.filename}",
        f"SHA256: {pkg.sha256}",
        f"Size: {pkg.size}",
    ]
    if pkg.description:
        lines.append(f"Description: {pkg.description}")
    if pkg.depends:
        dep_strs = []
        for group in pkg.depends:
            dep_strs.append(" | ".join(str(d) for d in group))
        lines.append(f"Depends: {', '.join(dep_strs)}")
    if pkg.provides:
        lines.append(f"Provides: {', '.join(pkg.provides)}")
    return "\n".join(lines)


def build_packages_gz(packages: Dict[str, PackageInfo]) -> bytes:
    """Build gzip-compressed Packages.gz from PackageInfo dict.

    Returns gzip-compressed bytes with mtime=0 for deterministic output.
    """
    stanzas = [_format_stanza(pkg) for pkg in packages.values()]
    text = "\n\n".join(stanzas) + "\n\n" if stanzas else ""
    return gzip.compress(text.encode("utf-8"), mtime=0)


def build_release(
    codename: str,
    arch: str,
    packages_gz_sha256: str,
    packages_gz_size: int,
) -> str:
    """Build a Release file for a single-component, single-arch repo."""
    date_str = time.strftime("%a, %d %b %Y %H:%M:%S UTC", time.gmtime())
    lines = [
        f"Codename: {codename}",
        f"Architectures: {arch}",
        "Components: main",
        f"Date: {date_str}",
        "SHA256:",
        f" {packages_gz_sha256} {packages_gz_size} main/binary-{arch}/Packages.gz",
        "",
    ]
    return "\n".join(lines)
