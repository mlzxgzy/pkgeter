"""Tests for dependency resolver."""

import pytest

from pkgeter.deps.resolver import Resolver
from pkgeter.models import PackageInfo, Dependency


def _make_pkg(name, depends=None, provides=None) -> PackageInfo:
    return PackageInfo(
        package=name,
        version="1.0",
        depends=depends or [],
        provides=provides or [],
        arch="amd64",
        filename=f"pool/main/{name[0]}/{name}/{name}_1.0_amd64.deb",
        sha256="x" * 64,
        size=1024,
    )


def test_resolve_single_package_no_deps():
    db = {"vsftpd": _make_pkg("vsftpd")}
    r = Resolver(db)
    result = r.resolve(["vsftpd"])
    assert result == ["vsftpd"]


def test_resolve_with_deps():
    db = {
        "vsftpd": _make_pkg("vsftpd", depends=[[Dependency("libc6")]]),
        "libc6": _make_pkg("libc6"),
    }
    r = Resolver(db)
    result = r.resolve(["vsftpd"])
    assert result == ["libc6", "vsftpd"]


def test_resolve_avoids_cycle():
    db = {
        "pkg-a": _make_pkg("pkg-a", depends=[[Dependency("pkg-b")]]),
        "pkg-b": _make_pkg("pkg-b", depends=[[Dependency("pkg-a")]]),
    }
    r = Resolver(db)
    result = r.resolve(["pkg-a"])
    assert result == ["pkg-b", "pkg-a"]


def test_resolve_skips_installed():
    db = {
        "vsftpd": _make_pkg("vsftpd", depends=[[Dependency("libc6")]]),
        "libc6": _make_pkg("libc6"),
    }
    r = Resolver(db, installed={"libc6"})
    result = r.resolve(["vsftpd"])
    assert result == ["vsftpd"]


def test_resolve_virtual_package():
    db = {
        "vsftpd": _make_pkg("vsftpd", depends=[[Dependency("mail-transport-agent")]]),
        "postfix": _make_pkg("postfix", provides=["mail-transport-agent"]),
    }
    r = Resolver(db, virtual_callback=lambda v, p: p[0])
    result = r.resolve(["vsftpd"])
    assert "postfix" in result


def test_resolve_or_dependency_fails():
    """OR dependency where no alternative is available should raise."""
    db = {
        "pkg-a": _make_pkg("pkg-a", depends=[[Dependency("pkg-b"), Dependency("pkg-c")]]),
    }
    r = Resolver(db, virtual_callback=lambda v, p: p[0])
    with pytest.raises(ValueError, match="Cannot resolve"):
        r.resolve(["pkg-a"])


def test_resolve_or_dependency_succeeds():
    """OR dependency where one alternative exists should use it."""
    db = {
        "pkg-a": _make_pkg("pkg-a", depends=[[Dependency("pkg-b"), Dependency("pkg-c")]]),
        "pkg-b": _make_pkg("pkg-b"),
    }
    r = Resolver(db)
    result = r.resolve(["pkg-a"])
    assert result == ["pkg-b", "pkg-a"]


def test_resolve_package_not_found():
    db = {}
    r = Resolver(db)
    with pytest.raises(ValueError, match="not found"):
        r.resolve(["nonexistent"])


def test_resolve_multiple_packages():
    db = {
        "pkg-a": _make_pkg("pkg-a", depends=[[Dependency("pkg-c")]]),
        "pkg-b": _make_pkg("pkg-b", depends=[[Dependency("pkg-c")]]),
        "pkg-c": _make_pkg("pkg-c"),
    }
    r = Resolver(db)
    result = r.resolve(["pkg-a", "pkg-b"])
    # pkg-a resolved first: pkg-c, pkg-a
    # then pkg-b (pkg-c already visited): pkg-b
    assert result == ["pkg-c", "pkg-a", "pkg-b"]
