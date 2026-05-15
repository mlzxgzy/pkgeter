# SQLite Package Cache Design Spec

**Date:** 2026-05-15
**Status:** Draft
**Scope:** Both Debian and RPM backends

## Problem

Every `get`, `search`, or `tree` command re-parses the full package metadata from scratch, even when the source files (Packages.gz / primary.xml.gz) haven't changed. For Debian bookworm main/amd64, this means decompressing ~10-15MB of gzip, decoding ~40-60MB of UTF-8 text, and parsing ~60,000 stanzas into Python dataclass objects — every single time. This takes 3-8 seconds on a typical machine.

The existing `SourceCache` avoids re-downloading by checking SHA256 against the Release file, but the CPU-bound parse step still runs on every invocation.

## Solution

Introduce a SQLite-backed cache layer (`PackageCache`) that stores parsed `PackageInfo` objects. After the first parse, subsequent loads read structured rows from SQLite instead of re-parsing text. SQLite's C engine makes this an order of magnitude faster (~0.3-0.5s vs 3-8s).

Additionally, the `search` command gains SQL LIKE and FTS5 full-text search capabilities, replacing the current O(n) Python dict traversal.

## Approach

**SQLite as a transparent cache layer.** The existing `Dict[str, PackageInfo]` interface that Resolver, Downloader, and other consumers depend on remains unchanged. PackageCache sits between the raw source files and the consumers, caching the parse results.

## Architecture

### New Module: `pkgeter/db/package_cache.py`

Single new module containing the `PackageCache` class. Database file at `~/.config/pkgeter/cache.db`.

### SQLite Schema

**Main table — `packages`:**

```sql
CREATE TABLE IF NOT EXISTS packages (
    source_id   TEXT NOT NULL,
    package     TEXT NOT NULL,
    version     TEXT NOT NULL,
    arch        TEXT DEFAULT '',
    filename    TEXT DEFAULT '',
    sha256      TEXT DEFAULT '',
    size        INTEGER DEFAULT 0,
    description TEXT DEFAULT '',
    depends     TEXT DEFAULT '[]',
    provides    TEXT DEFAULT '[]',
    base_url    TEXT DEFAULT '',
    PRIMARY KEY (source_id, package)
);

CREATE INDEX IF NOT EXISTS idx_packages_name ON packages(package);
```

- `source_id`: composite key like `"deb:deb.debian.org/debian:bookworm:amd64:main"` or `"rpm:<sanitized_url>"`. Uniquely identifies a package source so multiple repos coexist in one database.
- `depends`: JSON-serialized `list[list[dict]]` where each dict has keys `name`, `op`, `ver`. Reconstructed into `list[list[Dependency]]` on load.
- `provides`: JSON-serialized `list[str]`.

**Metadata table — `source_meta`:**

```sql
CREATE TABLE IF NOT EXISTS source_meta (
    source_id     TEXT PRIMARY KEY,
    source_sha256 TEXT NOT NULL,
    package_count INTEGER DEFAULT 0,
    updated_at    REAL NOT NULL
);
```

- `source_sha256`: SHA256 of the raw source file (Packages.gz or primary.xml.gz). Cache is valid when this matches the file on disk.

**FTS5 virtual table (for search):**

```sql
CREATE VIRTUAL TABLE IF NOT EXISTS packages_fts USING fts5(
    package,
    description,
    content='packages',
    content_rowid='rowid'
);
```

- Covers `package` name and `description` fields.
- Content-sync with the `packages` table via triggers (INSERT/DELETE/UPDATE on `packages` automatically update FTS).

**Schema versioning:** Uses SQLite's `PRAGMA user_version`. On version mismatch, the database is deleted and recreated — cached data is regenerable, no migration needed.

### PackageCache Public API

```python
class PackageCache:
    def __init__(self, db_path: Path | None = None):
        """Open or create the cache database.
        Default: ~/.config/pkgeter/cache.db"""

    def is_fresh(self, source_id: str, source_sha256: str) -> bool:
        """Check if the cached data for a source is still valid."""

    def load(self, source_id: str) -> Dict[str, PackageInfo] | None:
        """Load all packages for a source from SQLite.
        Returns Dict[str, PackageInfo] or None if not cached."""

    def store(self, source_id: str, source_sha256: str,
              packages: Dict[str, PackageInfo]) -> None:
        """Write parsed results to SQLite, replacing old data atomically."""

    def search(self, query: str, source_ids: list[str] | None = None,
               search_desc: bool = False) -> list[PackageInfo]:
        """Search packages via SQL.
        Name matching: LIKE '%query%' for plain queries;
        fnmatch wildcards (* → %, ? → _) converted to LIKE patterns.
        Description matching: FTS5 MATCH (when search_desc=True).
        Optional source_ids filter."""

    def clear(self, source_id: str | None = None) -> None:
        """Clear cache for a specific source, or all sources."""
```

### Cache Validation Flow

When a backend needs package data for a source:

1. Compute `source_id` from backend type + mirror + release + arch + component.
2. Obtain the raw source file's SHA256 (already computed by SourceCache for Debian, or from repomd.xml for RPM).
3. Call `PackageCache.is_fresh(source_id, sha256)`.
4. **Fresh** → `PackageCache.load(source_id)` — skip text parsing entirely.
5. **Stale/missing** → parse via existing logic → `PackageCache.store(source_id, sha256, result)`.

### Integration Points

**`pkgeter/backend/__init__.py` (PmBackend base class):**

Add an optional `_cache: PackageCache | None` attribute, lazily initialized on first use. Optionally provide a `_load_or_parse()` template method to reduce duplication between backends.

**`pkgeter/backend/debian.py` (DebianBackend):**

Modify `_download_component()` to insert cache check between `SourceCache.read_packages_gz()` and `_parse_packages_gz()`. The SHA256 comes from `SourceCache._file_sha256()` on the cached Packages.gz file.

**`pkgeter/backend/rpm.py` (RpmBackend):**

Modify `_download_repo()` to insert cache check before `_parse_primary()`. The SHA256 comes from `repomd.xml` (already parsed as `expected_sha256`).

**`pkgeter/search.py`:**

Replace the current `_search_db()` in-memory traversal with `PackageCache.search()`. The search command no longer needs to load the full dict into memory — it queries SQLite directly.

**`pkgeter/repl.py` (session-level in-memory cache):**

Hold a session-level `_package_db_cache: Dict[str, Dict[str, PackageInfo]]` keyed by source_id in the `PkgeterREPL` instance. Within a REPL session, the second `get`/`search` call reuses the in-memory dict without even hitting SQLite. Clear on `force_update` or when the user switches preset/repo.

### Modules NOT Changed

- `pkgeter/models.py` — no changes
- `pkgeter/deps/resolver.py` — still receives `Dict[str, PackageInfo]`
- `pkgeter/deps/virtual.py` — no changes
- `pkgeter/downloader.py` — no changes
- `pkgeter/output/` — no changes

## Error Handling

SQLite cache failures must never block normal operation:

- **Database open/corruption failure** (`sqlite3.Error`): print warning to stderr, fall back to direct text parsing. User experience degrades to "same as no cache" but doesn't crash.
- **Write failure** (disk full, permissions): catch and ignore. Current parse result is still returned normally; it just isn't cached.
- **Schema version mismatch**: delete and recreate the database. Cached data is regenerable.
- **FTS5 unavailable** (stripped SQLite builds): attempt FTS table creation at init. On failure, degrade `search()` to use `LIKE` queries on the main table. Core functionality unaffected.

## Testing

New test file: `tests/test_db/test_package_cache.py`

Test cases:
- `test_store_and_load` — round-trip: store packages, load them back, verify all fields match including depends/provides
- `test_is_fresh` — returns True when SHA256 matches, False when different
- `test_cache_invalidation` — storing with new SHA256 replaces old data for same source_id
- `test_search_by_name` — LIKE search matches package names (substring, case-insensitive)
- `test_search_by_description` — FTS5 search matches description text
- `test_search_with_source_filter` — source_ids parameter limits search scope
- `test_clear` — clear specific source and clear all
- `test_corrupted_db_fallback` — corrupted database file triggers graceful recreation

Existing backend tests should continue to pass with PackageCache mocked or using a temp database.

## File Changes Summary

| File | Change | Description |
|---|---|---|
| `pkgeter/db/package_cache.py` | **New** | PackageCache class with SQLite read/write + FTS5 search |
| `pkgeter/backend/__init__.py` | Modify | Add optional `_cache` attribute to PmBackend |
| `pkgeter/backend/debian.py` | Modify | Insert cache check in `_download_component()` |
| `pkgeter/backend/rpm.py` | Modify | Insert cache check in `_download_repo()` |
| `pkgeter/search.py` | Modify | Use `PackageCache.search()` instead of in-memory traversal |
| `pkgeter/repl.py` | Modify | Optional session-level in-memory cache |
| `tests/test_db/test_package_cache.py` | **New** | PackageCache unit tests |

## Performance Expectations

| Operation | Before | After |
|---|---|---|
| First load (cold cache) | 3-8s (parse) | 3-8s (parse) + ~0.5s (SQLite write) |
| Subsequent load (warm cache) | 3-8s (re-parse) | ~0.3-0.5s (SQLite read) |
| Search (60K packages) | ~0.5-1s (Python dict traversal) | ~10-50ms (SQL query) |
| REPL second command | 3-8s (re-parse) | ~0ms (in-memory dict) |
