"""Dependency resolution engine - recursively resolve package dependencies."""

from __future__ import annotations

from typing import TYPE_CHECKING, Callable, Dict, List, Optional, Set

from pkgeter.deps.virtual import find_providers
from pkgeter.models import PackageInfo

if TYPE_CHECKING:
    from pkgeter.deps.provides_index import ProvidesIndex


class Resolver:
    """Recursively resolve all dependencies for a set of target packages."""

    def __init__(
        self,
        all_pkgs: Dict[str, PackageInfo],
        installed: Optional[Set[str]] = None,
        virtual_callback: Optional[Callable[[str, list[str]], str]] = None,
        provides_index: Optional["ProvidesIndex"] = None,
    ):
        self.all_pkgs = all_pkgs
        self.installed = installed or set()
        self.virtual_callback = virtual_callback or self._default_virtual_handler
        self.provides_index = provides_index
        self._visited: Set[str] = set()
        self.skipped: Dict[str, List[str]] = {}  # pkg_name -> [skipped dep names]

    def resolve(self, pkg_names: list[str]) -> List[str]:
        """Resolve all dependencies for the given package names.

        Returns a list of package names in dependency order
        (dependencies before dependentsls
      ), including the target packages
        themselves. Can be used directly for dpkg -i ordering.
        """
        result: List[str] = []
        self._visited = set()
        self.skipped = {}
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
            # May be a virtual package — use index (O(1)) or linear scan
            if self.provides_index is not None:
                providers = self.provides_index.find(pkg_name)
            else:
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
                has_soft_dep = False
                for dep in dep_group:
                    # RPM-internal markers — always skip
                    if dep.name.startswith("rpmlib(") or dep.name == "rtld(GNU_HASH)":
                        resolved_one = True
                        break

                    # Sonames and file paths are "soft" deps: resolve if
                    # possible (via provides), but tolerate missing ones
                    # (assumed provided by the base system).
                    is_soft = dep.name.startswith("/") or ".so" in dep.name
                    if is_soft:
                        has_soft_dep = True

                    try:
                        sub_deps = self._resolve_one(dep.name)
                        result.extend(sub_deps)
                        resolved_one = True
                        break
                    except ValueError:
                        if is_soft:
                            # Soft dep didn't resolve via name/provides — try
                            # extracting a package name candidate as fallback.
                            fallback = self._resolve_soft_dep_fallback(dep.name)
                            if fallback is not None:
                                result.extend(fallback)
                                resolved_one = True
                                break
                        continue
                if not resolved_one:
                    if has_soft_dep:
                        skipped_names = [d.name for d in dep_group if d.name.startswith("/") or ".so" in d.name]
                        if skipped_names:
                            self.skipped.setdefault(pkg_name, []).extend(skipped_names)
                        continue
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

    @staticmethod
    def _extract_pkg_candidate(dep_name: str) -> str | None:
        """Extract a package name candidate from a soft dependency string.

        For file paths (``/usr/bin/perl``) extracts the basename ``perl``.
        For sonames with architecture annotations (``libfoo.so.3()(64bit)``)
        strips the annotation to produce ``libfoo.so.3``.
        """
        if dep_name.startswith("/"):
            base = dep_name.rsplit("/", 1)[-1]
            return base if base else None
        if ".so" in dep_name:
            # Strip architecture annotations like ()64bit
            base = dep_name.split("(")[0] if "(" in dep_name else dep_name
            return base if base else None
        return None

    def _resolve_soft_dep_fallback(self, dep_name: str) -> list[str] | None:
        """Try to resolve a soft dependency by extracting a package-name
        candidate and resolving that.

        Called after the standard resolution path for *dep_name* (direct
        package lookup followed by provides-index query) raises
        :class:`ValueError`.

        Returns the resolved package list, or ``None`` when no fallback
        candidate could be resolved.
        """
        candidate = self._extract_pkg_candidate(dep_name)
        if candidate is None or candidate == dep_name:
            return None
        try:
            return self._resolve_one(candidate)
        except ValueError:
            return None
