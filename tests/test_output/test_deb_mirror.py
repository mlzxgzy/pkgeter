"""Tests for Debian local mirror output format."""

import gzip
from pathlib import Path

from pkgeter.models import PackageInfo
from pkgeter.output.deb_mirror import DebMirrorOutput


def _make_fake_deb(path: Path, content: str = "deb-data") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    return path


def test_deb_mirror_basic_structure(tmp_path):
    """DebMirrorOutput creates debs/, dists/, local.sources, install.sh."""
    src = tmp_path / "src"
    src.mkdir()
    deb_path = _make_fake_deb(src / "vsftpd_3.0.5-3_amd64.deb")

    output = DebMirrorOutput()
    result = output.execute(
        deb_files={"vsftpd": deb_path},
        install_script="", release="bookworm", arch="amd64",
        output_dir=tmp_path / "output",
        packages=["vsftpd"],
        pkg_info={"vsftpd": PackageInfo(package="vsftpd", version="3.0.5-3",
                                         arch="amd64", filename="", sha256="abc", size=123)},
    )
    assert (result / "debs").is_dir()
    assert (result / "dists").is_dir()
    assert (result / "dists" / "bookworm").is_dir()
    assert (result / "dists" / "bookworm" / "main" / "binary-amd64" / "Packages.gz").exists()
    assert (result / "dists" / "bookworm" / "main" / "binary-amd64" / "Release").exists()
    assert (result / "local.sources").exists()
    assert (result / "install.sh").exists()


def test_deb_mirror_deb_files_copied(tmp_path):
    """.deb files are copied to debs/ subdirectory."""
    src = tmp_path / "src"
    src.mkdir()
    deb_path = _make_fake_deb(src / "pkg_1.0-1_amd64.deb", content="deb-content")

    output = DebMirrorOutput()
    result = output.execute(
        deb_files={"pkg": deb_path},
        install_script="", release="bookworm", arch="amd64",
        output_dir=tmp_path / "output", packages=["pkg"],
    )
    copied = list((result / "debs").rglob("*.deb"))
    assert len(copied) == 1
    assert copied[0].read_text() == "deb-content"


def test_deb_mirror_local_sources(tmp_path):
    """local.sources points to the output root with dists/ layout."""
    src = tmp_path / "src"
    src.mkdir()
    deb_path = _make_fake_deb(src / "pkg_1.0-1_amd64.deb")

    output = DebMirrorOutput()
    result = output.execute(
        deb_files={"pkg": deb_path},
        install_script="", release="bookworm", arch="amd64",
        output_dir=tmp_path / "output", packages=["pkg"],
    )
    sources = (result / "local.sources").read_text()
    assert "[trusted=yes]" in sources
    assert "file:" in sources
    assert "bookworm" in sources
    assert "main" in sources


def test_deb_mirror_install_script(tmp_path):
    """install.sh uses apt-get -o Dir::Etc::sourcelist."""
    src = tmp_path / "src"
    src.mkdir()
    deb_path = _make_fake_deb(src / "pkg_1.0-1_amd64.deb")

    output = DebMirrorOutput()
    result = output.execute(
        deb_files={"pkg": deb_path},
        install_script="", release="bookworm", arch="amd64",
        output_dir=tmp_path / "output", packages=["pkg"],
    )
    script = (result / "install.sh").read_text()
    assert "#!/bin/bash" in script
    assert "sudo apt-get" in script
    assert "Dir::Etc::sourcelist" in script
    assert "local.sources" in script
    assert "install pkg" in script


def test_deb_mirror_packages_gz_content(tmp_path):
    """Packages.gz contains valid package stanzas."""
    src = tmp_path / "src"
    src.mkdir()
    deb_path = _make_fake_deb(src / "pkg_1.0-1_amd64.deb")

    output = DebMirrorOutput()
    result = output.execute(
        deb_files={"pkg": deb_path},
        install_script="", release="bookworm", arch="amd64",
        output_dir=tmp_path / "output", packages=["pkg"],
        pkg_info={"pkg": PackageInfo(package="pkg", version="1.0-1",
                                      arch="amd64", filename="", sha256="abc", size=99)},
    )
    pkg_gz = result / "dists" / "bookworm" / "main" / "binary-amd64" / "Packages.gz"
    raw = gzip.decompress(pkg_gz.read_bytes()).decode()
    assert "Package: pkg" in raw
    assert "Version: 1.0-1" in raw


def test_deb_mirror_release_content(tmp_path):
    """Release file contains correct codename and arch."""
    src = tmp_path / "src"
    src.mkdir()
    deb_path = _make_fake_deb(src / "pkg_1.0-1_amd64.deb")

    output = DebMirrorOutput()
    result = output.execute(
        deb_files={"pkg": deb_path},
        install_script="", release="bookworm", arch="amd64",
        output_dir=tmp_path / "output", packages=["pkg"],
    )
    release = result / "dists" / "bookworm" / "main" / "binary-amd64" / "Release"
    content = release.read_text()
    assert "Codename: bookworm" in content
    assert "Architectures: amd64" in content


def test_deb_mirror_empty_packages(tmp_path):
    """Empty package dict still produces valid mirror structure."""
    output = DebMirrorOutput()
    result = output.execute(
        deb_files={}, install_script="", release="bookworm", arch="amd64",
        output_dir=tmp_path / "output", packages=[],
    )
    assert (result / "dists" / "bookworm" / "main" / "binary-amd64" / "Packages.gz").exists()
    assert (result / "install.sh").exists()
