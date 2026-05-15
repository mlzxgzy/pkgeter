# SQLite Package Cache Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace repeated text parsing of Packages.gz / primary.xml.gz with a SQLite cache layer, cutting load times from 3-8s to ~0.3s and enabling SQL-based search.

**Architecture:** New `PackageCache` class in `pkgeter/db/package_cache.py` manages a SQLite database at `~/.config/pkgeter/cache.db`. Backends check the cache before parsing; if the source file's SHA256 matches the cached entry, rows are loaded from SQLite instead of re-parsing text. Search uses FTS5 for description matching and LIKE for name matching.

**Tech Stack:** Python 3.10+, sqlite3 (stdlib), json (stdlib). No new dependencies.

**Spec:** `docs/superpowers/specs/2026-05-15-sqlite-package-cache-design.md`

---

## File Structure

| File | Role |
|---|---|
| `pkgeter/db/package_cache.py` | **New.** PackageCache class — SQLite schema, store/load/search/clear operations, FTS5 support with graceful fallback. |
| `pkgeter/backend/__init__.py` | **Modify.** Add lazy `_cache` property to PmBackend base class. |
| `pkgeter/backend/debian.py` | **Modify.** Insert cache check in `_download_component()` (lines 211-246). |
| `pkgeter/backend/rpm.py` | **Modify.** Insert cache check in `_download_repo()` (lines 205-268). |
| `pkgeter/search.py` | **Modify.** Replace `_search_db()` (lines 15-33) and the per-repo loop in `run_search()` (lines 115-133) with `PackageCache.search()`. |
| `pkgeter/repl.py` | **Modify.** Not in current scope — deferred to a follow-up since get/search currently instantiate their own backends without passing state through the REPL. |
| `tests/test_db/test_package_cache.py` | **New.** Unit tests for PackageCache. |

---

### Task 1: PackageCache — Schema, Store, and Freshness Check

**Files:**
- Create: `pkgeter/db/package_cache.py`
- Create: `tests/test_db/test_package_cache.py`

- [ ] **Step 1: Write failing tests for store and is_fresh**

Create `tests/test_db/test_package_cache.py`:

```python
"""Tests for the SQLite package cache."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pkgeter.models import Dependency, PackageInfo


@pytest.fixture
def cache(tmp_path):
    from pkgeter.db.package_cache import PackageCache
    return PackageCache(db_path=tmp_path / "test_cache.db")


@pytest.fixture
def sample_packages() -> dict[str, PackageInfo]:
    return {
        "nginx": PackageInfo(
            package="nginx",
            version="1.22.1-9",
            arch="amd64",
            filename="pool/main/n/nginx/nginx_1.22.1-9_amd64.deb",
            sha256="abc123",
            size=123456,
            description="Small, powerful, scalable web/proxy server",
            depends=[
                [Dependency(name="libc6", version_operator=">=", version="2.34")],
                [Dependency(name="libpcre2-8-0"), Dependency(name="libpcre3")],
            ],
            provides=["httpd", "httpd-cgi"],
            base_url="https://deb.debian.org/debian",
        ),
        "curl": PackageInfo(
            package="curl",
            version="7.88.1-10",
            arch="amd64",
            filename="pool/main/c/curl/curl_7.88.1-10_amd64.deb",
            sha256="def456",
            size=456789,
            description="command line tool for transferring data with URL syntax",
            depends=[
                [Dependency(name="libcurl4", version_operator="=", version="7.88.1-10")],
            ],
            provides=[],
            base_url="https://deb.debian.org/debian",
        ),
    }


SOURCE_ID = "deb:deb.debian.org/debian:bookworm:amd64:main"
SOURCE_SHA = "aabbccdd" * 8


class TestStoreAndFresh:
    def test_is_fresh_returns_false_when_empty(self, cache):
        assert cache.is_fresh(SOURCE_ID, SOURCE_SHA) is False

    def test_store_then_is_fresh(self, cache, sample_packages):
        cache.store(SOURCE_ID, SOURCE_SHA, sample_packages)
        assert cache.is_fresh(SOURCE_ID, SOURCE_SHA) is True

    def test_is_fresh_returns_false_for_different_sha(self, cache, sample_packages):
        cache.store(SOURCE_ID, SOURCE_SHA, sample_packages)
        assert cache.is_fresh(SOURCE_ID, "different_sha") is False

    def test_store_replaces_old_data(self, cache, sample_packages):
        cache.store(SOURCE_ID, "old_sha", sample_packages)
        new_pkgs = {"only-one": sample_packages["nginx"]}
        cache.store(SOURCE_ID, "new_sha", new_pkgs)
        assert cache.is_fresh(SOURCE_ID, "new_sha") is True
        assert cache.is_fresh(SOURCE_ID, "old_sha") is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_db/test_package_cache.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'pkgeter.db.package_cache'`

- [ ] **Step 3: Implement PackageCache with schema, store(), and is_fresh()**

Create `pkgeter/db/package_cache.py`:

```python
"""SQLite-backed cache for parsed package metadata.

Stores parsed PackageInfo objects so that subsequent loads read structured
rows from SQLite instead of re-parsing Packages.gz / primary.xml.gz.
"""

from __future__ import annotations

import json
import sqlite3
import sys
import time
from pathlib import Path
from typing import Dict

from pkgeter.config import CONFIG_PATH
from pkgeter.models import Dependency, PackageInfo

CACHE_DB_PATH = CONFIG_PATH.parent / "cache.db"
_SCHEMA_VERSION = 1


def _serialize_depends(depends: list[list[Dependency]]) -> str:
    groups = []
    for group in depends:
        groups.append(
            [{"name": d.name, "op": d.version_operator, "ver": d.version} for d in group]
        )
    return json.dumps(groups)


def _deserialize_depends(raw: str) -> list[list[Dependency]]:
    groups = json.loads(raw) if raw else []
    result: list[list[Dependency]] = []
    for group in groups:
        result.append(
            [Dependency(name=d["name"], version_operator=d.get("op"), version=d.get("ver")) for d in group]
        )
    return result


def _serialize_provides(provides: list[str]) -> str:
    return json.dumps(provides)


def _deserialize_provides(raw: str) -> list[str]:
    return json.loads(raw) if raw else []


class PackageCache:
    """SQLite-backed cache for parsed package metadata."""

    def __init__(self, db_path: Path | None = None):
        self._db_path = db_path or CACHE_DB_PATH
        self._fts_available = False
        try:
            self._db_path.parent.mkdir(parents=True, exist_ok=True)
            self._conn = sqlite3.connect(str(self._db_path))
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._ensure_schema()
        except sqlite3.Error as exc:
            print(f"Warning: cache database unavailable: {exc}", file=sys.stderr)
            self._conn = None

    def _ensure_schema(self) -> None:
        if self._conn is None:
            return
        cur = self._conn.execute("PRAGMA user_version")
        version = cur.fetchone()[0]
        if version != 0 and version != _SCHEMA_VERSION:
            self._conn.close()
            self._db_path.unlink(missing_ok=True)
            self._conn = sqlite3.connect(str(self._db_path))
            self._conn.execute("PRAGMA journal_mode=WAL")

        self._conn.executescript("""
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

            CREATE TABLE IF NOT EXISTS source_meta (
                source_id     TEXT PRIMARY KEY,
                source_sha256 TEXT NOT NULL,
                package_count INTEGER DEFAULT 0,
                updated_at    REAL NOT NULL
            );
        """)
        self._conn.execute(f"PRAGMA user_version = {_SCHEMA_VERSION}")

        try:
            self._conn.executescript("""
                CREATE VIRTUAL TABLE IF NOT EXISTS packages_fts USING fts5(
                    package,
                    description,
                    content='packages',
                    content_rowid='rowid'
                );

                CREATE TRIGGER IF NOT EXISTS packages_ai AFTER INSERT ON packages BEGIN
                    INSERT INTO packages_fts(rowid, package, description)
                    VALUES (new.rowid, new.package, new.description);
                END;
                CREATE TRIGGER IF NOT EXISTS packages_ad AFTER DELETE ON packages BEGIN
                    INSERT INTO packages_fts(packages_fts, rowid, package, description)
                    VALUES ('delete', old.rowid, old.package, old.description);
                END;
            """)
            self._fts_available = True
        except sqlite3.OperationalError:
            self._fts_available = False

        self._conn.commit()

    def is_fresh(self, source_id: str, source_sha256: str) -> bool:
        if self._conn is None:
            return False
        cur = self._conn.execute(
            "SELECT source_sha256 FROM source_meta WHERE source_id = ?",
            (source_id,),
        )
        row = cur.fetchone()
        return row is not None and row[0] == source_sha256

    def store(self, source_id: str, source_sha256: str,
              packages: Dict[str, PackageInfo]) -> None:
        if self._conn is None:
            return
        try:
            with self._conn:
                self._conn.execute(
                    "DELETE FROM packages WHERE source_id = ?", (source_id,),
                )
                self._conn.executemany(
                    """INSERT INTO packages
                       (source_id, package, version, arch, filename, sha256,
                        size, description, depends, provides, base_url)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    [
                        (
                            source_id,
                            pkg.package,
                            pkg.version,
                            pkg.arch,
                            pkg.filename,
                            pkg.sha256,
                            pkg.size,
                            pkg.description,
                            _serialize_depends(pkg.depends),
                            _serialize_provides(pkg.provides),
                            pkg.base_url,
                        )
                        for pkg in packages.values()
                    ],
                )
                self._conn.execute(
                    """INSERT OR REPLACE INTO source_meta
                       (source_id, source_sha256, package_count, updated_at)
                       VALUES (?, ?, ?, ?)""",
                    (source_id, source_sha256, len(packages), time.time()),
                )
        except sqlite3.Error as exc:
            print(f"Warning: cache write failed: {exc}", file=sys.stderr)

    def load(self, source_id: str) -> Dict[str, PackageInfo] | None:
        raise NotImplementedError("Task 2")

    def search(self, query: str, source_ids: list[str] | None = None,
               search_desc: bool = False) -> list[PackageInfo]:
        raise NotImplementedError("Task 3")

    def clear(self, source_id: str | None = None) -> None:
        raise NotImplementedError("Task 3")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_db/test_package_cache.py -v`
Expected: All 4 tests PASS

- [ ] **Step 5: Commit**

```bash
git add pkgeter/db/package_cache.py tests/test_db/test_package_cache.py
git commit -m "feat(cache): add PackageCache with SQLite schema, store(), and is_fresh()"
```

---

### Task 2: PackageCache — Load and Clear

**Files:**
- Modify: `pkgeter/db/package_cache.py` (replace `load()` and `clear()` stubs)
- Modify: `tests/test_db/test_package_cache.py`

- [ ] **Step 1: Write failing tests for load and clear**

Append to `tests/test_db/test_package_cache.py`:

```python
class TestLoad:
    def test_load_returns_none_when_empty(self, cache):
        assert cache.load(SOURCE_ID) is None

    def test_load_round_trip(self, cache, sample_packages):
        cache.store(SOURCE_ID, SOURCE_SHA, sample_packages)
        loaded = cache.load(SOURCE_ID)
        assert loaded is not None
        assert set(loaded.keys()) == {"nginx", "curl"}

        nginx = loaded["nginx"]
        assert nginx.package == "nginx"
        assert nginx.version == "1.22.1-9"
        assert nginx.arch == "amd64"
        assert nginx.filename == "pool/main/n/nginx/nginx_1.22.1-9_amd64.deb"
        assert nginx.sha256 == "abc123"
        assert nginx.size == 123456
        assert nginx.description == "Small, powerful, scalable web/proxy server"
        assert nginx.base_url == "https://deb.debian.org/debian"

        # Verify depends round-trip
        assert len(nginx.depends) == 2
        assert nginx.depends[0][0].name == "libc6"
        assert nginx.depends[0][0].version_operator == ">="
        assert nginx.depends[0][0].version == "2.34"
        assert len(nginx.depends[1]) == 2  # OR group
        assert nginx.depends[1][0].name == "libpcre2-8-0"
        assert nginx.depends[1][1].name == "libpcre3"

        # Verify provides round-trip
        assert nginx.provides == ["httpd", "httpd-cgi"]

    def test_load_empty_depends_and_provides(self, cache, sample_packages):
        cache.store(SOURCE_ID, SOURCE_SHA, sample_packages)
        loaded = cache.load(SOURCE_ID)
        curl = loaded["curl"]
        assert curl.provides == []
        assert len(curl.depends) == 1


class TestClear:
    def test_clear_specific_source(self, cache, sample_packages):
        other_id = "deb:other:bookworm:amd64:main"
        cache.store(SOURCE_ID, SOURCE_SHA, sample_packages)
        cache.store(other_id, "other_sha", {"curl": sample_packages["curl"]})

        cache.clear(SOURCE_ID)
        assert cache.load(SOURCE_ID) is None
        assert cache.load(other_id) is not None

    def test_clear_all(self, cache, sample_packages):
        other_id = "deb:other:bookworm:amd64:main"
        cache.store(SOURCE_ID, SOURCE_SHA, sample_packages)
        cache.store(other_id, "other_sha", {"curl": sample_packages["curl"]})

        cache.clear()
        assert cache.load(SOURCE_ID) is None
        assert cache.load(other_id) is None
```

- [ ] **Step 2: Run tests to verify new tests fail**

Run: `pytest tests/test_db/test_package_cache.py::TestLoad -v`
Expected: FAIL — `NotImplementedError: Task 2`

- [ ] **Step 3: Implement load() and clear()**

Replace the `load()` and `clear()` stubs in `pkgeter/db/package_cache.py`:

```python
    def load(self, source_id: str) -> Dict[str, PackageInfo] | None:
        if self._conn is None:
            return None
        cur = self._conn.execute(
            """SELECT package, version, arch, filename, sha256, size,
                      description, depends, provides, base_url
               FROM packages WHERE source_id = ?""",
            (source_id,),
        )
        rows = cur.fetchall()
        if not rows:
            return None
        packages: Dict[str, PackageInfo] = {}
        for row in rows:
            (name, version, arch, filename, sha256, size,
             description, depends_raw, provides_raw, base_url) = row
            packages[name] = PackageInfo(
                package=name,
                version=version,
                arch=arch,
                filename=filename,
                sha256=sha256,
                size=size,
                description=description,
                depends=_deserialize_depends(depends_raw),
                provides=_deserialize_provides(provides_raw),
                base_url=base_url,
            )
        return packages

    def clear(self, source_id: str | None = None) -> None:
        if self._conn is None:
            return
        try:
            with self._conn:
                if source_id is not None:
                    self._conn.execute("DELETE FROM packages WHERE source_id = ?", (source_id,))
                    self._conn.execute("DELETE FROM source_meta WHERE source_id = ?", (source_id,))
                else:
                    self._conn.execute("DELETE FROM packages")
                    self._conn.execute("DELETE FROM source_meta")
        except sqlite3.Error as exc:
            print(f"Warning: cache clear failed: {exc}", file=sys.stderr)
```

- [ ] **Step 4: Run all tests to verify they pass**

Run: `pytest tests/test_db/test_package_cache.py -v`
Expected: All tests PASS (TestStoreAndFresh + TestLoad + TestClear)

- [ ] **Step 5: Commit**

```bash
git add pkgeter/db/package_cache.py tests/test_db/test_package_cache.py
git commit -m "feat(cache): add PackageCache.load() and clear()"
```

---

### Task 3: PackageCache — Search (LIKE + FTS5)

**Files:**
- Modify: `pkgeter/db/package_cache.py` (replace `search()` stub)
- Modify: `tests/test_db/test_package_cache.py`

- [ ] **Step 1: Write failing tests for search**

Append to `tests/test_db/test_package_cache.py`:

```python
class TestSearch:
    def test_search_by_name_substring(self, cache, sample_packages):
        cache.store(SOURCE_ID, SOURCE_SHA, sample_packages)
        results = cache.search("ngi")
        assert len(results) == 1
        assert results[0].package == "nginx"

    def test_search_by_name_case_insensitive(self, cache, sample_packages):
        cache.store(SOURCE_ID, SOURCE_SHA, sample_packages)
        results = cache.search("CURL")
        assert len(results) == 1
        assert results[0].package == "curl"

    def test_search_wildcard_star(self, cache, sample_packages):
        cache.store(SOURCE_ID, SOURCE_SHA, sample_packages)
        results = cache.search("ng*")
        names = [r.package for r in results]
        assert "nginx" in names

    def test_search_wildcard_question(self, cache, sample_packages):
        cache.store(SOURCE_ID, SOURCE_SHA, sample_packages)
        results = cache.search("cur?")
        assert len(results) == 1
        assert results[0].package == "curl"

    def test_search_description(self, cache, sample_packages):
        cache.store(SOURCE_ID, SOURCE_SHA, sample_packages)
        results = cache.search("proxy", search_desc=True)
        assert len(results) >= 1
        assert any(r.package == "nginx" for r in results)

    def test_search_with_source_filter(self, cache, sample_packages):
        other_id = "deb:other:bookworm:amd64:main"
        cache.store(SOURCE_ID, SOURCE_SHA, sample_packages)
        cache.store(other_id, "other_sha", {"curl": sample_packages["curl"]})

        results = cache.search("curl", source_ids=[other_id])
        assert len(results) == 1

        results_all = cache.search("curl")
        assert len(results_all) >= 1

    def test_search_no_results(self, cache, sample_packages):
        cache.store(SOURCE_ID, SOURCE_SHA, sample_packages)
        results = cache.search("nonexistent_xyz")
        assert results == []
```

- [ ] **Step 2: Run tests to verify new tests fail**

Run: `pytest tests/test_db/test_package_cache.py::TestSearch -v`
Expected: FAIL — `NotImplementedError: Task 3`

- [ ] **Step 3: Implement search()**

Replace the `search()` stub in `pkgeter/db/package_cache.py`:

```python
    def search(self, query: str, source_ids: list[str] | None = None,
               search_desc: bool = False) -> list[PackageInfo]:
        if self._conn is None:
            return []

        has_wildcards = "*" in query or "?" in query
        q_lower = query.lower()

        if has_wildcards:
            like_pattern = q_lower.replace("*", "%").replace("?", "_")
        else:
            like_pattern = f"%{q_lower}%"

        # Name search via LIKE
        if source_ids:
            placeholders = ",".join("?" for _ in source_ids)
            sql = f"""SELECT package, version, arch, filename, sha256, size,
                             description, depends, provides, base_url, source_id
                      FROM packages
                      WHERE LOWER(package) LIKE ? AND source_id IN ({placeholders})"""
            params: list = [like_pattern] + source_ids
        else:
            sql = """SELECT package, version, arch, filename, sha256, size,
                            description, depends, provides, base_url, source_id
                     FROM packages
                     WHERE LOWER(package) LIKE ?"""
            params = [like_pattern]

        cur = self._conn.execute(sql, params)
        results = self._rows_to_packages(cur.fetchall())

        # Description search via FTS5 (or LIKE fallback)
        if search_desc and not has_wildcards:
            desc_results = self._search_description(q_lower, source_ids)
            seen = {r.package for r in results}
            for pkg in desc_results:
                if pkg.package not in seen:
                    results.append(pkg)
                    seen.add(pkg.package)

        return results

    def _search_description(self, query: str,
                            source_ids: list[str] | None) -> list[PackageInfo]:
        if self._conn is None:
            return []

        if self._fts_available:
            fts_query = query.replace('"', '""')
            if source_ids:
                placeholders = ",".join("?" for _ in source_ids)
                sql = f"""SELECT p.package, p.version, p.arch, p.filename, p.sha256,
                                 p.size, p.description, p.depends, p.provides,
                                 p.base_url, p.source_id
                          FROM packages_fts f
                          JOIN packages p ON p.rowid = f.rowid
                          WHERE packages_fts MATCH ?
                            AND p.source_id IN ({placeholders})"""
                params: list = [f'description:"{fts_query}"'] + source_ids
            else:
                sql = """SELECT p.package, p.version, p.arch, p.filename, p.sha256,
                                p.size, p.description, p.depends, p.provides,
                                p.base_url, p.source_id
                         FROM packages_fts f
                         JOIN packages p ON p.rowid = f.rowid
                         WHERE packages_fts MATCH ?"""
                params = [f'description:"{fts_query}"']
            try:
                cur = self._conn.execute(sql, params)
                return self._rows_to_packages(cur.fetchall())
            except sqlite3.OperationalError:
                pass  # Fall through to LIKE

        # LIKE fallback
        if source_ids:
            placeholders = ",".join("?" for _ in source_ids)
            sql = f"""SELECT package, version, arch, filename, sha256, size,
                             description, depends, provides, base_url, source_id
                      FROM packages
                      WHERE LOWER(description) LIKE ?
                        AND source_id IN ({placeholders})"""
            params = [f"%{query}%"] + source_ids
        else:
            sql = """SELECT package, version, arch, filename, sha256, size,
                            description, depends, provides, base_url, source_id
                     FROM packages
                     WHERE LOWER(description) LIKE ?"""
            params = [f"%{query}%"]

        cur = self._conn.execute(sql, params)
        return self._rows_to_packages(cur.fetchall())

    @staticmethod
    def _rows_to_packages(rows: list) -> list[PackageInfo]:
        results: list[PackageInfo] = []
        for row in rows:
            (name, version, arch, filename, sha256, size,
             description, depends_raw, provides_raw, base_url, _source_id) = row
            results.append(PackageInfo(
                package=name,
                version=version,
                arch=arch,
                filename=filename,
                sha256=sha256,
                size=size,
                description=description,
                depends=_deserialize_depends(depends_raw),
                provides=_deserialize_provides(provides_raw),
                base_url=base_url,
            ))
        return results
```

- [ ] **Step 4: Run all tests to verify they pass**

Run: `pytest tests/test_db/test_package_cache.py -v`
Expected: All tests PASS

- [ ] **Step 5: Commit**

```bash
git add pkgeter/db/package_cache.py tests/test_db/test_package_cache.py
git commit -m "feat(cache): add PackageCache.search() with FTS5 and LIKE fallback"
```

---

### Task 4: PackageCache — Error Handling (corrupted DB)

**Files:**
- Modify: `pkgeter/db/package_cache.py`
- Modify: `tests/test_db/test_package_cache.py`

- [ ] **Step 1: Write failing test for corrupted database recovery**

Append to `tests/test_db/test_package_cache.py`:

```python
class TestErrorHandling:
    def test_corrupted_db_recreates(self, tmp_path, sample_packages):
        db_path = tmp_path / "corrupt.db"
        db_path.write_bytes(b"this is not a sqlite database at all!")

        from pkgeter.db.package_cache import PackageCache
        cache = PackageCache(db_path=db_path)

        # Should recover — store and load should work
        cache.store(SOURCE_ID, SOURCE_SHA, sample_packages)
        loaded = cache.load(SOURCE_ID)
        assert loaded is not None
        assert "nginx" in loaded

    def test_store_failure_does_not_crash(self, tmp_path, sample_packages):
        """Even if the DB becomes read-only after init, store() doesn't raise."""
        from pkgeter.db.package_cache import PackageCache
        cache = PackageCache(db_path=tmp_path / "test.db")

        # Forcibly close the connection to simulate failure
        cache._conn.close()
        cache._conn = None

        # Should not raise, just silently skip
        cache.store(SOURCE_ID, SOURCE_SHA, sample_packages)
        assert cache.load(SOURCE_ID) is None
```

- [ ] **Step 2: Run tests to verify new tests fail**

Run: `pytest tests/test_db/test_package_cache.py::TestErrorHandling -v`
Expected: FAIL — the corrupted DB test will fail because the constructor doesn't handle corrupt files yet.

- [ ] **Step 3: Update __init__ to handle corrupted databases**

In `pkgeter/db/package_cache.py`, update the `__init__` method to catch `sqlite3.DatabaseError` on connect and delete-and-retry:

```python
    def __init__(self, db_path: Path | None = None):
        self._db_path = db_path or CACHE_DB_PATH
        self._fts_available = False
        self._conn: sqlite3.Connection | None = None
        try:
            self._db_path.parent.mkdir(parents=True, exist_ok=True)
            self._conn = self._open_db()
        except sqlite3.Error as exc:
            print(f"Warning: cache database unavailable: {exc}", file=sys.stderr)
            self._conn = None

    def _open_db(self) -> sqlite3.Connection:
        try:
            conn = sqlite3.connect(str(self._db_path))
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("SELECT 1 FROM sqlite_master LIMIT 1")
        except sqlite3.DatabaseError:
            conn.close()
            self._db_path.unlink(missing_ok=True)
            conn = sqlite3.connect(str(self._db_path))
            conn.execute("PRAGMA journal_mode=WAL")
        self._conn = conn
        self._ensure_schema()
        return conn
```

- [ ] **Step 4: Run all tests to verify they pass**

Run: `pytest tests/test_db/test_package_cache.py -v`
Expected: All tests PASS

- [ ] **Step 5: Commit**

```bash
git add pkgeter/db/package_cache.py tests/test_db/test_package_cache.py
git commit -m "feat(cache): handle corrupted database with auto-recreation"
```

---

### Task 5: Integrate Cache into PmBackend Base Class

**Files:**
- Modify: `pkgeter/backend/__init__.py` (lines 1-50)

- [ ] **Step 1: Add lazy _cache property to PmBackend**

In `pkgeter/backend/__init__.py`, add a `_cache` property after the existing `merge_package_dbs` method (after line 49):

```python
    @property
    def cache(self) -> "PackageCache | None":
        """Lazily-initialized SQLite package cache."""
        if not hasattr(self, "_cache"):
            try:
                from pkgeter.db.package_cache import PackageCache
                self._cache: PackageCache | None = PackageCache()
            except Exception:
                self._cache = None
        return self._cache
```

Also add a `build_source_id` static method for consistent source_id generation:

```python
    @staticmethod
    def build_source_id(backend_type: str, url: str, release: str, arch: str, component: str = "") -> str:
        """Build a unique source identifier for the cache."""
        sanitized = url.removeprefix("https://").removeprefix("http://").rstrip("/")
        parts = [backend_type, sanitized, release, arch]
        if component:
            parts.append(component)
        return ":".join(parts)
```

- [ ] **Step 2: Run existing tests to verify nothing breaks**

Run: `pytest tests/ -v`
Expected: All existing tests PASS (no behavior change yet — cache is just a property)

- [ ] **Step 3: Commit**

```bash
git add pkgeter/backend/__init__.py
git commit -m "feat(backend): add lazy cache property and build_source_id to PmBackend"
```

---

### Task 6: Integrate Cache into DebianBackend

**Files:**
- Modify: `pkgeter/backend/debian.py` (method `_download_component`, lines 211-246)

- [ ] **Step 1: Modify _download_component() to use cache**

The current `_download_component()` method at lines 211-246 needs a cache check inserted. Replace the method body:

```python
    def _download_component(
        self,
        mirror: str,
        release: str,
        component: str,
        arch: str,
        *,
        timeout: int = 60,
        force_update: bool = False,
    ) -> Dict[str, PackageInfo] | None:
        source_id = self.build_source_id("deb", mirror, release, arch, component)

        if component == "main":
            cache_obj = SourceCache(mirror, release, arch)
            if cache_obj.update(timeout=timeout, force_update=force_update):
                action = cache_obj.last_action
                if action == "cache_hit":
                    print(" (cached)", end="", flush=True)
                elif action == "downloaded":
                    print(" (downloaded)", end="", flush=True)

                # Check SQLite cache before parsing
                raw = cache_obj.read_packages_gz()
                if raw is not None:
                    file_sha = cache_obj._file_sha256(cache_obj._packages_gz_path)
                    if file_sha and not force_update and self.cache:
                        if self.cache.is_fresh(source_id, file_sha):
                            loaded = self.cache.load(source_id)
                            if loaded is not None:
                                return loaded
                    # Parse and cache
                    parsed = self._parse_packages_gz(raw)
                    if file_sha and self.cache:
                        self.cache.store(source_id, file_sha, parsed)
                    return parsed

        # Direct HTTP fallback (non-main components, or cache failure)
        print(" (downloading)", end="", flush=True)
        url = self._build_component_url(mirror, release, component, arch)
        with httpx.Client(timeout=timeout) as client:
            resp = client.get(url, follow_redirects=True)
            resp.raise_for_status()
        parsed = self._parse_packages_gz(resp.content)

        # Cache the directly-downloaded result too
        if self.cache:
            import hashlib
            content_sha = hashlib.sha256(resp.content).hexdigest()
            self.cache.store(source_id, content_sha, parsed)

        return parsed
```

- [ ] **Step 2: Run existing Debian-related tests**

Run: `pytest tests/test_db/test_packages.py tests/test_deps/ -v`
Expected: All PASS. The cache layer is transparent — existing behavior unchanged.

- [ ] **Step 3: Commit**

```bash
git add pkgeter/backend/debian.py
git commit -m "feat(debian): integrate SQLite cache in _download_component()"
```

---

### Task 7: Integrate Cache into RpmBackend

**Files:**
- Modify: `pkgeter/backend/rpm.py` (method `_download_repo`, lines 205-268)

- [ ] **Step 1: Modify _download_repo() to use cache**

The current `_download_repo()` method needs a cache check before calling `_parse_primary()`. The SHA256 is already available from `repomd.xml` as `expected_sha256`. Replace the method body:

```python
    def _download_repo(
        self,
        repo: RepoConfig,
        *,
        timeout: int = 60,
        force_update: bool = False,
    ) -> Dict[str, PackageInfo] | None:
        base_url = repo.url.rstrip("/")
        sanitized = re.sub(r"[^a-zA-Z0-9]", "_", base_url)
        cache_dir = CONFIG_PATH.parent / "sources" / "rpm" / sanitized
        cache_path = cache_dir / "primary.xml.gz"

        source_id = self.build_source_id("rpm", base_url, repo.release, repo.arch or "")

        # 1-hour cache cooldown – skip HTTP entirely when the cache is fresh
        if not force_update and cache_path.exists():
            age = time.time() - cache_path.stat().st_mtime
            if age < 3600:
                # Check SQLite cache first
                file_sha = hashlib.sha256(cache_path.read_bytes()).hexdigest()
                if self.cache and self.cache.is_fresh(source_id, file_sha):
                    loaded = self.cache.load(source_id)
                    if loaded is not None:
                        for pkg in loaded.values():
                            pkg.base_url = repo.url
                        return loaded
                # SQLite miss — parse and cache
                packages = self._parse_primary(cache_path.read_bytes())
                for pkg in packages.values():
                    pkg.base_url = repo.url
                if self.cache:
                    self.cache.store(source_id, file_sha, packages)
                return packages

        repomd_url = f"{base_url}/repodata/repomd.xml"

        with httpx.Client(timeout=timeout) as client:
            resp = client.get(repomd_url, follow_redirects=True)
            resp.raise_for_status()
        repomd_xml = resp.text

        href, expected_sha256 = self._parse_repomd(repomd_xml)

        # Check cache: if cached file's SHA256 matches, skip download
        if cache_path.exists():
            cached_sha256 = hashlib.sha256(cache_path.read_bytes()).hexdigest()
            if cached_sha256 == expected_sha256:
                # Check SQLite cache
                if self.cache and not force_update and self.cache.is_fresh(source_id, expected_sha256):
                    loaded = self.cache.load(source_id)
                    if loaded is not None:
                        for pkg in loaded.values():
                            pkg.base_url = repo.url
                        return loaded
                packages = self._parse_primary(cache_path.read_bytes())
                for pkg in packages.values():
                    pkg.base_url = repo.url
                if self.cache:
                    self.cache.store(source_id, expected_sha256, packages)
                return packages

        # Download primary.xml.gz
        primary_url = f"{base_url}/{href}"
        with httpx.Client(timeout=timeout) as client:
            resp = client.get(primary_url, follow_redirects=True)
            resp.raise_for_status()

        data = resp.content

        # Verify SHA256
        actual_sha256 = hashlib.sha256(data).hexdigest()
        if actual_sha256 != expected_sha256:
            raise ValueError(
                f"SHA256 mismatch for {primary_url}: "
                f"expected {expected_sha256}, got {actual_sha256}"
            )

        # Save to file cache
        cache_dir.mkdir(parents=True, exist_ok=True)
        cache_path.write_bytes(data)

        packages = self._parse_primary(data)
        for pkg in packages.values():
            pkg.base_url = repo.url

        # Store in SQLite cache
        if self.cache:
            self.cache.store(source_id, expected_sha256, packages)

        return packages
```

- [ ] **Step 2: Run existing tests**

Run: `pytest tests/ -v`
Expected: All PASS.

- [ ] **Step 3: Commit**

```bash
git add pkgeter/backend/rpm.py
git commit -m "feat(rpm): integrate SQLite cache in _download_repo()"
```

---

### Task 8: Optimize Search to Use PackageCache.search()

**Files:**
- Modify: `pkgeter/search.py` (lines 15-33 `_search_db`, lines 115-158 search loop in `run_search`)

- [ ] **Step 1: Modify run_search() to use cache-based search**

The current `run_search()` loads the full package DB into memory per-repo, then calls `_search_db()` which iterates the dict. We change this so that after loading repos (which now populates the SQLite cache), search queries go through `PackageCache.search()`.

Replace the `_search_db` function and modify the search loop in `run_search()`:

Replace `_search_db` (lines 15-33) with:

```python
def _search_db(
    package_db: Dict[str, PackageInfo],
    q: str,
    has_wildcards: bool,
    search_desc: bool,
) -> list[PackageInfo]:
    """Search a single package DB for packages matching *q* (in-memory fallback)."""
    results = []
    seen = set()
    for name, info in package_db.items():
        n = name.lower()
        matched = False
        if has_wildcards:
            if fnmatch(n, q):
                matched = True
        else:
            if q in n:
                matched = True
        if search_desc and not matched and info.description and q in info.description.lower():
            matched = True
        if matched and name not in seen:
            results.append(info)
            seen.add(name)
    return results
```

In `run_search()`, after the per-repo loading loop (after line 133 `print(f"Found {total} packages...")`), replace the search loop (lines 137-161) with:

```python
    # Search — prefer SQLite cache, fall back to in-memory
    try:
        from pkgeter.db.package_cache import PackageCache
        pkg_cache = PackageCache()
        use_cache_search = True
    except Exception:
        use_cache_search = False

    for query in args.queries:
        q = query.lower()
        has_wildcards = "*" in q or "?" in q
        found_any = False

        for repo_name, package_db in repo_dbs:
            if use_cache_search:
                results = pkg_cache.search(q, search_desc=args.desc)
            else:
                results = _search_db(package_db, q, has_wildcards, args.desc)
            if not results:
                continue

            if not found_any:
                print(f"Results for '{query}':")
                found_any = True

            header = f"{preset_label} / {repo_name}" if preset_label else repo_name
            print(f"  [{header}]")
            for info in results:
                size_str = _format_size(info.size) if info.size else ""
                desc = (info.description or "").split("\n")[0][:80]
                print(f"    {info.package} {info.version:>20}  {info.arch:>8}  {size_str:>8}  {desc}")
            print()

        if not found_any:
            print(f"No matches for '{query}'\n")
```

- [ ] **Step 2: Run existing tests**

Run: `pytest tests/ -v`
Expected: All PASS.

- [ ] **Step 3: Commit**

```bash
git add pkgeter/search.py
git commit -m "feat(search): use SQLite cache for faster search with FTS5 fallback"
```

---

### Task 9: Run Full Test Suite and Verify

**Files:** None (verification only)

- [ ] **Step 1: Run full test suite**

Run: `pytest tests/ -v`
Expected: All tests PASS — no regressions.

- [ ] **Step 2: Run a quick manual smoke test**

Run: `python -m pkgeter search nginx --distro debian-bookworm` (or equivalent available preset)
Expected: Results appear faster on second run (SQLite cache hit). First run populates the cache.

- [ ] **Step 3: Verify cache.db was created**

Run: `ls ~/.config/pkgeter/cache.db` (or `dir %USERPROFILE%\.config\pkgeter\cache.db` on Windows)
Expected: File exists after the first run.

- [ ] **Step 4: Final commit if any cleanup needed**

```bash
git add -A
git commit -m "chore: final cleanup for SQLite package cache"
```
