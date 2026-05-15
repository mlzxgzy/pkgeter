"""Tests for :mod:`pkgeter.backend.rpm`."""

import gzip

from pkgeter.backend.rpm import RpmBackend
from pkgeter.models import PackageInfo

# ---------------------------------------------------------------------------
# Inline XML test data
# ---------------------------------------------------------------------------

REPOMD_XML = """\
<?xml version="1.0" encoding="UTF-8"?>
<repomd xmlns="http://linux.duke.edu/metadata/repo">
  <data type="primary">
    <location href="repodata/abc123-primary.xml.gz"/>
    <checksum type="sha256">e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855</checksum>
  </data>
  <data type="filelists">
    <location href="repodata/def456-filelists.xml.gz"/>
    <checksum type="sha256">aabbccdd</checksum>
  </data>
</repomd>
"""

PRIMARY_XML_SINGLE = """\
<?xml version="1.0" encoding="UTF-8"?>
<metadata xmlns="http://linux.duke.edu/metadata/common" packages="1">
  <package type="rpm">
    <name>openssl</name>
    <arch>x86_64</arch>
    <version epoch="0" ver="1.1.1k" rel="7.el8_9"/>
    <format>
      <rpm:requires xmlns:rpm="http://linux.duke.edu/metadata/rpm">
        <rpm:entry name="libc.so.6()(64bit)"/>
        <rpm:entry name="krb5-libs"/>
      </rpm:requires>
      <rpm:provides xmlns:rpm="http://linux.duke.edu/metadata/rpm">
        <rpm:entry name="openssl" flags="EQ" epoch="0" ver="1.1.1k" rel="7.el8_9"/>
        <rpm:entry name="libssl.so.10()(64bit)"/>
      </rpm:provides>
    </format>
    <location href="Packages/openssl-1.1.1k-7.el8_9.x86_64.rpm"/>
    <checksum type="sha256">def456</checksum>
  </package>
</metadata>
"""


def _compress(xml_str: str) -> bytes:
    """Gzip-compress an XML string for parser input."""
    return gzip.compress(xml_str.encode("utf-8"))


# ---------------------------------------------------------------------------
# Backend name
# ---------------------------------------------------------------------------


def test_backend_name():
    """RpmBackend.name returns ``'rpm'``."""
    assert RpmBackend().name == "rpm"


# ---------------------------------------------------------------------------
# _parse_repomd
# ---------------------------------------------------------------------------


def test_parse_repomd():
    """``_parse_repomd`` extracts primary and filelists from repomd.xml."""
    meta = RpmBackend._parse_repomd(REPOMD_XML)
    assert "primary" in meta
    href, sha256 = meta["primary"]
    assert href == "repodata/abc123-primary.xml.gz"
    assert sha256 == "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
    assert "filelists" in meta
    fl_href, fl_sha = meta["filelists"]
    assert fl_href == "repodata/def456-filelists.xml.gz"
    assert fl_sha == "aabbccdd"


def test_parse_repomd_no_primary():
    """``_parse_repomd`` raises when ``data[@type='primary']`` is missing."""
    xml = """\
<?xml version="1.0" encoding="UTF-8"?>
<repomd xmlns="http://linux.duke.edu/metadata/repo">
  <data type="other">
    <location href="repodata/other.xml.gz"/>
  </data>
</repomd>
"""
    import pytest
    with pytest.raises(ValueError, match="No primary data element"):
        RpmBackend._parse_repomd(xml)


# ---------------------------------------------------------------------------
# _parse_primary
# ---------------------------------------------------------------------------


def test_parse_primary():
    """``_parse_primary`` parses gzip-compressed primary.xml into PackageInfo."""
    pkgs = RpmBackend._parse_primary(_compress(PRIMARY_XML_SINGLE))
    assert len(pkgs) == 1
    assert "openssl" in pkgs

    pkg = pkgs["openssl"]
    assert pkg.package == "openssl"
    assert pkg.version == "1.1.1k-7.el8_9"  # epoch "0" is omitted
    assert pkg.arch == "x86_64"
    assert pkg.filename == "Packages/openssl-1.1.1k-7.el8_9.x86_64.rpm"
    assert pkg.sha256 == "def456"

    # Two requires entries, each as a single-element Dependency group
    assert len(pkg.depends) == 2
    assert pkg.depends[0][0].name == "libc.so.6()(64bit)"
    assert pkg.depends[1][0].name == "krb5-libs"

    # Provides includes all entries (self-provides + virtual capabilities)
    assert pkg.provides == ["openssl", "libssl.so.10()(64bit)"]


def test_parse_primary_with_epoch():
    """Non-zero epoch is included in the version string (``epoch:ver-rel``)."""
    xml = """\
<?xml version="1.0" encoding="UTF-8"?>
<metadata xmlns="http://linux.duke.edu/metadata/common" packages="1">
  <package type="rpm">
    <name>glibc</name>
    <arch>x86_64</arch>
    <version epoch="2" ver="2.28" rel="164.el8"/>
    <format>
      <rpm:requires xmlns:rpm="http://linux.duke.edu/metadata/rpm"/>
      <rpm:provides xmlns:rpm="http://linux.duke.edu/metadata/rpm">
        <rpm:entry name="glibc"/>
      </rpm:provides>
    </format>
    <location href="Packages/glibc-2.28-164.el8.x86_64.rpm"/>
    <checksum type="sha256">abc123</checksum>
  </package>
</metadata>
"""
    pkgs = RpmBackend._parse_primary(_compress(xml))
    assert pkgs["glibc"].version == "2:2.28-164.el8"
    assert pkgs["glibc"].arch == "x86_64"


def test_parse_primary_multiple_packages():
    """``_parse_primary`` handles multiple packages in one metadata file."""
    xml = """\
<?xml version="1.0" encoding="UTF-8"?>
<metadata xmlns="http://linux.duke.edu/metadata/common" packages="2">
  <package type="rpm">
    <name>openssl</name>
    <arch>x86_64</arch>
    <version epoch="0" ver="1.1.1k" rel="7.el8_9"/>
    <format>
      <rpm:requires xmlns:rpm="http://linux.duke.edu/metadata/rpm"/>
      <rpm:provides xmlns:rpm="http://linux.duke.edu/metadata/rpm">
        <rpm:entry name="openssl"/>
      </rpm:provides>
    </format>
    <location href="Packages/openssl-1.1.1k-7.el8_9.x86_64.rpm"/>
    <checksum type="sha256">abc</checksum>
  </package>
  <package type="rpm">
    <name>krb5-libs</name>
    <arch>x86_64</arch>
    <version epoch="0" ver="1.17" rel="9.el8"/>
    <format>
      <rpm:requires xmlns:rpm="http://linux.duke.edu/metadata/rpm"/>
      <rpm:provides xmlns:rpm="http://linux.duke.edu/metadata/rpm">
        <rpm:entry name="krb5-libs"/>
      </rpm:provides>
    </format>
    <location href="Packages/krb5-libs-1.17-9.el8.x86_64.rpm"/>
    <checksum type="sha256">def</checksum>
  </package>
</metadata>
"""
    pkgs = RpmBackend._parse_primary(_compress(xml))
    assert len(pkgs) == 2
    assert pkgs["openssl"].version == "1.1.1k-7.el8_9"
    assert pkgs["krb5-libs"].version == "1.17-9.el8"


def test_parse_primary_empty():
    """Empty primary.xml.gz (no packages) produces an empty dict."""
    xml = """\
<?xml version="1.0" encoding="UTF-8"?>
<metadata xmlns="http://linux.duke.edu/metadata/common" packages="0">
</metadata>
"""
    pkgs = RpmBackend._parse_primary(_compress(xml))
    assert pkgs == {}


def test_parse_primary_no_deps():
    """A package with no requires entries has an empty depends list."""
    xml = """\
<?xml version="1.0" encoding="UTF-8"?>
<metadata xmlns="http://linux.duke.edu/metadata/common" packages="1">
  <package type="rpm">
    <name>no-deps-pkg</name>
    <arch>noarch</arch>
    <version epoch="0" ver="1.0" rel="1"/>
    <format>
      <rpm:requires xmlns:rpm="http://linux.duke.edu/metadata/rpm"/>
    </format>
    <location href="Packages/no-deps-pkg-1.0-1.noarch.rpm"/>
    <checksum type="sha256">nosha</checksum>
  </package>
</metadata>
"""
    pkgs = RpmBackend._parse_primary(_compress(xml))
    assert pkgs["no-deps-pkg"].depends == []


# ---------------------------------------------------------------------------
# build_download_url
# ---------------------------------------------------------------------------


def test_build_download_url():
    """``build_download_url`` combines base URL with the package filename."""
    pkg = PackageInfo(
        package="openssl",
        version="1.1.1k-7.el8_9",
        filename="Packages/openssl-1.1.1k-7.el8_9.x86_64.rpm",
    )
    url = RpmBackend.build_download_url(
        "https://mirror.centos.org/centos/8/BaseOS/x86_64/os",
        pkg,
    )
    assert url == (
        "https://mirror.centos.org/centos/8/BaseOS/x86_64/os"
        "/Packages/openssl-1.1.1k-7.el8_9.x86_64.rpm"
    )


def test_build_download_url_trailing_slash():
    """Trailing slash on the base URL is handled gracefully."""
    pkg = PackageInfo(
        package="openssl",
        version="1.1.1k-7.el8_9",
        filename="Packages/openssl-1.1.1k-7.el8_9.x86_64.rpm",
    )
    url = RpmBackend.build_download_url(
        "https://mirror.centos.org/centos/8/BaseOS/x86_64/os/",
        pkg,
    )
    assert url == (
        "https://mirror.centos.org/centos/8/BaseOS/x86_64/os"
        "/Packages/openssl-1.1.1k-7.el8_9.x86_64.rpm"
    )


# ---------------------------------------------------------------------------
# generate_install_script
# ---------------------------------------------------------------------------


def test_generate_install_script_basic():
    """Generated script contains ``sudo rpm -ivh`` commands for each file."""
    script = RpmBackend.generate_install_script(
        ["openssl-1.1.1k-7.el8_9.x86_64.rpm", "krb5-libs-1.17-9.el8.x86_64.rpm"],
        ["openssl"],
    )
    assert "#!/bin/bash" in script
    assert "sudo rpm -ivh" in script
    assert "openssl-1.1.1k-7.el8_9.x86_64.rpm" in script
    assert "krb5-libs-1.17-9.el8.x86_64.rpm" in script
    assert "openssl" in script


def test_generate_install_script_single_file():
    """Script works with a single file and multiple target names in header."""
    script = RpmBackend.generate_install_script(
        ["openssl-1.1.1k-7.el8_9.x86_64.rpm"],
        ["openssl", "openssl-libs"],
    )
    assert "openssl-1.1.1k-7.el8_9.x86_64.rpm" in script
    assert "Target packages: openssl openssl-libs" in script
    assert script.count("sudo rpm -ivh") == 1


def test_generate_install_script_empty():
    """Script with no files still produces valid shell output."""
    script = RpmBackend.generate_install_script([], [])
    assert "#!/bin/bash" in script
    assert "sudo rpm -ivh" not in script


# ---------------------------------------------------------------------------
# download_package_db
# ---------------------------------------------------------------------------


def test_download_package_db_empty_repos():
    """Empty repos list produces an empty package database."""
    backend = RpmBackend()
    db = backend.download_package_db(repos=[], arch="x86_64")
    assert db == {}


# ---------------------------------------------------------------------------
# merge_package_dbs
# ---------------------------------------------------------------------------


def test_merge_package_dbs():
    """``merge_package_dbs`` combines multiple DBs, later overriding earlier."""
    backend = RpmBackend()
    db1 = {"a": PackageInfo(package="a", version="1.0")}
    db2 = {"b": PackageInfo(package="b", version="2.0")}
    merged = backend.merge_package_dbs([db1, db2])
    assert len(merged) == 2
    assert merged["a"].version == "1.0"
    assert merged["b"].version == "2.0"


def test_merge_package_dbs_override():
    """Later repos override earlier ones for the same package name."""
    backend = RpmBackend()
    db1 = {"a": PackageInfo(package="a", version="1.0")}
    db2 = {"a": PackageInfo(package="a", version="2.0")}
    merged = backend.merge_package_dbs([db1, db2])
    assert merged["a"].version == "2.0"
