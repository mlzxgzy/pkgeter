"""Dependency tree builder - construct nested tree structures for visualization."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Optional, Set

from pkgeter.deps.virtual import find_providers
from pkgeter.models import Dependency, PackageInfo


@dataclass
class TreeNode:
    """A node in the dependency tree."""

    name: str
    version: str
    children: list[TreeNode] = field(default_factory=list)
    is_circular: bool = False
    is_virtual: bool = False
    is_duplicate: bool = False
    provider: str = ""
    or_alternatives: list[str] = field(default_factory=list)


def _build_provides_index(all_pkgs: Dict[str, PackageInfo]) -> Dict[str, list[str]]:
    """Pre-build virtual-name → provider-names index to avoid repeated full scans."""
    index: Dict[str, list[str]] = {}
    for name, info in all_pkgs.items():
        if info.provides:
            for virt in info.provides:
                index.setdefault(virt, []).append(name)
    for providers in index.values():
        providers.sort()
    return index


def build_dependency_tree(
    pkg_names: list[str],
    all_pkgs: Dict[str, PackageInfo],
    installed: Optional[Set[str]] = None,
) -> list[TreeNode]:
    """Build dependency trees for the given package names.

    Returns one TreeNode per target package, with nested children
    representing the full dependency graph.

    Each package is fully expanded only once. Subsequent occurrences
    become leaf nodes with is_duplicate=True to prevent exponential blowup.
    """
    installed = installed or set()
    provides_index = _build_provides_index(all_pkgs)
    seen: Set[str] = set()
    trees: list[TreeNode] = []
    for name in pkg_names:
        tree = _build_node(name, all_pkgs, installed, ancestors=set(),
                           seen=seen, provides_index=provides_index)
        trees.append(tree)
    return trees


def _find_providers_fast(
    virtual_name: str,
    provides_index: Dict[str, list[str]],
) -> list[str]:
    """O(1) provider lookup using pre-built index."""
    return provides_index.get(virtual_name, [])


def _build_node(
    pkg_name: str,
    all_pkgs: Dict[str, PackageInfo],
    installed: Set[str],
    ancestors: Set[str],
    seen: Set[str],
    provides_index: Dict[str, list[str]],
) -> TreeNode:
    """Recursively build a TreeNode for a single package."""
    # Cycle detection (on current recursion path)
    if pkg_name in ancestors:
        return TreeNode(name=pkg_name, version="", is_circular=True)

    # Installed packages become leaf nodes
    if pkg_name in installed:
        info = all_pkgs.get(pkg_name)
        version = info.version if info else ""
        return TreeNode(name=pkg_name, version=version)

    # Duplicate detection: already expanded elsewhere in the tree
    if pkg_name in seen:
        info = all_pkgs.get(pkg_name)
        version = info.version if info else ""
        return TreeNode(name=pkg_name, version=version, is_duplicate=True)

    info = all_pkgs.get(pkg_name)
    if info is None:
        # Try virtual package resolution
        providers = _find_providers_fast(pkg_name, provides_index)
        if not providers:
            return TreeNode(name=pkg_name, version="(not found)")
        chosen = providers[0]
        real_node = _build_node(chosen, all_pkgs, installed, ancestors,
                                seen=seen, provides_index=provides_index)
        return TreeNode(
            name=pkg_name,
            version="",
            children=real_node.children,
            is_virtual=True,
            provider=chosen,
        )

    seen.add(pkg_name)
    new_ancestors = ancestors | {pkg_name}
    children: list[TreeNode] = []

    if info.depends:
        for dep_group in info.depends:
            child = _resolve_dep_group(dep_group, all_pkgs, installed,
                                       new_ancestors, seen, provides_index)
            if child is not None:
                children.append(child)

    return TreeNode(name=pkg_name, version=info.version, children=children)


def _resolve_dep_group(
    dep_group: list["Dependency"],
    all_pkgs: Dict[str, PackageInfo],
    installed: Set[str],
    ancestors: Set[str],
    seen: Set[str],
    provides_index: Dict[str, list[str]],
) -> TreeNode | None:
    """Resolve an OR-dependency group, returning a TreeNode for the chosen dep."""
    chosen_dep = None
    alternatives: list[str] = []

    for dep in dep_group:
        # Skip system-provided deps
        if dep.name.startswith("/") or ".so" in dep.name or dep.name.startswith("rpmlib(") or dep.name == "rtld(GNU_HASH)":
            return None

        if chosen_dep is None and (dep.name in all_pkgs or dep.name in installed or _find_providers_fast(dep.name, provides_index)):
            chosen_dep = dep
        else:
            alternatives.append(dep.name)

    if chosen_dep is None:
        if dep_group:
            chosen_dep = dep_group[0]
            alternatives = [d.name for d in dep_group[1:]]
        else:
            return None

    node = _build_node(chosen_dep.name, all_pkgs, installed, ancestors,
                        seen=seen, provides_index=provides_index)
    if alternatives:
        node.or_alternatives = alternatives
    return node
