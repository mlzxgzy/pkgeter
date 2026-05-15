"""Tests for :mod:`pkgeter.deps.provides_index`."""

import gzip

from pkgeter.deps.provides_index import ProvidesIndex
from pkgeter.models import PackageInfo


def _make_pkg(name, provides=None) -> PackageInfo:
    return PackageInfo(
        package=name,
        version="1.0",
        provides=provides or [],
    )


# ---------------------------------------------------------------------------
# build_from_packages
# ---------------------------------------------------------------------------


def test_build_from_packages_basic():
    """Index built from packages maps provides → package names."""
    pkgs = {
        "libunwind": _make_pkg("libunwind", provides=[
            "libunwind.so.8()(64bit)",
            "libunwind",
        ]),
        "openssl": _make_pkg("openssl", provides=[
            "libssl.so.10()(64bit)",
            "openssl",
        ]),
    }
    idx = ProvidesIndex()
    idx.build_from_packages(pkgs)

    assert idx.find("libunwind.so.8()(64bit)") == ["libunwind"]
    assert idx.find("libssl.so.10()(64bit)") == ["openssl"]


def test_build_from_packages_multiple_providers():
    """Multiple packages providing the same capability are all listed."""
    pkgs = {
        "postfix": _make_pkg("postfix", provides=["mail-transport-agent"]),
        "sendmail": _make_pkg("sendmail", provides=["mail-transport-agent"]),
    }
    idx = ProvidesIndex()
    idx.build_from_packages(pkgs)

    providers = idx.find("mail-transport-agent")
    assert sorted(providers) == ["postfix", "sendmail"]


def test_find_not_found():
    """Querying a name not in the index returns empty list."""
    idx = ProvidesIndex()
    assert idx.find("nonexistent") == []


def test_contains():
    """``in`` operator checks membership."""
    pkgs = {"foo": _make_pkg("foo", provides=["bar"])}
    idx = ProvidesIndex()
    idx.build_from_packages(pkgs)
    assert "bar" in idx
    assert "baz" not in idx


def test_len():
    """``len()`` returns number of distinct capabilities."""
    pkgs = {
        "a": _make_pkg("a", provides=["x", "y"]),
        "b": _make_pkg("b", provides=["z"]),
    }
    idx = ProvidesIndex()
    idx.build_from_packages(pkgs)
    assert len(idx) == 3


# ---------------------------------------------------------------------------
# add_filelists
# ---------------------------------------------------------------------------


FILELISTS_XML = """\
<?xml version="1.0" encoding="UTF-8"?>
<filelists xmlns="http://linux.duke.edu/metadata/filelists" packages="2">
  <package pkgid="abc123" name="libunwind" arch="x86_64">
    <version epoch="0" ver="1.3.1" rel="3.el8"/>
    <file>/usr/lib64/libunwind.so.8</file>
    <file>/usr/lib64/libunwind.so.8.0.1</file>
    <file type="dir">/usr/include/libunwind</file>
  </package>
  <package pkgid="def456" name="bash" arch="x86_64">
    <version epoch="0" ver="5.1" rel="6.el9"/>
    <file>/usr/bin/bash</file>
    <file>/bin/sh</file>
  </package>
</filelists>
"""


def test_add_filelists():
    """File paths from filelists.xml.gz are added to the index."""
    idx = ProvidesIndex()
    gz_data = gzip.compress(FILELISTS_XML.encode("utf-8"))
    idx.add_filelists(gz_data)

    assert idx.find("/usr/lib64/libunwind.so.8") == ["libunwind"]
    assert idx.find("/usr/bin/bash") == ["bash"]
    assert idx.find("/bin/sh") == ["bash"]


def test_combined_index():
    """Provides from primary.xml + file paths from filelists are merged."""
    pkgs = {
        "libunwind": _make_pkg("libunwind", provides=[
            "libunwind.so.8()(64bit)",
        ]),
    }
    idx = ProvidesIndex()
    idx.build_from_packages(pkgs)
    idx.add_filelists(gzip.compress(FILELISTS_XML.encode("utf-8")))

    # soname from primary
    assert idx.find("libunwind.so.8()(64bit)") == ["libunwind"]
    # file path from filelists
    assert idx.find("/usr/lib64/libunwind.so.8") == ["libunwind"]
    # file path for a different package
    assert idx.find("/bin/sh") == ["bash"]


# ---------------------------------------------------------------------------
# Integration with Resolver
# ---------------------------------------------------------------------------


def test_resolver_uses_provides_index():
    """Resolver with a ProvidesIndex resolves soname deps via O(1) lookup."""
    from pkgeter.deps.resolver import Resolver
    from pkgeter.models import Dependency

    pkgs = {
        "nginx-mod": PackageInfo(
            package="nginx-mod",
            version="1.0",
            depends=[[Dependency("libunwind.so.8()(64bit)")]],
        ),
        "libunwind": PackageInfo(
            package="libunwind",
            version="1.0",
            provides=["libunwind.so.8()(64bit)"],
        ),
    }
    idx = ProvidesIndex()
    idx.build_from_packages(pkgs)

    r = Resolver(pkgs, provides_index=idx)
    result = r.resolve(["nginx-mod"])
    assert result == ["libunwind", "nginx-mod"]


def test_resolver_uses_filelists_index():
    """Resolver resolves file-path deps through filelists-based index."""
    from pkgeter.deps.resolver import Resolver
    from pkgeter.models import Dependency

    pkgs = {
        "some-pkg": PackageInfo(
            package="some-pkg",
            version="1.0",
            depends=[[Dependency("/bin/sh")]],
        ),
        "bash": PackageInfo(
            package="bash",
            version="5.1",
        ),
    }
    idx = ProvidesIndex()
    idx.build_from_packages(pkgs)
    idx.add_filelists(gzip.compress(FILELISTS_XML.encode("utf-8")))

    r = Resolver(pkgs, provides_index=idx)
    result = r.resolve(["some-pkg"])
    assert result == ["bash", "some-pkg"]
