"""Tests for RPM local mirror output format."""

import gzip
from pathlib import Path

from pkgeter.models import Dependency, PackageInfo
from pkgeter.output.rpm_mirror import RpmMirrorOutput


def _make_fake_rpm(path: Path, name: str = "pkg", content: str = "rpm-data") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    return path


def test_rpm_mirror_basic_structure(tmp_path):
    """RpmMirrorOutput creates rpms/, repodata/, yum.conf, local.repo, install.sh."""
    src = tmp_path / "src"
    src.mkdir()
    fake_rpm = _make_fake_rpm(src / "openssl-1.1.1k-7.el8_9.x86_64.rpm", "openssl")
    pkg_info = {"openssl": PackageInfo(package="openssl", version="1.1.1k-7.el8_9",
                                        arch="x86_64", filename="", sha256="abc", size=8)}

    output = RpmMirrorOutput()
    result = output.execute(
        deb_files={"openssl": fake_rpm},
        install_script="", release="9", arch="x86_64",
        output_dir=tmp_path / "output",
        packages=["openssl"], pkg_info=pkg_info,
    )
    assert (result / "rpms").is_dir()
    assert (result / "repodata").is_dir()
    assert (result / "repodata" / "repomd.xml").exists()
    assert (result / "repodata" / "primary.xml.gz").exists()
    assert (result / "yum.conf").exists()
    assert (result / "local.repo").exists()
    assert (result / "install.sh").exists()


def test_rpm_mirror_rpm_files_copied(tmp_path):
    """RPM files are copied to rpms/ subdirectory."""
    src = tmp_path / "src"
    src.mkdir()
    rpm_path = _make_fake_rpm(src / "openssl.rpm", "openssl", content="rpm-data")

    output = RpmMirrorOutput()
    result = output.execute(
        deb_files={"openssl": rpm_path},
        install_script="", release="9", arch="x86_64",
        output_dir=tmp_path / "output", packages=["openssl"],
    )
    copied = list((result / "rpms").rglob("*.rpm"))
    assert len(copied) == 1
    assert copied[0].read_text() == "rpm-data"


def test_rpm_mirror_install_script_has_sed(tmp_path):
    """install.sh runs sed to replace REPLACE_ME placeholder in local.repo."""
    src = tmp_path / "src"
    src.mkdir()
    rpm_path = _make_fake_rpm(src / "pkg.rpm", "pkg")

    output = RpmMirrorOutput()
    result = output.execute(
        deb_files={"pkg": rpm_path},
        install_script="", release="9", arch="x86_64",
        output_dir=tmp_path / "output", packages=["pkg"],
    )
    script = (result / "install.sh").read_text()
    assert "sed -i" in script
    assert "local.repo" in script


def test_rpm_mirror_install_script_yum3(tmp_path):
    """install.sh uses yum --config for yum3 compatibility."""
    src = tmp_path / "src"
    src.mkdir()
    rpm_path = _make_fake_rpm(src / "pkg.rpm", "pkg")

    output = RpmMirrorOutput()
    result = output.execute(
        deb_files={"pkg": rpm_path},
        install_script="", release="9", arch="x86_64",
        output_dir=tmp_path / "output", packages=["pkg"],
    )
    script = (result / "install.sh").read_text()
    assert "#!/bin/bash" in script
    assert "sudo yum --config" in script
    assert "pkg" in script


def test_rpm_mirror_yum_conf_minimal(tmp_path):
    """yum.conf is minimal with just [main] and reposdir=."""
    src = tmp_path / "src"
    src.mkdir()
    rpm_path = _make_fake_rpm(src / "pkg.rpm", "pkg")

    output = RpmMirrorOutput()
    result = output.execute(
        deb_files={"pkg": rpm_path},
        install_script="", release="9", arch="x86_64",
        output_dir=tmp_path / "output", packages=["pkg"],
    )
    conf = (result / "yum.conf").read_text()
    assert "[main]" in conf
    assert "reposdir=" in conf
    assert "[local]" not in conf


def test_rpm_mirror_local_repo_placeholder(tmp_path):
    """local.repo has [local] section with REPLACE_ME placeholder."""
    src = tmp_path / "src"
    src.mkdir()
    rpm_path = _make_fake_rpm(src / "pkg.rpm", "pkg")

    output = RpmMirrorOutput()
    result = output.execute(
        deb_files={"pkg": rpm_path},
        install_script="", release="9", arch="x86_64",
        output_dir=tmp_path / "output", packages=["pkg"],
    )
    repo = (result / "local.repo").read_text()
    assert "[local]" in repo
    assert "REPLACE_ME" in repo
    assert "baseurl=file:///REPLACE_ME" in repo


def test_rpm_mirror_multiple_packages(tmp_path):
    """Multiple packages all appear in install.sh."""
    src = tmp_path / "src"
    src.mkdir()
    _make_fake_rpm(src / "a.rpm", "a")
    _make_fake_rpm(src / "b.rpm", "b")

    output = RpmMirrorOutput()
    result = output.execute(
        deb_files={"a": src / "a.rpm", "b": src / "b.rpm"},
        install_script="", release="9", arch="x86_64",
        output_dir=tmp_path / "output", packages=["a", "b"],
    )
    script = (result / "install.sh").read_text()
    assert "a" in script and "b" in script


def test_dnf_mirror_install_script(tmp_path):
    """DnfMirrorOutput uses --repofrompath, no yum.conf."""
    from pkgeter.output.rpm_mirror import DnfMirrorOutput
    src = tmp_path / "src"
    src.mkdir()
    rpm_path = _make_fake_rpm(src / "pkg.rpm", "pkg")

    output = DnfMirrorOutput()
    result = output.execute(
        deb_files={"pkg": rpm_path},
        install_script="", release="9", arch="x86_64",
        output_dir=tmp_path / "output", packages=["pkg"],
    )
    script = (result / "install.sh").read_text()
    assert "sudo dnf --repofrompath" in script
    assert "install pkg" in script
    assert not (result / "yum.conf").exists()


def test_rpm_mirror_empty_packages(tmp_path):
    """Empty package dict still produces valid mirror structure."""
    output = RpmMirrorOutput()
    result = output.execute(
        deb_files={}, install_script="", release="9", arch="x86_64",
        output_dir=tmp_path / "output", packages=[],
    )
    assert (result / "repodata").is_dir()
    assert (result / "repodata" / "primary.xml.gz").exists()
    assert (result / "install.sh").exists()
    primary = gzip.decompress((result / "repodata" / "primary.xml.gz").read_bytes())
    assert b'packages="0"' in primary


def test_rpm_mirror_strips_file_path_deps(tmp_path):
    """File-path dependencies (e.g. /usr/bin/perl) are stripped from
    generated primary.xml so DNF doesn't fail resolving them."""
    from pkgeter.output.rpm_mirror import RpmMirrorOutputBase
    # Test the static method directly
    deps = [
        [Dependency("glibc")],
        [Dependency("/usr/bin/perl")],
        [Dependency("rpmlib(CompressedFileNames)")],
    ]
    cleaned = RpmMirrorOutputBase._clean_repodata_depends(deps)
    assert cleaned == [[Dependency("glibc")]]


def test_rpm_mirror_primary_xml_strips_file_paths(tmp_path):
    """Generated primary.xml.gz does not contain file-path requires."""
    src = tmp_path / "src"
    src.mkdir()
    _make_fake_rpm(src / "gd-2.3.0-4.ky10.x86_64.rpm", "gd")
    pkg_info = {
        "gd": PackageInfo(
            package="gd", version="2.3.0-4.ky10", arch="x86_64",
            filename="pool/gd-2.3.0.rpm", sha256="abc", size=8,
            depends=[
                [Dependency("/usr/bin/perl")],
                [Dependency("glibc")],
            ],
            provides=["libgd.so.3()(64bit)"],
        ),
    }
    output = RpmMirrorOutput()
    result = output.execute(
        deb_files={"gd": src / "gd-2.3.0-4.ky10.x86_64.rpm"},
        install_script="", release="ky10", arch="x86_64",
        output_dir=tmp_path / "output", packages=["gd"],
        pkg_info=pkg_info,
    )
    primary = gzip.decompress((result / "repodata" / "primary.xml.gz").read_bytes())
    # Verify: /usr/bin/perl require is REMOVED, glibc require is KEPT
    assert b"/usr/bin/perl" not in primary, \
        "file-path requires should be stripped from primary.xml"
    assert b"glibc" in primary, \
        "package-name requires should be kept in primary.xml"
    # Verify libgd.so.3()(64bit) provide is kept
    assert b"libgd.so.3()(64bit)" in primary, \
        "soname provides should be kept in primary.xml"
