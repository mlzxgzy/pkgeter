"""Pure-Python RPM repodata generation — no external tools required."""

from __future__ import annotations

import gzip
import hashlib
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Dict

from pkgeter.models import PackageInfo

_REPO_NS = "http://linux.duke.edu/metadata/repo"
_RPM_NS = "http://linux.duke.edu/metadata/common"
_RPM_FORMAT_NS = "http://linux.duke.edu/metadata/rpm"

ET.register_namespace("", _RPM_NS)
ET.register_namespace("rpm", _RPM_FORMAT_NS)


def _parse_version(version: str) -> tuple[str, str, str]:
    """Split '1:1.1.1k-7.el8_9' into (epoch, ver, rel).

    RPM epoch-default = '0' when no colon present.
    """
    epoch = "0"
    rest = version
    if ":" in version:
        epoch, rest = version.split(":", 1)
    if "-" in rest:
        ver, rel = rest.rsplit("-", 1)
    else:
        ver = rest
        rel = ""
    return epoch, ver, rel


def _make_sub_element(
    parent: ET.Element,
    tag: str,
    ns: str,
    text: str | None = None,
    attrib: dict | None = None,
) -> ET.Element:
    """Create a namespaced sub-element."""
    el = ET.SubElement(parent, f"{{{ns}}}{tag}")
    if attrib:
        el.attrib.update(attrib)
    if text is not None:
        el.text = text
    return el


def build_primary_xml(packages: Dict[str, PackageInfo]) -> bytes:
    """Build gzip-compressed primary.xml.gz from PackageInfo dict.

    Returns gzip-compressed bytes with mtime=0 for deterministic output.
    """
    root = ET.Element(f"{{{_RPM_NS}}}metadata")
    root.set("packages", str(len(packages)))

    for pkg in packages.values():
        pkg_el = _make_sub_element(root, "package", _RPM_NS, attrib={"type": "rpm"})
        _make_sub_element(pkg_el, "name", _RPM_NS, pkg.package)
        _make_sub_element(pkg_el, "arch", _RPM_NS, pkg.arch or "noarch")

        epoch, ver, rel = _parse_version(pkg.version)
        _make_sub_element(
            pkg_el,
            "version",
            _RPM_NS,
            attrib={"epoch": epoch, "ver": ver, "rel": rel},
        )
        _make_sub_element(
            pkg_el,
            "checksum",
            _RPM_NS,
            pkg.sha256,
            attrib={"type": "sha256", "pkgid": "YES"},
        )
        _make_sub_element(
            pkg_el,
            "location",
            _RPM_NS,
            attrib={"href": pkg.filename},
        )

        now = str(int(time.time()))
        _make_sub_element(
            pkg_el, "time", _RPM_NS, attrib={"file": now, "build": now}
        )
        _make_sub_element(
            pkg_el,
            "size",
            _RPM_NS,
            attrib={
                "package": str(pkg.size),
                "installed": "0",
                "archive": "0",
            },
        )

        fmt_el = _make_sub_element(pkg_el, "format", _RPM_NS)
        if pkg.depends:
            requires_el = _make_sub_element(fmt_el, "requires", _RPM_FORMAT_NS)
            for dep_group in pkg.depends:
                for dep in dep_group:
                    req_attrib: dict = {"name": dep.name}
                    if dep.version_operator:
                        req_attrib["flags"] = dep.version_operator
                    if dep.version:
                        req_attrib["ver"] = dep.version
                    _make_sub_element(
                        requires_el, "entry", _RPM_FORMAT_NS, attrib=req_attrib
                    )
        if pkg.provides:
            provides_el = _make_sub_element(fmt_el, "provides", _RPM_FORMAT_NS)
            for prov_name in pkg.provides:
                _make_sub_element(
                    provides_el, "entry", _RPM_FORMAT_NS, attrib={"name": prov_name}
                )

    raw_xml = ET.tostring(root, encoding="utf-8", xml_declaration=True)
    return gzip.compress(raw_xml, mtime=0)


def build_repomd_xml(primary_gz_bytes: bytes, pkg_dir: Path) -> str:
    """Build repomd.xml string. Validates primary.xml.gz exists on disk."""
    primary_path = pkg_dir / "repodata" / "primary.xml.gz"
    if not primary_path.exists():
        raise FileNotFoundError(f"primary.xml.gz not found at {primary_path}")

    primary_sha256 = hashlib.sha256(primary_gz_bytes).hexdigest()
    primary_size = len(primary_gz_bytes)
    open_data = gzip.decompress(primary_gz_bytes)
    open_size = len(open_data)
    now = str(int(time.time()))

    root = ET.Element(f"{{{_REPO_NS}}}repomd")
    root.set("xmlns", _REPO_NS)

    data_el = _make_sub_element(root, "data", _REPO_NS, attrib={"type": "primary"})
    _make_sub_element(
        data_el,
        "location",
        _REPO_NS,
        attrib={"href": "repodata/primary.xml.gz"},
    )
    _make_sub_element(
        data_el,
        "checksum",
        _REPO_NS,
        primary_sha256,
        attrib={"type": "sha256"},
    )
    _make_sub_element(data_el, "timestamp", _REPO_NS, now)
    _make_sub_element(data_el, "open-size", _REPO_NS, str(open_size))
    _make_sub_element(data_el, "size", _REPO_NS, str(primary_size))

    return ET.tostring(root, encoding="unicode", xml_declaration=True)
