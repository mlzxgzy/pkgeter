"""Dependency tree builder - construct nested tree structures for visualization."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Dict, Optional, Set

from pkgeter.deps.virtual import find_providers
from pkgeter.models import Dependency, PackageInfo

if TYPE_CHECKING:
    from pkgeter.deps.provides_index import ProvidesIndex


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
    reverse_deps: list[str] = field(default_factory=list)
    install_layer: int = 0


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
    external_index: Optional["ProvidesIndex"] = None,
) -> list[TreeNode]:
    """Build dependency trees for the given package names.

    Returns one TreeNode per target package, with nested children
    representing the full dependency graph.

    Each package is fully expanded only once. Subsequent occurrences
    become leaf nodes with is_duplicate=True to prevent exponential blowup.

    When *external_index* is provided (a :class:`ProvidesIndex` built from
    primary.xml provides + filelists.xml.gz), it is used alongside the
    internal provides index for O(1) lookups that cover both sonames and
    file paths.
    """
    installed = installed or set()
    provides_index = _build_provides_index(all_pkgs)
    seen: Set[str] = set()
    trees: list[TreeNode] = []
    for name in pkg_names:
        tree = _build_node(name, all_pkgs, installed, ancestors=set(),
                           seen=seen, provides_index=provides_index,
                           external_index=external_index)
        trees.append(tree)
    return trees


def build_install_order_trees(trees: list[TreeNode]) -> list[TreeNode]:
    """Build deduplicated install-order trees from the full dependency trees.

    Algorithm:
    1. Walk all (parent->child) edges from the full trees, collecting unique pkgs
    2. Build forward index (pkg->its deps) and reverse index (pkg->its dependents)
    3. Roots = packages with no dependencies of their own (foundation libs)
    4. For each root, BFS through the reverse index to grow a tree:
       children = packages that depend on the root, each assigned exactly once
    5. Nodes get install_layer (distance from root) and reverse_deps populated
    """
    # Step 1: Walk all trees, collect edges + versions
    edges: set[tuple[str, str]] = set()  # (parent, child) = parent depends on child
    all_names: set[str] = set()
    versions: dict[str, str] = {}

    def _walk(node: TreeNode, parent_name: str | None = None) -> None:
        # If the node is virtual, use the actual provider name instead
        actual_name = node.provider if node.is_virtual and node.provider else node.name
        all_names.add(actual_name)
        if actual_name not in versions or not versions[actual_name]:
            versions[actual_name] = node.version if not node.is_virtual else ""
        if parent_name is not None:
            edges.add((parent_name, actual_name))
        for child in node.children:
            _walk(child, actual_name)

    for tree in trees:
        _walk(tree)

    if not all_names:
        return []

    # Step 2: Build indexes
    reverse: dict[str, set[str]] = {p: set() for p in all_names}
    forward: dict[str, set[str]] = {p: set() for p in all_names}

    for parent, child in edges:
        reverse[child].add(parent)
        forward[parent].add(child)

    # Step 3: Find roots = packages with no deps of their own
    roots = sorted(p for p in all_names if not forward[p])

    # Also handle packages that aren't in any edge
    orphan_roots = sorted(all_names - set(forward.keys()) - set(reverse.keys()))
    roots.extend(o for o in orphan_roots if o not in roots)

    # Step 4: Build reverse-dep trees using BFS, assigning each pkg exactly once
    assigned: set[str] = set(roots)
    root_trees: list[TreeNode] = []

    for root in roots:
        root_node = TreeNode(
            name=root,
            version=versions.get(root, ""),
            install_layer=0,
            reverse_deps=sorted(reverse.get(root, set())),
        )
        queue = deque([(root_node, root, 0)])
        visited_local = {root}

        while queue:
            parent_node, parent_name, layer = queue.popleft()
            for dependent in sorted(reverse.get(parent_name, set())):
                if dependent not in visited_local and dependent not in assigned:
                    visited_local.add(dependent)
                    assigned.add(dependent)
                    child_node = TreeNode(
                        name=dependent,
                        version=versions.get(dependent, ""),
                        install_layer=layer + 1,
                        reverse_deps=sorted(reverse.get(dependent, set())),
                    )
                    parent_node.children.append(child_node)
                    queue.append((child_node, dependent, layer + 1))

        root_trees.append(root_node)

    # Step 5: Handle any remaining unassigned packages
    remaining = sorted(all_names - assigned)
    for name in remaining:
        root_trees.append(TreeNode(
            name=name,
            version=versions.get(name, ""),
            install_layer=0,
            reverse_deps=sorted(reverse.get(name, set())),
        ))

    return root_trees


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
    external_index: Optional["ProvidesIndex"] = None,
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
        # Try virtual package resolution (external index first, then internal)
        providers = (external_index.find(pkg_name) if external_index else []) or _find_providers_fast(pkg_name, provides_index)
        if not providers:
            return TreeNode(name=pkg_name, version="(not found)")
        chosen = providers[0]
        real_node = _build_node(chosen, all_pkgs, installed, ancestors,
                                seen=seen, provides_index=provides_index,
                                external_index=external_index)
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
                                       new_ancestors, seen, provides_index,
                                       external_index=external_index)
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
    external_index: Optional["ProvidesIndex"] = None,
) -> TreeNode | None:
    """Resolve an OR-dependency group, returning a TreeNode for the chosen dep."""
    chosen_dep = None
    alternatives: list[str] = []
    has_soft_dep = False

    for dep in dep_group:
        # RPM-internal markers — always skip
        if dep.name.startswith("rpmlib(") or dep.name == "rtld(GNU_HASH)":
            return None

        is_soft = dep.name.startswith("/") or ".so" in dep.name
        if is_soft:
            has_soft_dep = True

        def _can_resolve(name: str) -> bool:
            if name in all_pkgs or name in installed:
                return True
            if external_index and external_index.find(name):
                return True
            if _find_providers_fast(name, provides_index):
                return True
            return False

        if chosen_dep is None and _can_resolve(dep.name):
            chosen_dep = dep
        else:
            alternatives.append(dep.name)

    if chosen_dep is None:
        if has_soft_dep:
            return None
        if dep_group:
            chosen_dep = dep_group[0]
            alternatives = [d.name for d in dep_group[1:]]
        else:
            return None

    node = _build_node(chosen_dep.name, all_pkgs, installed, ancestors,
                        seen=seen, provides_index=provides_index,
                        external_index=external_index)
    if alternatives:
        node.or_alternatives = alternatives
    return node
