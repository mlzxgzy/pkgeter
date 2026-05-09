"""Abstract base class for output formats."""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Dict


class OutputFormat(ABC):
    """Plugable output format for processed .deb files."""

    name: str = ""
    description: str = ""

    @abstractmethod
    def execute(
        self,
        deb_files: Dict[str, Path],
        install_script: str,
        release: str,
        arch: str,
        output_dir: Path,
    ) -> Path:
        """Process downloaded .deb files and return the output path.

        Args:
            deb_files: dict of package_name -> local Path to .deb
            install_script: shell script content for offline installation
            release: Debian release name (e.g., "bookworm")
            arch: architecture (e.g., "amd64")
            output_dir: directory to write output to

        Returns:
            Path to the created output directory
        """
        ...
