"""Tests for dependency tree builder."""

import pytest

from pkgeter.deps.tree import TreeNode, build_dependency_tree
from pkgeter.models import PackageInfo, Dependency


def _make_pkg(name, version="1.0", depends=None, provides=None) -> PackageInfo:
    return PackageInfo(
        package=name,
        version=version,
        depends=depends or [],
        provides=provides or [],
        arch="amd64",
        filename=f"pool/main/{name[0]}/{name}/{name}_{version}_amd64.deb",
        sha256="x" * 64,
        size=1024,
    )


def test_single_package_no_deps():
    """A package with no dependencies produces a single leaf node."""
    db = {"nginx": _make_pkg("nginx", "1.22.1")}
    trees = build_dependency_tree(["nginx"], db)
    assert len(trees) == 1
    node = trees[0]
    assert node.name == "nginx"
    assert node.version == "1.22.1"
    assert node.children == []
    assert not node.is_circular
    assert not node.is_virtual


def test_single_package_with_deps():
    """A package with dependencies produces a tree with children."""
    db = {
        "nginx": _make_pkg("nginx", depends=[[Dependency("libc6")]]),
        "libc6": _make_pkg("libc6", "2.36"),
    }
    trees = build_dependency_tree(["nginx"], db)
    assert len(trees) == 1
    root = trees[0]
    assert root.name == "nginx"
    assert len(root.children) == 1
    assert root.children[0].name == "libc6"
    assert root.children[0].version == "2.36"
    assert root.children[0].children == []


def test_deep_dependency_chain():
    """Dependencies of dependencies are nested correctly."""
    db = {
        "app": _make_pkg("app", depends=[[Dependency("libfoo")]]),
        "libfoo": _make_pkg("libfoo", depends=[[Dependency("libc6")]]),
        "libc6": _make_pkg("libc6"),
    }
    trees = build_dependency_tree(["app"], db)
    root = trees[0]
    assert root.name == "app"
    assert len(root.children) == 1
    assert root.children[0].name == "libfoo"
    assert len(root.children[0].children) == 1
    assert root.children[0].children[0].name == "libc6"


def test_multiple_deps():
    """A package with multiple AND dependencies gets multiple children."""
    db = {
        "app": _make_pkg("app", depends=[[Dependency("liba")], [Dependency("libb")]]),
        "liba": _make_pkg("liba"),
        "libb": _make_pkg("libb"),
    }
    trees = build_dependency_tree(["app"], db)
    root = trees[0]
    assert len(root.children) == 2
    names = {c.name for c in root.children}
    assert names == {"liba", "libb"}


def test_cycle_detection():
    """Circular dependency produces a node with is_circular=True."""
    db = {
        "pkg-a": _make_pkg("pkg-a", depends=[[Dependency("pkg-b")]]),
        "pkg-b": _make_pkg("pkg-b", depends=[[Dependency("pkg-a")]]),
    }
    trees = build_dependency_tree(["pkg-a"], db)
    root = trees[0]
    assert root.name == "pkg-a"
    assert len(root.children) == 1
    child_b = root.children[0]
    assert child_b.name == "pkg-b"
    assert len(child_b.children) == 1
    circular_ref = child_b.children[0]
    assert circular_ref.name == "pkg-a"
    assert circular_ref.is_circular is True
    assert circular_ref.children == []


def test_or_dependency_picks_first_available():
    """OR dependency picks the first available and records alternatives."""
    db = {
        "app": _make_pkg("app", depends=[[Dependency("pkg-x"), Dependency("pkg-y")]]),
        "pkg-y": _make_pkg("pkg-y"),
    }
    trees = build_dependency_tree(["app"], db)
    root = trees[0]
    assert len(root.children) == 1
    child = root.children[0]
    assert child.name == "pkg-y"
    assert child.or_alternatives == ["pkg-x"]


def test_or_dependency_first_present():
    """OR dependency picks the first present alternative."""
    db = {
        "app": _make_pkg("app", depends=[[Dependency("pkg-x"), Dependency("pkg-y")]]),
        "pkg-x": _make_pkg("pkg-x"),
        "pkg-y": _make_pkg("pkg-y"),
    }
    trees = build_dependency_tree(["app"], db)
    child = trees[0].children[0]
    assert child.name == "pkg-x"
    assert child.or_alternatives == ["pkg-y"]


def test_virtual_package_resolution():
    """Virtual packages are marked with is_virtual and provider."""
    db = {
        "app": _make_pkg("app", depends=[[Dependency("mail-transport-agent")]]),
        "postfix": _make_pkg("postfix", provides=["mail-transport-agent"]),
    }
    trees = build_dependency_tree(["app"], db)
    child = trees[0].children[0]
    assert child.name == "mail-transport-agent"
    assert child.is_virtual is True
    assert child.provider == "postfix"


def test_installed_packages_are_leaf_nodes():
    """Installed packages become leaf nodes without expanding children."""
    db = {
        "app": _make_pkg("app", depends=[[Dependency("libc6")]]),
        "libc6": _make_pkg("libc6", depends=[[Dependency("libgcc")]]),
        "libgcc": _make_pkg("libgcc"),
    }
    trees = build_dependency_tree(["app"], db, installed={"libc6"})
    root = trees[0]
    child = root.children[0]
    assert child.name == "libc6"
    assert child.children == []  # Not expanded because it's installed


def test_multiple_target_packages():
    """Multiple target packages produce multiple root nodes."""
    db = {
        "curl": _make_pkg("curl"),
        "wget": _make_pkg("wget"),
    }
    trees = build_dependency_tree(["curl", "wget"], db)
    assert len(trees) == 2
    assert trees[0].name == "curl"
    assert trees[1].name == "wget"


def test_package_not_found():
    """Unknown package produces a node with '(not found)' version."""
    db = {}
    trees = build_dependency_tree(["nonexistent"], db)
    assert len(trees) == 1
    assert trees[0].name == "nonexistent"
    assert trees[0].version == "(not found)"


def test_system_deps_skipped():
    """System-provided deps (absolute paths, .so) with no provider are skipped."""
    db = {
        "app": _make_pkg("app", depends=[
            [Dependency("/bin/sh")],
            [Dependency("libc.so.6()(64bit)")],
            [Dependency("rpmlib(CompressedFileNames)")],
        ]),
    }
    trees = build_dependency_tree(["app"], db)
    assert trees[0].children == []


def test_soname_dep_resolved_via_provides():
    """Soname dependency with a provider in the DB is resolved, not skipped."""
    db = {
        "nginx-mod": _make_pkg("nginx-mod", depends=[
            [Dependency("libunwind.so.8()(64bit)")],
        ]),
        "libunwind": _make_pkg("libunwind", "1.3.1",
                               provides=["libunwind.so.8()(64bit)"]),
    }
    trees = build_dependency_tree(["nginx-mod"], db)
    root = trees[0]
    assert len(root.children) == 1
    child = root.children[0]
    assert child.name == "libunwind.so.8()(64bit)"
    assert child.is_virtual is True
    assert child.provider == "libunwind"


def test_soname_dep_resolved_via_external_index():
    """Soname dependency resolved through an external ProvidesIndex."""
    from pkgeter.deps.provides_index import ProvidesIndex

    db = {
        "nginx-mod": _make_pkg("nginx-mod", depends=[
            [Dependency("libunwind.so.8()(64bit)")],
        ]),
        "libunwind": _make_pkg("libunwind", "1.3.1"),
    }
    idx = ProvidesIndex()
    idx.build_from_packages({
        "libunwind": _make_pkg("libunwind", "1.3.1",
                               provides=["libunwind.so.8()(64bit)"]),
    })
    trees = build_dependency_tree(["nginx-mod"], db, external_index=idx)
    root = trees[0]
    assert len(root.children) == 1
    child = root.children[0]
    assert child.name == "libunwind.so.8()(64bit)"
    assert child.is_virtual is True
    assert child.provider == "libunwind"


def test_soname_transitive_deps_in_tree():
    """Full chain: nginx → nginx-mod → libunwind.so → libunwind → libgcc."""
    db = {
        "nginx": _make_pkg("nginx", depends=[
            [Dependency("nginx-mod")],
        ]),
        "nginx-mod": _make_pkg("nginx-mod", depends=[
            [Dependency("libunwind.so.8()(64bit)")],
        ]),
        "libunwind": _make_pkg("libunwind", "1.3.1",
                               depends=[[Dependency("libgcc")]],
                               provides=["libunwind.so.8()(64bit)"]),
        "libgcc": _make_pkg("libgcc"),
    }
    trees = build_dependency_tree(["nginx"], db)
    root = trees[0]
    assert root.name == "nginx"
    # nginx → nginx-mod
    assert len(root.children) == 1
    mod_node = root.children[0]
    assert mod_node.name == "nginx-mod"
    # nginx-mod → libunwind.so.8()(64bit) (virtual)
    assert len(mod_node.children) == 1
    so_node = mod_node.children[0]
    assert so_node.name == "libunwind.so.8()(64bit)"
    assert so_node.is_virtual is True
    assert so_node.provider == "libunwind"
    # virtual node inherits libunwind's children → libgcc
    assert len(so_node.children) == 1
    assert so_node.children[0].name == "libgcc"


from pathlib import Path
from pkgeter.backend.debian import DebianBackend

SAMPLE_PACKAGES_GZ = Path(__file__).parent.parent / "data" / "sample_packages.gz"


def test_tree_with_sample_packages_gz():
    """Integration test: build tree from sample_packages.gz fixture."""
    if not SAMPLE_PACKAGES_GZ.exists():
        pytest.skip("sample_packages.gz not found")
    raw = SAMPLE_PACKAGES_GZ.read_bytes()
    backend = DebianBackend()
    db = backend._parse_packages_gz(raw)
    if not db:
        pytest.skip("sample_packages.gz is empty")
    # Pick first package from DB
    first_pkg = next(iter(db))
    trees = build_dependency_tree([first_pkg], db)
    assert len(trees) == 1
    assert trees[0].name == first_pkg
    assert trees[0].version == db[first_pkg].version
