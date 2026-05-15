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
