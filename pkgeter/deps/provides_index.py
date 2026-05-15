"""Reverse provides index — O(1) lookup from capability/file to provider packages.

Combines two data sources:

* **primary.xml provides** — sonames (e.g. ``libunwind.so.8()(64bit)``),
  explicit ``Provides:`` entries, and package-name self-provides.
* **filelists.xml.gz** — every file path a package installs
  (e.g. ``/usr/lib64/libunwind.so.8``).

Together these replicate what ``yum provides`` can query.
"""

from __future__ import annotations

import gzip
import xml.etree.ElementTree as ET
from typing import Dict, List

from pkgeter.models import PackageInfo

# filelists.xml.gz namespace
_FL_NS = {"fl": "http://linux.duke.edu/metadata/filelists"}


class ProvidesIndex:
    """Reverse mapping: capability / file path → list of provider package names."""

    def __init__(self) -> None:
        self._index: Dict[str, List[str]] = {}

    # ------------------------------------------------------------------
    # Construction helpers
    # ------------------------------------------------------------------

    def build_from_packages(self, packages: Dict[str, PackageInfo]) -> None:
        """Populate the index from ``PackageInfo.provides`` fields.

        This covers soname provides and explicit ``Provides:`` entries
        that are already available from ``primary.xml.gz``.
        """
        for name, info in packages.items():
            for prov in info.provides:
                self._index.setdefault(prov, []).append(name)

    def add_filelists(self, gz_data: bytes) -> None:
        """Extend the index with file-path → package mappings from
        ``filelists.xml.gz``.
        """
        raw = gzip.decompress(gz_data)
        root = ET.fromstring(raw)

        for pkg_el in root.findall("fl:package", _FL_NS):
            pkg_name = pkg_el.get("name", "")
            if not pkg_name:
                continue
            for file_el in pkg_el.findall("fl:file", _FL_NS):
                path = file_el.text
                if path:
                    self._index.setdefault(path, []).append(pkg_name)

    # ------------------------------------------------------------------
    # Query
    # ------------------------------------------------------------------

    def find(self, name: str) -> List[str]:
        """Return sorted list of packages that provide *name*, or ``[]``."""
        providers = self._index.get(name)
        if providers is None:
            return []
        return sorted(set(providers))

    def __len__(self) -> int:
        return len(self._index)

    def __contains__(self, name: str) -> bool:
        return name in self._index
