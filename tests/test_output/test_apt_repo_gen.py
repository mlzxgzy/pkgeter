"""Tests for pure-Python apt repository metadata generation."""

import gzip

from pkgeter.models import PackageInfo, Dependency
from pkgeter.output.apt_repo_gen import build_packages_gz, build_release


def test_packages_gz_single():
    """Single package produces correct stanza."""
    pkgs = {
        "vsftpd": PackageInfo(
            package="vsftpd",
            version="3.0.5-3",
            arch="amd64",
            filename="debs/vsftpd_3.0.5-3_amd64.deb",
            sha256="abc123",
            size=123456,
            description="FTP server",
            depends=[[Dependency(name="libc6", version_operator=">=", version="2.28")]],
        )
    }
    raw = gzip.decompress(build_packages_gz(pkgs)).decode()
    assert "Package: vsftpd" in raw
    assert "Version: 3.0.5-3" in raw
    assert "Architecture: amd64" in raw
    assert "Filename: debs/vsftpd_3.0.5-3_amd64.deb" in raw
    assert "SHA256: abc123" in raw
    assert "Size: 123456" in raw
    assert "Description: FTP server" in raw
    assert "Depends: libc6 (>= 2.28)" in raw


def test_packages_gz_multiple():
    """Multiple packages each have their own stanza."""
    pkgs = {
        "pkg1": PackageInfo(package="pkg1", version="1.0-1", arch="amd64", filename="debs/pkg1.deb"),
        "pkg2": PackageInfo(package="pkg2", version="2.0-1", arch="amd64", filename="debs/pkg2.deb"),
    }
    raw = gzip.decompress(build_packages_gz(pkgs)).decode()
    assert raw.count("Package:") == 2
    assert "\n\n" in raw


def test_packages_gz_empty():
    """Empty package dict returns empty gzip."""
    data = gzip.decompress(build_packages_gz({})).decode()
    assert data.strip() == ""


def test_packages_gz_provides():
    """Provides field is rendered correctly."""
    pkgs = {
        "pkg": PackageInfo(
            package="pkg", version="1.0-1", arch="amd64",
            filename="debs/pkg.deb", provides=["virtual-pkg"],
        )
    }
    raw = gzip.decompress(build_packages_gz(pkgs)).decode()
    assert "Provides: virtual-pkg" in raw


def test_packages_gz_or_depends():
    """OR-dependencies (pipe-separated) render correctly."""
    pkgs = {
        "pkg": PackageInfo(
            package="pkg", version="1.0-1", arch="amd64",
            filename="debs/pkg.deb",
            depends=[
                [Dependency(name="libc6")],
                [Dependency(name="pkg-a"), Dependency(name="pkg-b")],
            ],
        )
    }
    raw = gzip.decompress(build_packages_gz(pkgs)).decode()
    assert "libc6" in raw
    assert "pkg-a | pkg-b" in raw


def test_release_file():
    """Release file contains expected fields."""
    release = build_release(
        codename="bookworm",
        arch="amd64",
        packages_gz_sha256="abc123",
        packages_gz_size=1234,
    )
    assert "Codename: bookworm" in release
    assert "Architectures: amd64" in release
    assert "Components: main" in release
    assert "Date:" in release
    assert "abc123" in release
    assert "1234" in release
    assert "main/binary-amd64/Packages.gz" in release
