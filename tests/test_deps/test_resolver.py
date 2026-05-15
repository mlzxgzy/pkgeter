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


def test_resolve_empty():
    """Empty package list returns empty result."""
    r = Resolver({})
    assert r.resolve([]) == []


def test_resolve_duplicate_packages():
    """Duplicate package names in input are deduplicated."""
    db = {"pkg-a": _make_pkg("pkg-a")}
    r = Resolver(db)
    result = r.resolve(["pkg-a", "pkg-a"])
    assert result == ["pkg-a"]


def test_resolve_file_path_dep_falls_back_to_alternative():
    """OR-dependency group where first alternative is a file path that can't
    be resolved falls through to the next alternative."""
    db = {
        "pkg-a": _make_pkg("pkg-a", depends=[[Dependency("/bin/sh"), Dependency("bash")]]),
        "bash": _make_pkg("bash"),
    }
    r = Resolver(db)
    result = r.resolve(["pkg-a"])
    # /bin/sh not in repo → resolver tries bash → resolves it
    assert result == ["bash", "pkg-a"]


def test_resolve_file_path_dep_skipped_when_no_provider():
    """Standalone file-path dep with no provider is silently skipped."""
    db = {
        "pkg-a": _make_pkg("pkg-a", depends=[[Dependency("/bin/awk")]]),
    }
    r = Resolver(db)
    result = r.resolve(["pkg-a"])
    assert result == ["pkg-a"]


def test_resolve_skips_soname_dep_no_provider():
    """Soname dep with no provider in repo is silently skipped."""
    db = {
        "pkg-a": _make_pkg("pkg-a", depends=[[Dependency("libc.so.6()(64bit)")]]),
    }
    r = Resolver(db)
    result = r.resolve(["pkg-a"])
    assert result == ["pkg-a"]
    assert "pkg-a" in r.skipped
    assert "libc.so.6()(64bit)" in r.skipped["pkg-a"]


def test_resolve_soname_dep_via_provides():
    """Soname dep is resolved through the provides mechanism when a
    provider exists in the repo (the core RPM dependency fix)."""
    db = {
        "nginx-mod": _make_pkg(
            "nginx-mod",
            depends=[[Dependency("libunwind.so.8()(64bit)")]],
        ),
        "libunwind": _make_pkg(
            "libunwind",
            provides=["libunwind.so.8()(64bit)"],
        ),
    }
    r = Resolver(db)
    result = r.resolve(["nginx-mod"])
    assert result == ["libunwind", "nginx-mod"]


def test_resolve_soname_transitive_deps():
    """Soname resolution should also pull in the provider's own transitive
    dependencies — this is the scenario the user reported (nginx →
    nginx-mod-http-image-filter → libunwind.so → libunwind → libgcc)."""
    db = {
        "nginx": _make_pkg(
            "nginx",
            depends=[[Dependency("nginx-mod")]],
        ),
        "nginx-mod": _make_pkg(
            "nginx-mod",
            depends=[
                [Dependency("libunwind.so.8()(64bit)")],
                [Dependency("libgd.so.2()(64bit)")],
            ],
        ),
        "libunwind": _make_pkg(
            "libunwind",
            depends=[[Dependency("libgcc")]],
            provides=["libunwind.so.8()(64bit)"],
        ),
        "libgd": _make_pkg(
            "libgd",
            provides=["libgd.so.2()(64bit)"],
        ),
        "libgcc": _make_pkg("libgcc"),
    }
    r = Resolver(db)
    result = r.resolve(["nginx"])
    # Full chain: libgcc → libunwind → libgd → nginx-mod → nginx
    assert "libgcc" in result
    assert "libunwind" in result
    assert "libgd" in result
    assert "nginx-mod" in result
    assert "nginx" in result
    assert result.index("libgcc") < result.index("libunwind")
    assert result.index("libunwind") < result.index("nginx-mod")
    assert result.index("nginx-mod") < result.index("nginx")


def test_resolve_skips_rpmlib_dep():
    """OR-dependency group with rpmlib( prefix is treated as resolved."""
    db = {
        "pkg-a": _make_pkg("pkg-a", depends=[[Dependency("rpmlib(CompressedFileNames)")]]),
    }
    r = Resolver(db)
    result = r.resolve(["pkg-a"])
    assert result == ["pkg-a"]


def test_resolve_skips_rtld_dep():
    """rtld(GNU_HASH) dependency is treated as resolved."""
    db = {
        "pkg-a": _make_pkg("pkg-a", depends=[[Dependency("rtld(GNU_HASH)")]]),
    }
    r = Resolver(db)
    result = r.resolve(["pkg-a"])
    assert result == ["pkg-a"]


def test_default_virtual_handler_empty_raises():
    """_default_virtual_handler raises ValueError on empty providers."""
    r = Resolver({})
    import pytest
    with pytest.raises(ValueError, match="No providers"):
        r._default_virtual_handler("virt-pkg", [])


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


# ---------------------------------------------------------------------------
# Soft dep fallback — basename extraction for file/soname deps
# ---------------------------------------------------------------------------


def test_resolve_file_path_dep_via_basename_fallback():
    """File-path dep like /usr/bin/perl resolves via basename 'perl' when
    provides-index lookup fails."""
    db = {
        "gd": _make_pkg("gd", depends=[[Dependency("/usr/bin/perl")]]),
        "perl": _make_pkg("perl"),
    }
    r = Resolver(db)
    result = r.resolve(["gd"])
    assert "perl" in result
    assert "gd" in result
    assert result.index("perl") < result.index("gd")


def test_resolve_file_path_dep_where_basename_is_missing():
    """File-path dep where basename doesn't match any package is still
    silently skipped (no regression on existing behavior)."""
    db = {
        "pkg-a": _make_pkg("pkg-a", depends=[[Dependency("/usr/bin/missing-tool")]]),
    }
    r = Resolver(db)
    result = r.resolve(["pkg-a"])
    assert result == ["pkg-a"]
    assert "/usr/bin/missing-tool" in r.skipped.get("pkg-a", [])


def test_resolve_soname_dep_via_stripped_fallback():
    """Soname dep with arch annotation that can't be matched by provides
    index is retried by stripping the () annotation."""
    db = {
        "pkg-a": _make_pkg("pkg-a", depends=[[Dependency("libfoo.so.3()(64bit)")]]),
        # Package provides the base soname WITHOUT the arch annotation
        "libfoo": _make_pkg("libfoo", provides=["libfoo.so.3"]),
    }
    r = Resolver(db)
    result = r.resolve(["pkg-a"])
    assert "libfoo" in result
    assert "pkg-a" in result


def test_resolve_soname_dep_no_match_even_after_stripping():
    """Soname dep that can't be resolved even after stripping annotations
    is still silently skipped."""
    db = {
        "pkg-a": _make_pkg("pkg-a", depends=[[Dependency("libfoo.so.3()(64bit)")]]),
    }
    r = Resolver(db)
    result = r.resolve(["pkg-a"])
    assert result == ["pkg-a"]
    assert "libfoo.so.3()(64bit)" in r.skipped.get("pkg-a", [])


def test_extract_pkg_candidate_file_path():
    """_extract_pkg_candidate extracts basename from file paths."""
    assert Resolver._extract_pkg_candidate("/usr/bin/perl") == "perl"
    assert Resolver._extract_pkg_candidate("/bin/sh") == "sh"
    assert Resolver._extract_pkg_candidate("/usr/bin/python3.10") == "python3.10"


def test_extract_pkg_candidate_soname():
    """_extract_pkg_candidate strips arch annotation from sonames."""
    assert Resolver._extract_pkg_candidate("libfoo.so.3()(64bit)") == "libfoo.so.3"
    assert Resolver._extract_pkg_candidate("libgd.so.3()(64bit)") == "libgd.so.3"
    assert Resolver._extract_pkg_candidate("libc.so.6") == "libc.so.6"


def test_extract_pkg_candidate_no_match():
    """_extract_pkg_candidate returns None for non-soft deps."""
    assert Resolver._extract_pkg_candidate("nginx") is None
    assert Resolver._extract_pkg_candidate("") is None


def test_resolve_file_path_dep_or_group_with_fallback():
    """OR-dependency group: file path resolves via fallback before trying
    the next alternative."""
    db = {
        "pkg-a": _make_pkg("pkg-a", depends=[[Dependency("/usr/bin/perl"), Dependency("other-perl")]]),
        "perl": _make_pkg("perl"),
        "other-perl": _make_pkg("other-perl"),
    }
    r = Resolver(db)
    result = r.resolve(["pkg-a"])
    # /usr/bin/perl → fallback to 'perl' → should resolve and short-circuit
    assert "perl" in result
    assert "other-perl" not in result  # second alternative not needed
    assert "pkg-a" in result
