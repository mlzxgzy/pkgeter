"""Dependency tree builder - construct nested tree structures for visualization."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Optional, Set

from pkgeter.deps.virtual import find_providers
from pkgeter.models import PackageInfo


@dataclass
class TreeNode:
    """A node in the dependency tree."""

    name: str
    version: str
    children: list[TreeNode] = field(default_factory=list)
    is_circular: bool = False
    is_virtual: bool = False
    provider: str = ""
    or_alternatives: list[str] = field(default_factory=list)


def build_dependency_tree(
    pkg_names: list[str],
    all_pkgs: Dict[str, PackageInfo],
    installed: Optional[Set[str]] = None,
) -> list[TreeNode]:
    """Build dependency trees for the given package names.

    Returns one TreeNode per target package, with nested children
    representing the full dependency graph.
    """
    installed = installed or set()
    trees: list[TreeNode] = []
    for name in pkg_names:
        tree = _build_node(name, all_pkgs, installed, ancestors=set())
        trees.append(tree)
    return trees


def _build_node(
    pkg_name: str,
    all_pkgs: Dict[str, PackageInfo],
    installed: Set[str],
    ancestors: Set[str],
) -> TreeNode:
    """Recursively build a TreeNode for a single package."""
    # Cycle detection
    if pkg_name in ancestors:
        return TreeNode(name=pkg_name, version="", is_circular=True)

    # Installed packages become leaf nodes
    if pkg_name in installed:
        info = all_pkgs.get(pkg_name)
        version = info.version if info else ""
        return TreeNode(name=pkg_name, version=version)

    info = all_pkgs.get(pkg_name)
    if info is None:
        # Try virtual package resolution
        providers = find_providers(pkg_name, all_pkgs)
        if not providers:
            return TreeNode(name=pkg_name, version="(not found)")
        chosen = providers[0]
        real_node = _build_node(chosen, all_pkgs, installed, ancestors)
        return TreeNode(
            name=pkg_name,
            version="",
            children=real_node.children,
            is_virtual=True,
            provider=chosen,
        )

    new_ancestors = ancestors | {pkg_name}
    children: list[TreeNode] = []

    if info.depends:
        for dep_group in info.depends:
            child = _resolve_dep_group(dep_group, all_pkgs, installed, new_ancestors)
            if child is not None:
                children.append(child)

    return TreeNode(name=pkg_name, version=info.version, children=children)


def _resolve_dep_group(
    dep_group: list,
    all_pkgs: Dict[str, PackageInfo],
    installed: Set[str],
    ancestors: Set[str],
) -> TreeNode | None:
    """Resolve an OR-dependency group, returning a TreeNode for the chosen dep."""
    chosen_dep = None
    alternatives: list[str] = []

    for dep in dep_group:
        # Skip system-provided deps
        if dep.name.startswith("/") or ".so" in dep.name or dep.name.startswith("rpmlib(") or dep.name == "rtld(GNU_HASH)":
            return None

        if chosen_dep is None and (dep.name in all_pkgs or dep.name in installed or find_providers(dep.name, all_pkgs)):
            chosen_dep = dep
        else:
            alternatives.append(dep.name)

    if chosen_dep is None:
        # No alternative found — use the first one and let it show as "not found"
        if dep_group:
            chosen_dep = dep_group[0]
            alternatives = [d.name for d in dep_group[1:]]
        else:
            return None

    node = _build_node(chosen_dep.name, all_pkgs, installed, ancestors)
    if alternatives:
        node.or_alternatives = alternatives
    return node
