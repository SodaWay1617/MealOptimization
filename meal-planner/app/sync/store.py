from __future__ import annotations

import json
import sqlite3
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterator, Optional, Sequence, Tuple


@dataclass(frozen=True)
class StoredRecipe:
    source_path: str
    content_hash: str
    category: Optional[str]
    confidence: float
    recipe_payload: Dict[str, Any]
    updated_at: float


def default_recipes_db_path(root: Path) -> Path:
    return root / "data" / "recipes.sqlite"


class RecipeStore:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self._shared_conn: Optional[sqlite3.Connection] = None
        if str(self.db_path) not in {":memory:"} and not str(self.db_path).startswith("file:"):
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
        if str(self.db_path) == ":memory:":
            self._shared_conn = sqlite3.connect(":memory:")
            self._shared_conn.row_factory = sqlite3.Row
        self._init_schema()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        if self._shared_conn is not None:
            try:
                yield self._shared_conn
            except Exception:
                self._shared_conn.rollback()
                raise
            else:
                self._shared_conn.commit()
            return
        db_value = str(self.db_path)
        if db_value.startswith("file:"):
            conn = sqlite3.connect(db_value, uri=db_value.startswith("file:"))
        else:
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
                CREATE TABLE IF NOT EXISTS recipe_cache (
                    content_hash TEXT PRIMARY KEY,
                    recipe_json TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    updated_at REAL NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS recipes (
                    source_path TEXT PRIMARY KEY,
                    content_hash TEXT NOT NULL,
                    category TEXT,
                    confidence REAL NOT NULL,
                    recipe_json TEXT NOT NULL,
                    updated_at REAL NOT NULL
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_recipes_content_hash ON recipes(content_hash)"
            )

    def get_cached(self, content_hash: str) -> Optional[Tuple[Dict[str, Any], float]]:
        with self._connect() as conn:
            cursor = conn.execute(
                """
                SELECT recipe_json, confidence
                FROM recipe_cache
                WHERE content_hash = ?
                """,
                (content_hash,),
            )
            row = cursor.fetchone()
            if row is None:
                return None
            return json.loads(row["recipe_json"]), float(row["confidence"])

    def put_cached(
        self,
        content_hash: str,
        recipe_payload: Dict[str, Any],
        *,
        confidence: float,
    ) -> None:
        now = time.time()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO recipe_cache (content_hash, recipe_json, confidence, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(content_hash) DO UPDATE SET
                    recipe_json=excluded.recipe_json,
                    confidence=excluded.confidence,
                    updated_at=excluded.updated_at
                """,
                (content_hash, json.dumps(recipe_payload, ensure_ascii=False), confidence, now),
            )

    def upsert_recipe(
        self,
        *,
        source_path: str,
        content_hash: str,
        category: Optional[str],
        recipe_payload: Dict[str, Any],
        confidence: float,
    ) -> None:
        now = time.time()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO recipes (source_path, content_hash, category, confidence, recipe_json, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(source_path) DO UPDATE SET
                    content_hash=excluded.content_hash,
                    category=excluded.category,
                    confidence=excluded.confidence,
                    recipe_json=excluded.recipe_json,
                    updated_at=excluded.updated_at
                """,
                (
                    source_path,
                    content_hash,
                    category,
                    confidence,
                    json.dumps(recipe_payload, ensure_ascii=False),
                    now,
                ),
            )

    def get_recipes_by_source_paths(self, source_paths: Sequence[Path | str]) -> list[StoredRecipe]:
        normalized = [str(Path(path)) for path in source_paths]
        if not normalized:
            return []
        placeholders = ", ".join("?" for _ in normalized)
        query = f"""
            SELECT source_path, content_hash, category, confidence, recipe_json, updated_at
            FROM recipes
            WHERE source_path IN ({placeholders})
            ORDER BY source_path
        """
        with self._connect() as conn:
            cursor = conn.execute(query, tuple(normalized))
            return [self._row_to_stored_recipe(row) for row in cursor.fetchall()]

    @staticmethod
    def _row_to_stored_recipe(row: sqlite3.Row) -> StoredRecipe:
        return StoredRecipe(
            source_path=row["source_path"],
            content_hash=row["content_hash"],
            category=row["category"],
            confidence=float(row["confidence"]),
            recipe_payload=json.loads(row["recipe_json"]),
            updated_at=float(row["updated_at"]),
        )
