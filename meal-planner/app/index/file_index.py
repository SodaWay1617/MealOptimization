from __future__ import annotations

import sqlite3
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, Iterator, List, Optional, Sequence, Tuple

from app.scanner.scan import RecipeFile


@dataclass(frozen=True)
class FileIndexEntry:
    path: str
    category: Optional[str]
    mtime: float
    size: int
    content_hash: Optional[str]
    last_synced_hash: Optional[str]
    status: str
    updated_at: float


def default_db_path(root: Path) -> Path:
    return root / "data" / "file_index.sqlite"


class FileIndex:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        except Exception:
            conn.rollback()
            raise
        else:
            conn.commit()
        finally:
            conn.close()

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS file_index (
                    path TEXT PRIMARY KEY,
                    category TEXT,
                    mtime REAL NOT NULL,
                    size INTEGER NOT NULL,
                    content_hash TEXT,
                    last_synced_hash TEXT,
                    status TEXT NOT NULL,
                    updated_at REAL NOT NULL
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_file_index_status ON file_index(status)"
            )

    def upsert_records(
        self,
        records: Iterable[RecipeFile],
        *,
        status: str = "scanned",
    ) -> None:
        now = time.time()
        rows = [
            (
                str(item.path),
                item.category,
                item.mtime,
                item.size,
                item.content_hash,
                status,
                now,
            )
            for item in records
        ]
        if not rows:
            return
        with self._connect() as conn:
            conn.executemany(
                """
                INSERT INTO file_index (
                    path, category, mtime, size, content_hash, status, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(path) DO UPDATE SET
                    category=excluded.category,
                    mtime=excluded.mtime,
                    size=excluded.size,
                    content_hash=excluded.content_hash,
                    status=excluded.status,
                    updated_at=excluded.updated_at
                """,
                rows,
            )

    def reconcile_scan(self, records: Sequence[RecipeFile]) -> Tuple[int, int, int]:
        seen_paths = {str(item.path) for item in records}
        existing = self._load_existing()
        now = time.time()

        to_upsert: List[Tuple[str, Optional[str], float, int, Optional[str], str, float]] = []
        for item in records:
            path = str(item.path)
            previous = existing.get(path)
            last_synced_hash = previous[0] if previous else None

            status = "needs_sync"
            if item.content_hash and last_synced_hash == item.content_hash:
                status = "synced"

            to_upsert.append(
                (
                    path,
                    item.category,
                    item.mtime,
                    item.size,
                    item.content_hash,
                    status,
                    now,
                )
            )

        removed_paths = [path for path in existing.keys() if path not in seen_paths]

        with self._connect() as conn:
            if to_upsert:
                conn.executemany(
                    """
                    INSERT INTO file_index (
                        path, category, mtime, size, content_hash, status, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(path) DO UPDATE SET
                        category=excluded.category,
                        mtime=excluded.mtime,
                        size=excluded.size,
                        content_hash=excluded.content_hash,
                        status=excluded.status,
                        updated_at=excluded.updated_at
                    """,
                    to_upsert,
                )
            if removed_paths:
                conn.executemany(
                    """
                    UPDATE file_index
                    SET status = 'removed', updated_at = ?
                    WHERE path = ?
                    """,
                    [(now, path) for path in removed_paths],
                )

        synced = sum(1 for row in to_upsert if row[5] == "synced")
        needs_sync = sum(1 for row in to_upsert if row[5] == "needs_sync")
        removed = len(removed_paths)
        return synced, needs_sync, removed

    def get_all(self) -> List[FileIndexEntry]:
        with self._connect() as conn:
            cursor = conn.execute(
                """
                SELECT path, category, mtime, size, content_hash,
                       last_synced_hash, status, updated_at
                FROM file_index
                ORDER BY path
                """
            )
            return [self._row_to_entry(row) for row in cursor.fetchall()]

    def get_by_path(self, path: Path) -> Optional[FileIndexEntry]:
        with self._connect() as conn:
            cursor = conn.execute(
                """
                SELECT path, category, mtime, size, content_hash,
                       last_synced_hash, status, updated_at
                FROM file_index
                WHERE path = ?
                """,
                (str(path),),
            )
            row = cursor.fetchone()
            if row is None:
                return None
            return self._row_to_entry(row)

    def get_by_status(
        self,
        status: str,
        *,
        category: Optional[str] = None,
        paths: Optional[Sequence[Path | str]] = None,
        limit: Optional[int] = None,
    ) -> List[FileIndexEntry]:
        query = """
            SELECT path, category, mtime, size, content_hash,
                   last_synced_hash, status, updated_at
            FROM file_index
            WHERE status = ?
        """
        params: List[object] = [status]
        if category is not None:
            query += " AND category = ?"
            params.append(category)
        if paths:
            normalized_paths = [str(Path(path)) for path in paths]
            placeholders = ", ".join("?" for _ in normalized_paths)
            query += f" AND path IN ({placeholders})"
            params.extend(normalized_paths)
        query += " ORDER BY updated_at, path"
        if limit is not None and limit > 0:
            query += " LIMIT ?"
            params.append(limit)
        with self._connect() as conn:
            cursor = conn.execute(query, tuple(params))
            return [self._row_to_entry(row) for row in cursor.fetchall()]

    def count_active(self) -> int:
        with self._connect() as conn:
            cursor = conn.execute(
                "SELECT COUNT(*) AS total FROM file_index WHERE status != 'removed'"
            )
            return int(cursor.fetchone()["total"])

    def count_by_status(self) -> Dict[str, int]:
        with self._connect() as conn:
            cursor = conn.execute(
                "SELECT status, COUNT(*) AS total FROM file_index GROUP BY status"
            )
            return {row["status"]: int(row["total"]) for row in cursor.fetchall()}

    def count_by_category(self) -> Dict[str, int]:
        with self._connect() as conn:
            cursor = conn.execute(
                """
                SELECT COALESCE(category, '') AS category, COUNT(*) AS total
                FROM file_index
                WHERE status != 'removed'
                GROUP BY category
                ORDER BY category
                """
            )
            return {row["category"]: int(row["total"]) for row in cursor.fetchall()}

    def update_last_synced_hash(self, path: Path, last_synced_hash: str) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE file_index
                SET last_synced_hash = ?, updated_at = ?
                WHERE path = ?
                """,
                (last_synced_hash, time.time(), str(path)),
            )

    def mark_synced(self, path: Path, content_hash: str) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE file_index
                SET last_synced_hash = ?, status = 'synced', updated_at = ?
                WHERE path = ?
                """,
                (content_hash, time.time(), str(path)),
            )

    def upsert_synced_record(self, record: RecipeFile, *, last_synced_hash: str) -> None:
        now = time.time()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO file_index (
                    path, category, mtime, size, content_hash,
                    last_synced_hash, status, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, 'synced', ?)
                ON CONFLICT(path) DO UPDATE SET
                    category=excluded.category,
                    mtime=excluded.mtime,
                    size=excluded.size,
                    content_hash=excluded.content_hash,
                    last_synced_hash=excluded.last_synced_hash,
                    status='synced',
                    updated_at=excluded.updated_at
                """,
                (
                    str(record.path),
                    record.category,
                    record.mtime,
                    record.size,
                    record.content_hash,
                    last_synced_hash,
                    now,
                ),
            )

    def delete(self, path: Path) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM file_index WHERE path = ?", (str(path),))

    def _load_existing(self) -> Dict[str, Tuple[Optional[str], str]]:
        with self._connect() as conn:
            cursor = conn.execute(
                "SELECT path, last_synced_hash, status FROM file_index"
            )
            return {
                row["path"]: (row["last_synced_hash"], row["status"])
                for row in cursor.fetchall()
            }

    @staticmethod
    def _row_to_entry(row: sqlite3.Row) -> FileIndexEntry:
        return FileIndexEntry(
            path=row["path"],
            category=row["category"],
            mtime=row["mtime"],
            size=row["size"],
            content_hash=row["content_hash"],
            last_synced_hash=row["last_synced_hash"],
            status=row["status"],
            updated_at=row["updated_at"],
        )
