"""Virtual package resolution - find providers for virtual packages."""

from __future__ import annotations

from typing import Dict, List

from pkgeter.models import PackageInfo


def find_providers(virtual_name: str, all_pkgs: Dict[str, PackageInfo]) -> List[str]:
    """Find all real packages that provide the given virtual package.

    Returns a sorted list of provider package names.
    """
    providers: List[str] = []
    for name, info in all_pkgs.items():
        if info.provides and virtual_name in info.provides:
            providers.append(name)
    return sorted(providers)


def resolve_virtual_interactive(
    virtual_name: str,
    providers: List[str],
    all_pkgs: Dict[str, PackageInfo],
) -> str:
    """Prompt user to choose a provider for the virtual package.

    Uses stdin/stdout for CLI mode. Returns the chosen package name.
    """
    print(f"\nPackage '{virtual_name}' is a virtual package.")
    print(f"The following packages provide '{virtual_name}':")
    for i, name in enumerate(providers, 1):
        desc = all_pkgs[name].description[:60] if all_pkgs[name].description else ""
        print(f"  {i}. {name}  - {desc}")

    while True:
        try:
            choice = input(f"Select provider (1-{len(providers)}): ").strip()
            idx = int(choice) - 1
            if 0 <= idx < len(providers):
                return providers[idx]
            print(f"Please enter a number between 1 and {len(providers)}")
        except (ValueError, EOFError):
            print("Invalid input, try again.")
