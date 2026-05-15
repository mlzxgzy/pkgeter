"""Tests for virtual package resolution."""

from pkgeter.deps.virtual import find_providers
from pkgeter.models import PackageInfo


def _make_pkg(name: str, provides: list[str] | None = None) -> PackageInfo:
    return PackageInfo(
        package=name,
        version="1.0",
        provides=provides or [],
    )


def test_find_providers_no_match():
    """No package provides the virtual package → empty list."""
    db = {
        "vsftpd": _make_pkg("vsftpd"),
        "libc6": _make_pkg("libc6"),
    }
    assert find_providers("mail-transport-agent", db) == []


def test_find_providers_single_match():
    """One package provides the virtual package."""
    db = {
        "postfix": _make_pkg("postfix", provides=["mail-transport-agent"]),
    }
    assert find_providers("mail-transport-agent", db) == ["postfix"]


def test_find_providers_multiple_matches():
    """Multiple packages provide the same virtual → sorted by name."""
    db = {
        "postfix": _make_pkg("postfix", provides=["mail-transport-agent"]),
        "sendmail": _make_pkg("sendmail", provides=["mail-transport-agent"]),
    }
    assert find_providers("mail-transport-agent", db) == ["postfix", "sendmail"]


def test_find_providers_empty_db():
    """Empty package database → empty list."""
    assert find_providers("anything", {}) == []


def test_find_providers_package_provides_multiple():
    """A single package can provide multiple virtual packages."""
    db = {
        "nginx": _make_pkg("nginx", provides=["httpd", "proxy"]),
    }
    assert find_providers("httpd", db) == ["nginx"]
    assert find_providers("proxy", db) == ["nginx"]
    assert find_providers("mysql", db) == []


def test_find_providers_sorted_return():
    """Providers are returned in sorted order regardless of dict order."""
    db = {
        "z-pkg": _make_pkg("z-pkg", provides=["virt"]),
        "a-pkg": _make_pkg("a-pkg", provides=["virt"]),
        "m-pkg": _make_pkg("m-pkg", provides=["virt"]),
    }
    assert find_providers("virt", db) == ["a-pkg", "m-pkg", "z-pkg"]
