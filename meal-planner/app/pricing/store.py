from __future__ import annotations

import json
import sqlite3
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional


@dataclass(frozen=True)
class PriceBookEntry:
    ingredient_name: str
    unit: str
    price_per_unit: float
    currency: str
    source: str
    updated_at: float


class PriceBookConfigError(ValueError):
    pass


@dataclass(frozen=True)
class PriceSeedEntry:
    ingredient_name: str
    unit: str
    price_per_unit: Optional[float]
    currency: str
    source: str
    usage_count: int


def default_price_book_db_path(root: Path) -> Path:
    return root / "data" / "price_book.sqlite"


def export_price_book_seed_from_recipes(
    recipes_db_path: Path,
    output_path: Path,
    *,
    currency: str = "RUB",
    source: str = "seed",
) -> int:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(recipes_db_path)
    try:
        rows = conn.execute(
            """
            SELECT
                TRIM(json_extract(i.value, '$.name')) AS ingredient_name,
                TRIM(json_extract(i.value, '$.unit')) AS unit,
                COUNT(*) AS usage_count
            FROM recipes r, json_each(r.recipe_json, '$.ingredients') i
            WHERE ingredient_name IS NOT NULL
              AND ingredient_name != ''
              AND unit IS NOT NULL
              AND unit != ''
            GROUP BY ingredient_name, unit
            ORDER BY usage_count DESC, ingredient_name ASC, unit ASC
            """
        ).fetchall()
    finally:
        conn.close()

    payload = {
        "defaults": [
            {
                "ingredient_name": ingredient_name,
                "unit": unit,
                "price_per_unit": None,
                "currency": currency,
                "source": source,
                "usage_count": int(usage_count),
            }
            for ingredient_name, unit, usage_count in rows
        ]
    }
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return len(rows)


class PriceBookStore:
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
                CREATE TABLE IF NOT EXISTS price_book (
                    ingredient_name TEXT NOT NULL,
                    unit TEXT NOT NULL,
                    price_per_unit REAL NOT NULL,
                    currency TEXT NOT NULL,
                    source TEXT NOT NULL,
                    updated_at REAL NOT NULL,
                    PRIMARY KEY (ingredient_name, unit)
                )
                """
            )

    def list_entries(self) -> List[PriceBookEntry]:
        with self._connect() as conn:
            cursor = conn.execute(
                """
                SELECT ingredient_name, unit, price_per_unit, currency, source, updated_at
                FROM price_book
                ORDER BY ingredient_name, unit
                """
            )
            return [self._row_to_entry(row) for row in cursor.fetchall()]

    def get_entry(self, ingredient_name: str, unit: str) -> Optional[PriceBookEntry]:
        with self._connect() as conn:
            cursor = conn.execute(
                """
                SELECT ingredient_name, unit, price_per_unit, currency, source, updated_at
                FROM price_book
                WHERE ingredient_name = ? AND unit = ?
                """,
                (_normalize_name(ingredient_name), unit.strip()),
            )
            row = cursor.fetchone()
            if row is None:
                return None
            return self._row_to_entry(row)

    def upsert_entry(
        self,
        *,
        ingredient_name: str,
        unit: str,
        price_per_unit: float,
        currency: str = "RUB",
        source: str = "manual",
    ) -> None:
        if price_per_unit < 0:
            raise ValueError("price_per_unit must be non-negative")
        normalized_name = _normalize_name(ingredient_name)
        normalized_unit = unit.strip()
        if not normalized_name or not normalized_unit:
            raise ValueError("ingredient_name and unit are required")
        now = time.time()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO price_book (
                    ingredient_name, unit, price_per_unit, currency, source, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(ingredient_name, unit) DO UPDATE SET
                    price_per_unit=excluded.price_per_unit,
                    currency=excluded.currency,
                    source=excluded.source,
                    updated_at=excluded.updated_at
                """,
                (
                    normalized_name,
                    normalized_unit,
                    float(price_per_unit),
                    currency.strip() or "RUB",
                    source.strip() or "manual",
                    now,
                ),
            )

    def delete_entry(self, ingredient_name: str, unit: str) -> bool:
        with self._connect() as conn:
            cursor = conn.execute(
                "DELETE FROM price_book WHERE ingredient_name = ? AND unit = ?",
                (_normalize_name(ingredient_name), unit.strip()),
            )
            return cursor.rowcount > 0

    def seed_defaults(self, defaults: List[Dict[str, Any]]) -> int:
        count = 0
        for item in defaults:
            self.upsert_entry(
                ingredient_name=_require_string(item, "ingredient_name"),
                unit=_require_string(item, "unit"),
                price_per_unit=_require_number(item, "price_per_unit"),
                currency=str(item.get("currency", "RUB")).strip() or "RUB",
                source=str(item.get("source", "default")).strip() or "default",
            )
            count += 1
        return count

    @staticmethod
    def _row_to_entry(row: sqlite3.Row) -> PriceBookEntry:
        return PriceBookEntry(
            ingredient_name=row["ingredient_name"],
            unit=row["unit"],
            price_per_unit=float(row["price_per_unit"]),
            currency=row["currency"],
            source=row["source"],
            updated_at=float(row["updated_at"]),
        )


def load_price_book_defaults(config_path: Path) -> List[Dict[str, Any]]:
    if not config_path.exists():
        raise FileNotFoundError(f"Missing price book defaults config: {config_path}")
    payload = json.loads(config_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or "defaults" not in payload:
        raise PriceBookConfigError("Expected top-level object with 'defaults' array")
    defaults = payload["defaults"]
    if not isinstance(defaults, list):
        raise PriceBookConfigError("'defaults' must be an array")
    normalized: List[Dict[str, Any]] = []
    for item in defaults:
        if not isinstance(item, dict):
            raise PriceBookConfigError("Each default price entry must be an object")
        normalized.append(item)
    return normalized


def load_price_book_seed(config_path: Path) -> List[PriceSeedEntry]:
    if not config_path.exists():
        raise FileNotFoundError(f"Missing price book seed config: {config_path}")
    payload = json.loads(config_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or "defaults" not in payload:
        raise PriceBookConfigError("Expected top-level object with 'defaults' array")
    defaults = payload["defaults"]
    if not isinstance(defaults, list):
        raise PriceBookConfigError("'defaults' must be an array")

    normalized: List[PriceSeedEntry] = []
    for item in defaults:
        if not isinstance(item, dict):
            raise PriceBookConfigError("Each default price entry must be an object")
        ingredient_name = _require_string(item, "ingredient_name")
        unit = _require_string(item, "unit")
        raw_price = item.get("price_per_unit")
        if raw_price is None:
            price_per_unit = None
        elif isinstance(raw_price, (int, float)) and not isinstance(raw_price, bool) and raw_price >= 0:
            price_per_unit = float(raw_price)
        else:
            raise PriceBookConfigError("price_per_unit must be a non-negative number or null")
        normalized.append(
            PriceSeedEntry(
                ingredient_name=ingredient_name,
                unit=unit,
                price_per_unit=price_per_unit,
                currency=str(item.get("currency", "RUB")).strip() or "RUB",
                source=str(item.get("source", "seed")).strip() or "seed",
                usage_count=_require_int(item.get("usage_count"), "usage_count", default=0),
            )
        )
    return normalized


def _normalize_name(value: str) -> str:
    return " ".join(value.strip().casefold().split())


def _require_string(payload: Dict[str, Any], field: str) -> str:
    value = payload.get(field)
    if not isinstance(value, str) or not value.strip():
        raise PriceBookConfigError(f"{field} must be a non-empty string")
    return value.strip()


def _require_number(payload: Dict[str, Any], field: str) -> float:
    value = payload.get(field)
    if not isinstance(value, (int, float)) or isinstance(value, bool) or value < 0:
        raise PriceBookConfigError(f"{field} must be a non-negative number")
    return float(value)


def _require_int(value: Any, field: str, *, default: int) -> int:
    if value is None:
        return default
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise PriceBookConfigError(f"{field} must be a non-negative integer")
    return value
