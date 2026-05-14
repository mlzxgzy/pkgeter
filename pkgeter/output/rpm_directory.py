"""Output format: flat .rpm directory with install script."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Dict

from pkgeter.output.base import OutputFormat


class RpmDirectoryOutput(OutputFormat):
    name = "rpm"
    description = "Output .rpm files to a directory"

    def execute(
        self,
        deb_files: Dict[str, Path],
        install_script: str,
        release: str,
        arch: str,
        output_dir: Path,
    ) -> Path:
        out = output_dir / "rpms"
        out.mkdir(parents=True, exist_ok=True)
        for _pkg_name, src_path in deb_files.items():
            shutil.copy2(src_path, out / src_path.name)
        if install_script:
            script_path = out / "install.sh"
            script_path.write_bytes(install_script.encode("utf-8"))
            script_path.chmod(0o755)
        return out
