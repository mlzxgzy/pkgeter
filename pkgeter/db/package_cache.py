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
        return self._conn

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
