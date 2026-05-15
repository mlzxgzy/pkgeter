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
    assert "Depends:" not in text
    assert "Provides:" not in text


def test_parse_single_dep_version_no_version():
    """Version operator without version number is handled."""
    dep = _parse_single_dep("libc6 (>= )")
    assert dep is not None
    assert dep.name == "libc6"
    assert dep.version_operator == ">="
    assert dep.version is None


def test_parse_single_dep_extra_parentheses():
    """Extra closing parenthesis is handled (stops at first )."""
    dep = _parse_single_dep("libc6 (>= 2.34))")
    assert dep is not None
    assert dep.name == "libc6"
    assert dep.version_operator == ">="
    assert dep.version == "2.34"


def test_parse_depends_line_trailing_comma():
    """Trailing comma after valid dependency is handled."""
    result = parse_depends_line("libc6 (>= 2.34), ")
    assert len(result) == 1
    assert result[0][0].name == "libc6"


def test_parse_depends_line_or_empty_alternative():
    """OR group with an empty alternative is handled."""
    result = parse_depends_line("pkg-a |  | pkg-b")
    assert len(result) == 1
    assert len(result[0]) == 2
    assert result[0][0].name == "pkg-a"
    assert result[0][1].name == "pkg-b"


def test_parse_depends_line_multiple_or_groups():
    """Multiple comma-separated OR groups are handled."""
    result = parse_depends_line("pkg-a | pkg-b, pkg-c | pkg-d")
    assert len(result) == 2
    assert len(result[0]) == 2
    assert len(result[1]) == 2
    assert result[0][0].name == "pkg-a"
    assert result[0][1].name == "pkg-b"
    assert result[1][0].name == "pkg-c"
    assert result[1][1].name == "pkg-d"


def test_format_package_info_no_depends():
    """format_package_info works when depends and provides are empty."""
    info = PackageInfo(package="empty-pkg", version="1.0", arch="amd64")
    text = format_package_info(info)
    assert "Package: empty-pkg" in text
    assert "Version: 1.0" in text
    assert "Depends:" not in text
    assert "Provides:" not in text


def test_format_package_info_multi_depends():
    """format_package_info renders multiple dep groups correctly."""
    info = PackageInfo(
        package="multi-dep",
        version="1.0",
        arch="amd64",
        depends=[
            [Dependency("libc6", ">=", "2.34")],
            [Dependency("pkg-a"), Dependency("pkg-b")],
        ],
        provides=["virt-pkg"],
        description="Has multiple deps",
    )
    text = format_package_info(info)
    assert "Depends: libc6 (>= 2.34), pkg-a | pkg-b" in text
    assert "Provides: virt-pkg" in text
    assert "Description: Has multiple deps" in text
