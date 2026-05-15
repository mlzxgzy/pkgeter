"""Output format: local RPM/yum/DNF mirror with self-generated repodata."""

from __future__ import annotations

import hashlib
import shutil
from pathlib import Path
from typing import Dict, List, Optional

from pkgeter.models import Dependency, PackageInfo
from pkgeter.output.base import OutputFormat
from pkgeter.output.repomd_gen import build_primary_xml, build_repomd_xml


class RpmMirrorOutputBase(OutputFormat):
    """Base class for RPM mirror outputs (shared by yum3 and dnf variants)."""
    name = "rpm-mirror"
    description = "Output .rpm files to a local yum/dnf mirror with repodata"

    @property
    def package_manager(self) -> str:
        return "yum"

    @property
    def use_repofrompath(self) -> bool:
        return False

    def _generate_install_script(self, script_dir: str, packages: list[str]) -> str:
        pkg_list = " ".join(packages)
        sudo_block = (
            '# Auto-detect sudo availability\n'
            'if ! command -v sudo >/dev/null 2>&1; then\n'
            '    sudo() { "$@"; }\n'
            'fi\n'
            '\n'
        )
        if self.use_repofrompath:
            return (
                "#!/bin/bash\n"
                "# pkgeter - Offline DNF package installation\n"
                f"# Target packages: {pkg_list}\n"
                "#\n"
                f"{sudo_block}"
                'SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"\n'
                'cd "$SCRIPT_DIR"\n'
                f'sudo dnf --repofrompath=local,file://"$SCRIPT_DIR" --nogpgcheck install {pkg_list}\n'
            )
        return (
            "#!/bin/bash\n"
            "# pkgeter - Offline YUM package installation\n"
            f"# Target packages: {pkg_list}\n"
            "#\n"
            f"{sudo_block}"
            'SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"\n'
            'cd "$SCRIPT_DIR"\n'
            # Replace placeholder with actual path, then run yum
            'sed -i "s|/REPLACE_ME|$SCRIPT_DIR|g" local.repo\n'
            f'sudo yum --config="$SCRIPT_DIR/yum.conf" --nogpgcheck install {pkg_list}\n'
        )

    @staticmethod
    def _clean_repodata_depends(depends: list[list[Dependency]]) -> list[list[Dependency]]:
        """Remove file-path and RPM-internal requires from repodata entries.

        File-path dependencies (e.g. ``/usr/bin/perl``, ``/bin/sh``) are
        assumed to be provided by the base system and cannot be resolved
        against the local repository's metadata.  Removing them from the
        generated ``primary.xml`` prevents DNF from failing on "nothing
        provides /usr/bin/perl" at install time.
        """
        result: list[list[Dependency]] = []
        for dep_group in depends:
            cleaned = [d for d in dep_group
                       if not d.name.startswith("/")
                       and not d.name.startswith("rpmlib(")
                       and d.name != "rtld(GNU_HASH)"]
            if cleaned:
                result.append(cleaned)
        return result

    def _generate_yum_conf(self) -> str:
        return "[main]\ngpgcheck=0\nreposdir=.\n"

    def _generate_local_repo(self) -> str:
        return (
            "[local]\n"
            "name=Local Repository\n"
            "baseurl=file:///REPLACE_ME\n"
            "enabled=1\ngpgcheck=0\n"
        )

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

        # 1. Copy .rpm files to rpms/
        rpms_dir = output_dir / "rpms"
        rpms_dir.mkdir(parents=True, exist_ok=True)
        for src_path in deb_files.values():
            shutil.copy2(src_path, rpms_dir / src_path.name)

        # 2. Build metadata dict for repodata generation
        meta_pkgs: Dict[str, PackageInfo] = {}
        for pkg_name, src_path in deb_files.items():
            file_data = (rpms_dir / src_path.name).read_bytes()
            actual_sha = hashlib.sha256(file_data).hexdigest()
            file_size = len(file_data)
            if pkg_info and pkg_name in pkg_info:
                src = pkg_info[pkg_name]
                meta_pkgs[pkg_name] = PackageInfo(
                    package=src.package,
                    version=src.version,
                    arch=src.arch or "noarch",
                    filename=f"rpms/{src_path.name}",
                    sha256=actual_sha,
                    size=file_size,
                    depends=self._clean_repodata_depends(src.depends),
                    provides=src.provides,
                )
            else:
                meta_pkgs[pkg_name] = PackageInfo(
                    package=pkg_name, version="0:0-0",
                    arch="noarch", filename=f"rpms/{src_path.name}",
                    sha256=actual_sha, size=file_size,
                )

        # 3. Generate repodata
        repodata_dir = output_dir / "repodata"
        repodata_dir.mkdir(parents=True, exist_ok=True)
        primary_gz = build_primary_xml(meta_pkgs)
        (repodata_dir / "primary.xml.gz").write_bytes(primary_gz)
        (repodata_dir / "repomd.xml").write_text(
            build_repomd_xml(primary_gz, output_dir), newline="\n")

        # 4. Write yum.conf + local.repo (with REPLACE_ME placeholder)
        (output_dir / "yum.conf").write_text(self._generate_yum_conf(), newline="\n")
        (output_dir / "local.repo").write_text(self._generate_local_repo(), newline="\n")

        # 5. Write install.sh
        script_path = output_dir / "install.sh"
        script_path.write_text(
            self._generate_install_script(str(output_dir.resolve()), packages),
            newline="\n")
        script_path.chmod(0o755)

        return output_dir


class RpmMirrorOutput(RpmMirrorOutputBase):
    """RPM mirror output for yum3 (uses --config + yum.conf)."""
    name = "rpm-mirror"
    @property
    def package_manager(self) -> str:
        return "yum"
    @property
    def use_repofrompath(self) -> bool:
        return False


class DnfMirrorOutput(RpmMirrorOutputBase):
    """RPM mirror output for dnf (uses --repofrompath, no yum.conf)."""
    name = "dnf-mirror"
    @property
    def package_manager(self) -> str:
        return "dnf"
    @property
    def use_repofrompath(self) -> bool:
        return True

    def execute(self, **kwargs) -> Path:
        """DNF variant: skip yum.conf generation."""
        result = super().execute(**kwargs)
        yum_conf = kwargs["output_dir"] / "yum.conf"
        if yum_conf.exists():
            yum_conf.unlink()
        return result
