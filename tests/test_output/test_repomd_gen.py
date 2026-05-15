"""Tests for pure-Python RPM repodata generation."""

import gzip
import hashlib
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from pkgeter.models import PackageInfo, Dependency
from pkgeter.output.repomd_gen import build_repomd_xml, build_primary_xml


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def test_repomd_xml_structure(tmp_path):
    """repomd.xml contains a primary data entry with correct fields."""
    primary_xml = b"<metadata><package>...</package></metadata>"
    primary_gz = gzip.compress(primary_xml, mtime=0)
    repodata_dir = tmp_path / "repodata"
    repodata_dir.mkdir(parents=True)
    (repodata_dir / "primary.xml.gz").write_bytes(primary_gz)

    result = build_repomd_xml(primary_gz, tmp_path)

    root = ET.fromstring(result)
    ns = {"repo": "http://linux.duke.edu/metadata/repo"}
    data_el = root.find("repo:data[@type='primary']", ns)
    assert data_el is not None, "primary data element missing"

    location = data_el.find("repo:location", ns)
    assert location is not None
    assert location.get("href") == "repodata/primary.xml.gz"

    checksum = data_el.find("repo:checksum", ns)
    assert checksum is not None
    assert checksum.get("type") == "sha256"
    assert checksum.text == _sha256(primary_gz)

    timestamp = data_el.find("repo:timestamp", ns)
    assert timestamp is not None
    assert timestamp.text.isdigit()

    open_size = data_el.find("repo:open-size", ns)
    assert open_size is not None
    assert int(open_size.text) == len(primary_xml)

    size = data_el.find("repo:size", ns)
    assert size is not None
    assert int(size.text) == len(primary_gz)


def test_primary_xml_single_package():
    """primary.xml.gz contains one package entry with all required fields."""
    pkgs = {
        "openssl": PackageInfo(
            package="openssl",
            version="1:1.1.1k-7.el8_9",
            arch="x86_64",
            filename="rpms/openssl-1.1.1k-7.el8_9.x86_64.rpm",
            sha256="abc123",
            size=1234567,
            depends=[[Dependency(name="libc.so.6")]],
            provides=["openssl"],
        )
    }
    primary_gz = build_primary_xml(pkgs)
    raw = gzip.decompress(primary_gz)
    root = ET.fromstring(raw)

    assert root.tag == "{http://linux.duke.edu/metadata/common}metadata"
    assert int(root.get("packages", "0")) == 1

    pkg_el = root.find("{http://linux.duke.edu/metadata/common}package")
    assert pkg_el is not None
    assert pkg_el.get("type") == "rpm"

    name = pkg_el.find("{http://linux.duke.edu/metadata/common}name")
    assert name is not None and name.text == "openssl"

    arch = pkg_el.find("{http://linux.duke.edu/metadata/common}arch")
    assert arch is not None and arch.text == "x86_64"

    ver = pkg_el.find("{http://linux.duke.edu/metadata/common}version")
    assert ver is not None
    assert ver.get("epoch") == "1"
    assert ver.get("ver") == "1.1.1k"
    assert ver.get("rel") == "7.el8_9"

    checksum = pkg_el.find("{http://linux.duke.edu/metadata/common}checksum")
    assert checksum is not None
    assert checksum.get("type") == "sha256"
    assert checksum.get("pkgid") == "YES"

    location = pkg_el.find("{http://linux.duke.edu/metadata/common}location")
    assert location is not None
    assert location.get("href") == "rpms/openssl-1.1.1k-7.el8_9.x86_64.rpm"

    time_el = pkg_el.find("{http://linux.duke.edu/metadata/common}time")
    assert time_el is not None
    assert time_el.get("file") is not None

    size_el = pkg_el.find("{http://linux.duke.edu/metadata/common}size")
    assert size_el is not None
    assert size_el.get("package") == "1234567"

    fmt = pkg_el.find("{http://linux.duke.edu/metadata/common}format")
    assert fmt is not None
    ns_rpm = "http://linux.duke.edu/metadata/rpm"
    requires = fmt.find(f"{{{ns_rpm}}}requires")
    assert requires is not None
    req_entry = requires.find(f"{{{ns_rpm}}}entry")
    assert req_entry is not None
    assert req_entry.get("name") == "libc.so.6"

    provides = fmt.find(f"{{{ns_rpm}}}provides")
    assert provides is not None
    prov_entry = provides.find(f"{{{ns_rpm}}}entry")
    assert prov_entry is not None
    assert prov_entry.get("name") == "openssl"


def test_primary_xml_multiple_packages():
    """Multiple packages all appear in the XML."""
    pkgs = {
        "openssl": PackageInfo(
            package="openssl",
            version="1.1.1k-7.el8_9",
            filename="rpms/a.rpm",
        ),
        "curl": PackageInfo(
            package="curl",
            version="7.76.1-8.el8_9",
            filename="rpms/b.rpm",
        ),
    }
    primary_gz = build_primary_xml(pkgs)
    raw = gzip.decompress(primary_gz)
    root = ET.fromstring(raw)
    assert int(root.get("packages", "0")) == 2


def test_primary_xml_empty():
    """Empty package dict produces metadata with 0 packages."""
    primary_gz = build_primary_xml({})
    raw = gzip.decompress(primary_gz)
    root = ET.fromstring(raw)
    assert int(root.get("packages", "0")) == 0


def test_primary_xml_no_depends():
    """Package with no depends produces XML without requires section."""
    pkgs = {
        "pkg": PackageInfo(
            package="pkg",
            version="1.0-1",
            filename="rpms/pkg.rpm",
        ),
    }
    primary_gz = build_primary_xml(pkgs)
    raw = gzip.decompress(primary_gz)
    root = ET.fromstring(raw)
    pkg_el = root.find("{http://linux.duke.edu/metadata/common}package")
    fmt = pkg_el.find("{http://linux.duke.edu/metadata/common}format")
    ns_rpm = "http://linux.duke.edu/metadata/rpm"
    requires = fmt.find(f"{{{ns_rpm}}}requires")
    assert requires is None or len(requires) == 0


def test_primary_xml_version_no_epoch():
    """Version without epoch (no colon) produces epoch='0'."""
    pkgs = {
        "pkg": PackageInfo(
            package="pkg",
            version="1.0-1",
            filename="rpms/pkg.rpm",
        ),
    }
    primary_gz = build_primary_xml(pkgs)
    raw = gzip.decompress(primary_gz)
    root = ET.fromstring(raw)
    ver = root.find(
        "{http://linux.duke.edu/metadata/common}package/{http://linux.duke.edu/metadata/common}version"
    )
    assert ver.get("epoch") == "0"
    assert ver.get("ver") == "1.0"
    assert ver.get("rel") == "1"


def test_repomd_xml_gz_nonexistent():
    """build_repomd_xml raises FileNotFoundError when gz path doesn't exist."""
    with pytest.raises(FileNotFoundError):
        build_repomd_xml(b"", Path("/nonexistent/primary.xml.gz"))


def test_primary_xml_special_chars():
    """Package name with special XML chars is properly escaped."""
    pkgs = {
        "pkg-a>b": PackageInfo(
            package="pkg-a>b",
            version="1.0-1",
            filename="rpms/pkg.rpm",
        ),
    }
    primary_gz = build_primary_xml(pkgs)
    raw = gzip.decompress(primary_gz).decode()
    assert "pkg-a&gt;b" in raw
    assert ">pkg-a&gt;b<" in raw
