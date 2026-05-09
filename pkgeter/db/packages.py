"""Download and parse Debian Packages.gz files."""

from __future__ import annotations

import gzip
from pathlib import Path
from typing import Dict

import httpx

from pkgeter.models import PackageInfo, parse_depends_line


def build_packages_url(mirror: str, release: str, arch: str) -> str:
    """Build the URL for Packages.gz on a Debian mirror."""
    mirror = mirror.rstrip("/")
    return f"{mirror}/dists/{release}/main/binary-{arch}/Packages.gz"


def download_packages_gz(url: str, timeout: int = 60) -> bytes:
    """Download Packages.gz from a Debian mirror."""
    with httpx.Client(timeout=timeout) as client:
        resp = client.get(url, follow_redirects=True)
        resp.raise_for_status()
        return resp.content


def parse_packages_file(data: bytes) -> Dict[str, PackageInfo]:
    """Parse Packages.gz (or uncompressed Packages) content into a dict keyed by package name."""
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
        info = _parse_stanza(stanza)
        if info and info.package:
            packages[info.package] = info
    return packages


def _parse_stanza(text: str) -> PackageInfo | None:
    """Parse a single package stanza from Packages file."""
    text = text.strip()
    pkg = PackageInfo(package="", version="")

    current_key = None
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


def download_package_db(mirror: str, release: str, arch: str) -> Dict[str, PackageInfo]:
    """High-level: download Packages.gz and parse into structured data."""
    url = build_packages_url(mirror, release, arch)
    raw = download_packages_gz(url)
    return parse_packages_file(raw)
