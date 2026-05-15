"""Output format: local Debian/APT mirror with self-generated metadata."""

from __future__ import annotations

import hashlib
import shutil
from pathlib import Path
from typing import Dict, Optional

from pkgeter.models import PackageInfo
from pkgeter.output.base import OutputFormat
from pkgeter.output.apt_repo_gen import build_packages_gz, build_release


class DebMirrorOutput(OutputFormat):
    """Local apt mirror output with dists/ layout and self-generated metadata."""
    name = "deb-mirror"
    description = "Output .deb files to a local apt mirror with dists/ layout"

    def _generate_install_script(self, script_dir: str, packages: list[str]) -> str:
        pkg_list = " ".join(packages)
        sudo_block = (
            '# Auto-detect sudo availability\n'
            'if ! command -v sudo >/dev/null 2>&1; then\n'
            '    sudo() { "$@"; }\n'
            'fi\n'
            '\n'
        )
        return (
            "#!/bin/bash\n"
            "# pkgeter - Offline APT package installation\n"
            f"# Target packages: {pkg_list}\n"
            "#\n"
            f"{sudo_block}"
            'SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"\n'
            'cd "$SCRIPT_DIR"\n'
            'sudo apt-get \\\n'
            '  -o Dir::Etc::sourcelist="$SCRIPT_DIR/local.sources" \\\n'
            '  -o Dir::Etc::sourceparts=/dev/null \\\n'
            '  -o Acquire::AllowInsecureRepositories=yes \\\n'
            '  -o APT::Get::List-Cleanup="0" \\\n'
            '  update\n'
            'sudo apt-get \\\n'
            '  -o Dir::Etc::sourcelist="$SCRIPT_DIR/local.sources" \\\n'
            '  -o Dir::Etc::sourceparts=/dev/null \\\n'
            '  -o APT::Get::List-Cleanup="0" \\\n'
            f'  install {pkg_list}\n'
        )

    def _generate_local_sources(self, base_dir: str, release: str) -> str:
        """Generate a local sources file entry with Windows-path-safe file: URL."""
        # Use as_posix() for Windows compatibility (file:// URLs need forward slashes)
        base = base_dir.replace("\\", "/")
        return f"deb [trusted=yes] file:{base} {release} main\n"

    def execute(
        self,
        deb_files: Dict[str, Path],
        install_script: str,
        release: str,
        arch: str,
        output_dir: Path,
        packages: list[str] | None = None,
        pkg_info: Dict[str, PackageInfo] | None = None,
    ) -> Path:
        if packages is None:
            packages = list(deb_files.keys())

        # 1. Copy .deb files to debs/
        debs_dir = output_dir / "debs"
        debs_dir.mkdir(parents=True, exist_ok=True)
        for src_path in deb_files.values():
            shutil.copy2(src_path, debs_dir / src_path.name)

        # 2. Build metadata dict for Packages.gz
        meta_pkgs: Dict[str, PackageInfo] = {}
        for pkg_name, src_path in deb_files.items():
            file_data = (debs_dir / src_path.name).read_bytes()
            actual_sha = hashlib.sha256(file_data).hexdigest()
            file_size = len(file_data)
            if pkg_info and pkg_name in pkg_info:
                src = pkg_info[pkg_name]
                meta_pkgs[pkg_name] = PackageInfo(
                    package=src.package,
                    version=src.version,
                    arch=src.arch or arch,
                    filename=f"debs/{src_path.name}",
                    sha256=actual_sha,
                    size=file_size,
                    depends=src.depends,
                    provides=src.provides,
                    description=src.description,
                )
            else:
                meta_pkgs[pkg_name] = PackageInfo(
                    package=pkg_name, version="0:0-0",
                    arch=arch, filename=f"debs/{src_path.name}",
                    sha256=actual_sha, size=file_size,
                )

        # 3. Generate dists/ layout
        binary_dir = output_dir / "dists" / release / "main" / f"binary-{arch}"
        binary_dir.mkdir(parents=True, exist_ok=True)

        packages_gz_data = build_packages_gz(meta_pkgs)
        packages_gz_sha = hashlib.sha256(packages_gz_data).hexdigest()
        packages_gz_size = len(packages_gz_data)

        (binary_dir / "Packages.gz").write_bytes(packages_gz_data)
        (binary_dir / "Release").write_text(build_release(
            codename=release, arch=arch,
            packages_gz_sha256=packages_gz_sha,
            packages_gz_size=packages_gz_size,
        ), newline="\n")

        # 4. Write local.sources
        output_root = str(output_dir.resolve())
        (output_dir / "local.sources").write_text(
            self._generate_local_sources(output_root, release), newline="\n")

        # 5. Write install.sh
        script_path = output_dir / "install.sh"
        script_path.write_text(
            self._generate_install_script(str(output_dir.resolve()), packages),
            newline="\n")
        script_path.chmod(0o755)

        return output_dir
