"""Tests for data models."""

from pkgeter.models import (
    Dependency,
    PackageInfo,
    _parse_single_dep,
    parse_depends_line,
    format_package_info,
)


def test_parse_single_dep_simple():
    dep = _parse_single_dep("libc6")
    assert dep is not None
    assert dep.name == "libc6"
    assert dep.version_operator is None


def test_parse_single_dep_with_version():
    dep = _parse_single_dep("libc6 (>= 2.34)")
    assert dep is not None
    assert dep.name == "libc6"
    assert dep.version_operator == ">="
    assert dep.version == "2.34"


def test_parse_depends_line_empty():
    assert parse_depends_line("") == []


def test_parse_depends_line_simple():
    result = parse_depends_line("libc6 (>= 2.34), libssl3")
    assert len(result) == 2
    assert result[0][0].name == "libc6"
    assert result[1][0].name == "libssl3"


def test_parse_depends_line_or():
    result = parse_depends_line("pkg-a | pkg-b")
    assert len(result) == 1
    assert len(result[0]) == 2
    assert result[0][0].name == "pkg-a"
    assert result[0][1].name == "pkg-b"


def test_format_package_info():
    info = PackageInfo(
        package="vsftpd",
        version="3.0.5-3",
        arch="amd64",
        filename="pool/main/v/vsftpd/vsftpd_3.0.5-3_amd64.deb",
        sha256="abc123",
        size=1024,
        description="FTP server",
        depends=[[Dependency("libc6", ">=", "2.34")]],
        provides=["ftp-server"],
    )
    text = format_package_info(info)
    assert "Package: vsftpd" in text
    assert "Version: 3.0.5-3" in text
    assert "Depends: libc6 (>= 2.34)" in text
    assert "Provides: ftp-server" in text


def test_parse_single_dep_empty():
    assert _parse_single_dep("") is None
    assert _parse_single_dep("   ") is None


def test_parse_single_dep_malformed_parens():
    dep = _parse_single_dep("libc6 (>= 2.34")
    assert dep is not None
    assert dep.name == "libc6 (>= 2.34"


def test_parse_depends_line_whitespace_only():
    assert parse_depends_line("   ") == []


def test_format_package_info_minimal():
    """A PackageInfo with only required fields should not crash."""
    text = format_package_info(PackageInfo(package="pkg", version="1.0"))
    assert "Package: pkg" in text
    assert "Version: 1.0" in text
