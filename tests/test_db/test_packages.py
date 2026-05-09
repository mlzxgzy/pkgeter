"""Tests for Packages.gz parsing."""

import gzip
from pathlib import Path

from pkgeter.db.packages import (
    build_packages_url,
    parse_packages_file,
    _parse_stanza,
)


DATA_DIR = Path(__file__).parent.parent / "data"


def test_build_packages_url():
    url = build_packages_url("https://deb.debian.org/debian", "bookworm", "amd64")
    assert url == "https://deb.debian.org/debian/dists/bookworm/main/binary-amd64/Packages.gz"


def test_parse_stanza_simple():
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
    info = _parse_stanza(text)
    assert info is not None
    assert info.package == "vsftpd"
    assert info.version == "3.0.5-3"
    assert info.arch == "amd64"
    assert len(info.depends) == 2
    assert info.provides == ["ftp-server"]
    assert info.filename == "pool/main/v/vsftpd/vsftpd_3.0.5-3_amd64.deb"
    assert info.size == 204800
    assert info.description == "lightweight FTP server"


def test_parse_packages_file():
    fixture = DATA_DIR / "sample_packages.gz"
    raw = fixture.read_bytes()
    pkgs = parse_packages_file(raw)
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


def test_parse_empty_stanza():
    assert _parse_stanza("") is None
