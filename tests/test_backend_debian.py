"""Tests for :mod:`pkgeter.backend.debian`."""

from pathlib import Path

from pkgeter.backend.debian import DebianBackend
from pkgeter.models import PackageInfo

DATA_DIR = Path(__file__).parent / "data"


def test_backend_name():
    """DebianBackend.name returns ``'debian'``."""
    assert DebianBackend().name == "debian"


def test_parse_deb_stanza_simple():
    """A single Debian stanza is parsed into a ``PackageInfo``."""
    text = """\
Package: vsftpd
Version: 3.0.5-3
Architecture: amd64
Depends: libc6 (>= 2.34), libssl3 (>= 3.0.0)
Provides: ftp-server
Filename: pool/main/v/vsftpd/vsftpd_3.0.5-3_amd64.deb
SHA256: b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1
Size: 204800
Description: lightweight FTP server
"""
    info = DebianBackend._parse_deb_stanza(text)
    assert info is not None
    assert info.package == "vsftpd"
    assert info.version == "3.0.5-3"
    assert info.arch == "amd64"
    assert len(info.depends) == 2
    assert info.depends[1][0].name == "libssl3"
    assert info.provides == ["ftp-server"]
    assert info.filename == "pool/main/v/vsftpd/vsftpd_3.0.5-3_amd64.deb"
    assert info.size == 204800
    assert info.description == "lightweight FTP server"


def test_parse_deb_stanza_empty():
    """An empty or blank stanza returns ``None``."""
    assert DebianBackend._parse_deb_stanza("") is None
    assert DebianBackend._parse_deb_stanza("   ") is None
    assert DebianBackend._parse_deb_stanza("\n\n") is None


def test_parse_packages_gz():
    """``_parse_packages_gz`` correctly parses the sample ``.gz`` fixture."""
    fixture = DATA_DIR / "sample_packages.gz"
    raw = fixture.read_bytes()
    pkgs = DebianBackend._parse_packages_gz(raw)

    assert len(pkgs) == 4
    assert "vsftpd" in pkgs
    assert "libc6" in pkgs
    assert "libssl3" in pkgs
    assert "zlib1g" in pkgs

    vsftpd = pkgs["vsftpd"]
    assert vsftpd.version == "3.0.5-3"
    assert vsftpd.provides == ["ftp-server"]
    assert len(vsftpd.depends) == 2
    assert vsftpd.depends[1][0].name == "libssl3"


def test_parse_packages_gz_uncompressed():
    """``_parse_packages_gz`` also handles already-decompressed data."""
    fixture = DATA_DIR / "sample_packages.gz"
    raw = fixture.read_bytes()

    # Decompress first, then feed raw text
    import gzip
    decompressed = gzip.decompress(raw)
    pkgs = DebianBackend._parse_packages_gz(decompressed)

    assert len(pkgs) == 4
    assert "vsftpd" in pkgs


def test_build_download_url():
    """``build_download_url`` combines base URL with the package filename."""
    backend = DebianBackend()
    pkg = PackageInfo(
        package="vsftpd",
        version="3.0.5-3",
        filename="pool/main/v/vsftpd/vsftpd_3.0.5-3_amd64.deb",
    )
    url = backend.build_download_url("https://deb.debian.org/debian", pkg)
    assert url == (
        "https://deb.debian.org/debian"
        "/pool/main/v/vsftpd/vsftpd_3.0.5-3_amd64.deb"
    )


def test_build_download_url_trailing_slash():
    """Trailing slash on the base URL is handled gracefully."""
    backend = DebianBackend()
    pkg = PackageInfo(
        package="vsftpd",
        version="3.0.5-3",
        filename="pool/main/v/vsftpd/vsftpd_3.0.5-3_amd64.deb",
    )
    url = backend.build_download_url("https://deb.debian.org/debian/", pkg)
    assert url == (
        "https://deb.debian.org/debian"
        "/pool/main/v/vsftpd/vsftpd_3.0.5-3_amd64.deb"
    )


def test_generate_install_script_basic():
    """Generated script contains ``sudo dpkg -i`` commands for each file."""
    script = DebianBackend.generate_install_script(
        ["vsftpd_3.0.5-3_amd64.deb", "libc6_2.36-9_amd64.deb"],
        ["vsftpd"],
    )
    assert "#!/bin/bash" in script
    assert "sudo dpkg -i" in script
    assert "vsftpd_3.0.5-3_amd64.deb" in script
    assert "libc6_2.36-9_amd64.deb" in script
    assert "vsftpd" in script  # target package shown in header


def test_generate_install_script_single_file():
    """Script works with a single file and multiple target names in header."""
    script = DebianBackend.generate_install_script(
        ["curl_7.88.1_amd64.deb"],
        ["curl", "libcurl4"],
    )
    assert "curl_7.88.1_amd64.deb" in script
    assert "Target packages: curl libcurl4" in script
    # Exactly one dpkg -i line
    assert script.count("sudo dpkg -i") == 1


def test_generate_install_script_empty():
    """Script with no files still produces valid shell output."""
    script = DebianBackend.generate_install_script([], [])
    assert "#!/bin/bash" in script
    assert "sudo dpkg -i" not in script


def test_download_package_db_empty_repos():
    """Empty repos list produces an empty package database."""
    backend = DebianBackend()
    db = backend.download_package_db(repos=[], arch="amd64")
    assert db == {}


def test_merge_package_dbs():
    """``merge_package_dbs`` combines multiple DBs, later overriding earlier."""
    backend = DebianBackend()
    db1 = {"a": PackageInfo(package="a", version="1.0")}
    db2 = {"b": PackageInfo(package="b", version="2.0")}
    merged = backend.merge_package_dbs([db1, db2])
    assert len(merged) == 2
    assert merged["a"].version == "1.0"
    assert merged["b"].version == "2.0"


def test_merge_package_dbs_override():
    """Later repos override earlier ones for the same package name."""
    backend = DebianBackend()
    db1 = {"a": PackageInfo(package="a", version="1.0")}
    db2 = {"a": PackageInfo(package="a", version="2.0")}
    merged = backend.merge_package_dbs([db1, db2])
    assert merged["a"].version == "2.0"
