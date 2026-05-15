"""Shared backend resolution logic — unifies how subcommands select a backend."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Dict, List, Optional

from pkgeter.backend import PmBackend
from pkgeter.config import Config
from pkgeter.models import RepoConfig

logger = logging.getLogger(__name__)


@dataclass
class BackendContext:
    """Everything a subcommand needs after resolving the backend."""

    backend: PmBackend
    repos: list[RepoConfig]
    arch: str
    mirror_variant: str
    preset_name: str | None  # e.g. "debian-bookworm", used by search for display


def resolve_backend(
    *,
    distro: Optional[str] = None,
    arch: Optional[str] = None,
    mirror: Optional[str] = None,
    cn: bool = False,
    config: Config,
) -> BackendContext:
    """Resolve config and optional CLI arguments into a ready-to-use backend.

    Handles:
      - Architecture defaulting from config
      - Mirror variant resolution (including ``--cn`` shortcut)
      - ``--distro`` preset lookup with ``@variant`` suffix
      - Config fallback to ``debian-bookworm`` when no repos are configured
      - Backend instantiation (DebianBackend / RpmBackend / DnfBackend)

    Raises
    ------
    ValueError
        If the preset is unknown or the backend name is not recognised.
    """
    # --- Architecture & mirror variant ---
    resolved_arch = arch or config.get("arch", "amd64")
    mirror_variant = mirror or config.get_mirror_variant()
    if cn:
        mirror_variant = "cn"
    logger.debug("Architecture: %s, Mirror variant: %s", resolved_arch, mirror_variant)

    # --- Repos & backend name ---
    from pkgeter.preset import get_preset

    preset_name: str | None = None

    if distro:
        # Build <name>@<variant> string so get_preset applies the variant
        resolved_distro = distro
        if "@" not in resolved_distro and mirror_variant != "default":
            resolved_distro = f"{distro}@{mirror_variant}"
        preset = get_preset(resolved_distro)
        if not preset:
            raise ValueError(f"unknown preset '{distro}'")
        repos_raw: List[Dict] = preset["repos"]
        backend_name: str = preset["backend"]
        resolved_arch = preset.get("arch", resolved_arch)
        preset_name = distro
        logger.debug("Using preset: %s (backend=%s)", resolved_distro, backend_name)
    else:
        repos_dicts = config.get_repos()
        if not repos_dicts:
            fallback = "debian-bookworm"
            if mirror_variant != "default":
                fallback = f"debian-bookworm@{mirror_variant}"
            preset = get_preset(fallback)
            if not preset:
                raise ValueError(f"fallback preset '{fallback}' not found")
            repos_raw = preset["repos"]
            backend_name = preset["backend"]
            preset_name = "debian-bookworm"
            logger.debug("No repos in config, falling back to preset: %s", fallback)
        else:
            repos_raw = repos_dicts
            backend_name = config.get_backend()
            preset_name = config.get_preset_name() or None
            logger.debug("Using repos from config (backend=%s)", backend_name)

    repos = [RepoConfig(**r) if isinstance(r, dict) else r for r in repos_raw]
    logger.debug("Repos: %d configured", len(repos))

    # --- Backend instantiation ---
    if backend_name in ("apt", "debian"):
        from pkgeter.backend.debian import DebianBackend

        backend: PmBackend = DebianBackend()
    elif backend_name == "dnf":
        from pkgeter.backend.rpm import DnfBackend

        backend = DnfBackend()
    elif backend_name == "rpm":
        from pkgeter.backend.rpm import RpmBackend

        backend = RpmBackend()
    else:
        raise ValueError(f"unknown backend '{backend_name}'")

    logger.debug("Backend: %s", type(backend).__name__)
    return BackendContext(
        backend=backend,
        repos=repos,
        arch=resolved_arch,
        mirror_variant=mirror_variant,
        preset_name=preset_name,
    )
