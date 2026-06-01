"""In-memory session cache — keeps loaded package DB across REPL commands.

Reusing the backend and parsed package database avoids re-hashing cached
metadata and re-loading from SQLite on every command in the same session.
"""

from __future__ import annotations

import hashlib
import json
from typing import Dict

from pkgeter.config import Config
from pkgeter.context import BackendContext, resolve_backend
from pkgeter.models import PackageInfo


class SessionCache:
    """Holds a loaded package database so consecutive commands skip loading.

    Usage::

        cache = SessionCache()
        result = cache.get_or_load(config, force_update=False)
        if result:
            ctx, merged_db = result
    """

    def __init__(self) -> None:
        self._config_hash: str = ""
        self._ctx: BackendContext | None = None
        self._merged_db: Dict[str, PackageInfo] | None = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_or_load(
        self,
        config: Config,
        force_update: bool = False,
    ) -> tuple[BackendContext, Dict[str, PackageInfo] | None] | None:
        """Return cached context+DB, or load fresh if config changed."""
        ch = self._hash_config(config)

        if self._ctx is not None and self._config_hash == ch and not force_update:
            return self._ctx, self._merged_db

        # Load fresh
        try:
            ctx = resolve_backend(config=config)
        except ValueError:
            return None

        merged_db = ctx.backend.download_package_db(ctx.repos, ctx.arch, force_update=force_update)

        self._config_hash = ch
        self._ctx = ctx
        self._merged_db = merged_db
        return ctx, merged_db

    def invalidate(self) -> None:
        """Drop the cached session (call when config/repos change)."""
        self._config_hash = ""
        self._ctx = None
        self._merged_db = None

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    @staticmethod
    def _hash_config(config: Config) -> str:
        """Deterministic hash of the config values that affect package DB loading."""
        repos_raw = config.get_repos()
        canonical = {
            "backend": config.get_backend(),
            "arch": config.get("arch"),
            "mirror_variant": config.get_mirror_variant(),
            "preset_name": config.get_preset_name(),
            "repos": sorted(
                (r.get("name", ""), r.get("url", ""), r.get("release", ""), r.get("arch", ""))
                for r in repos_raw
            ),
        }
        return hashlib.sha256(
            json.dumps(canonical, sort_keys=True, ensure_ascii=False).encode()
        ).hexdigest()


# Module-level singleton — shared across REPL commands and CLI calls
_global_session: SessionCache | None = None


def get_session_cache() -> SessionCache:
    """Return the global session cache (lazily created)."""
    global _global_session
    if _global_session is None:
        _global_session = SessionCache()
    return _global_session


def invalidate_session_cache() -> None:
    """Drop the global session cache (call when config/repos change)."""
    global _global_session
    if _global_session is not None:
        _global_session.invalidate()
