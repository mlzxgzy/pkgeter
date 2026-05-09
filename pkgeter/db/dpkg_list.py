"""Parse dpkg -l output to extract installed package names."""

from pathlib import Path
from typing import Set


def parse_dpkg_list(text: str) -> Set[str]:
    """Parse dpkg -l output, return set of installed package names.

    Handles the standard dpkg -l column-header format with status flags
    (ii, hi, iU).
    """
    packages: Set[str] = set()
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        # Skip header lines
        if (
            line.startswith("Desired=")
            or line.startswith("| Status=")
            or line.startswith("|/ Err?")
            or line.startswith("+++-")
            or line.startswith("||/")
        ):
            continue
        # Status line: "ii  package_name  version  arch  description"
        if len(line) > 3 and line[0:2] in ("ii", "hi", "iU"):
            parts = line.split()
            if len(parts) >= 2:
                packages.add(parts[1])
    return packages


def parse_dpkg_list_file(path: Path) -> Set[str]:
    """Read and parse a dpkg -l output file."""
    return parse_dpkg_list(path.read_text(encoding="utf-8", errors="replace"))
