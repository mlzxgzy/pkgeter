"""Dependency resolution engine - recursively resolve package dependencies."""

from __future__ import annotations

from typing import Callable, Dict, List, Optional, Set

from pkgeter.deps.virtual import find_providers
from pkgeter.models import PackageInfo


class Resolver:
    """Recursively resolve all dependencies for a set of target packages."""

    def __init__(
        self,
        all_pkgs: Dict[str, PackageInfo],
        installed: Optional[Set[str]] = None,
        virtual_callback: Optional[Callable[[str, list[str]], str]] = None,
    ):
        self.all_pkgs = all_pkgs
        self.installed = installed or set()
        self.virtual_callback = virtual_callback or self._default_virtual_handler
        self._visited: Set[str] = set()

    def resolve(self, pkg_names: list[str]) -> List[str]:
        """Resolve all dependencies for the given package names.

        Returns a list of package names in dependency order
        (dependencies before dependents), including the target packages
        themselves. Can be used directly for dpkg -i ordering.
        """
        result: List[str] = []
        self._visited = set()
        for name in pkg_names:
            resolved = self._resolve_one(name)
            for pkg in resolved:
                if pkg not in result:
                    result.append(pkg)
        return result

    def _resolve_one(
        self,
        pkg_name: str,
    ) -> List[str]:
        """Recursively resolve a single package.

        Returns a list with the package and its dependencies in
        dependency order (dependencies come first).
        """
        if pkg_name in self._visited:
            return []
        if pkg_name in self.installed:
            return []

        info = self.all_pkgs.get(pkg_name)
        if info is None:
            # May be a virtual package
            providers = find_providers(pkg_name, self.all_pkgs)
            if not providers:
                raise ValueError(
                    f"Package '{pkg_name}' not found in repository "
                    f"and is not provided by any known package."
                )
            chosen = self.virtual_callback(pkg_name, providers)
            self._visited.add(pkg_name)
            return self._resolve_one(chosen)

        self._visited.add(pkg_name)
        result: List[str] = []

        # Process each dependency group
        if info.depends:
            for dep_group in info.depends:
                # OR dependency: try each alternative, use first available
                resolved_one = False
                for dep in dep_group:
                    try:
                        sub_deps = self._resolve_one(dep.name)
                        result.extend(sub_deps)
                        resolved_one = True
                        break
                    except ValueError:
                        continue
                if not resolved_one:
                    names = [d.name for d in dep_group]
                    raise ValueError(
                        f"Cannot resolve dependency '{' | '.join(names)}' "
                        f"for package '{pkg_name}'"
                    )

        result.append(pkg_name)
        return result

    def _default_virtual_handler(self, virtual_name: str, providers: list[str]) -> str:
        """Default: pick the first provider (for automated/headless use)."""
        if not providers:
            raise ValueError(f"No providers for virtual package '{virtual_name}'")
        return providers[0]
