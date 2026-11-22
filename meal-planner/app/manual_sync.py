from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.index.file_index import FileIndex
from app.scanner.hash import content_hash
from app.scanner.scan import RecipeFile
from app.sync.recipe_schema import ALLOWED_CATEGORIES, ALLOWED_UNITS, validate_recipe
from app.sync.store import RecipeStore


@dataclass(frozen=True)
class ManualRecipeDraft:
    source_path: str
    category: str
    title: str
    servings: Optional[float]
    ingredients: List[Dict[str, Any]]
    steps: List[str]
    notes: Optional[str]
    confidence: float


def save_manual_recipe(
    *,
    draft: ManualRecipeDraft,
    file_index: FileIndex,
    recipe_store: RecipeStore,
) -> Dict[str, Any]:
    source_path = Path(draft.source_path).expanduser()
    if not source_path.exists() or not source_path.is_file():
        raise ValueError(f"Source markdown file not found: {source_path}")
    if draft.category not in ALLOWED_CATEGORIES:
        raise ValueError(f"Category must be one of: {', '.join(ALLOWED_CATEGORIES)}")
    if draft.confidence < 0.0 or draft.confidence > 1.0:
        raise ValueError("Confidence must be in range [0.0, 1.0]")

    payload = {
        "title": draft.title.strip(),
        "category": draft.category,
        "servings": draft.servings,
        "ingredients": draft.ingredients,
        "steps": draft.steps,
        "source_path": str(source_path),
        "notes": draft.notes,
    }
    recipe_payload = validate_recipe(payload)

    stat = source_path.stat()
    _, digest = content_hash(source_path)
    record = RecipeFile(
        path=source_path,
        category=draft.category,
        mtime=stat.st_mtime,
        size=stat.st_size,
        content_hash=digest,
    )
    recipe_store.put_cached(digest, recipe_payload, confidence=draft.confidence)
    recipe_store.upsert_recipe(
        source_path=str(source_path),
        content_hash=digest,
        category=draft.category,
        recipe_payload=recipe_payload,
        confidence=draft.confidence,
    )
    file_index.upsert_synced_record(record, last_synced_hash=digest)
    return recipe_payload


def parse_ingredients_text(raw_text: str) -> List[Dict[str, Any]]:
    ingredients: List[Dict[str, Any]] = []
    for raw_line in raw_text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        parts = [part.strip() for part in line.split("|")]
        while len(parts) < 4:
            parts.append("")
        name, amount_raw, unit_raw, note_raw = parts[:4]
        if not name:
            raise ValueError("Each ingredient line must have a name")
        unit = unit_raw or None
        if unit is not None and unit not in ALLOWED_UNITS:
            raise ValueError(f"Ingredient unit '{unit}' is not supported")
        amount = _parse_optional_number(amount_raw)
        ingredient = {
            "name": name,
            "amount": amount,
            "unit": unit,
        }
        ingredient["note"] = note_raw or None
        ingredients.append(ingredient)
    if not ingredients:
        raise ValueError("At least one ingredient is required")
    return ingredients


def parse_steps_text(raw_text: str) -> List[str]:
    steps = [line.strip() for line in raw_text.splitlines() if line.strip()]
    if not steps:
        raise ValueError("At least one step is required")
    return steps


def export_recipe_json(draft: ManualRecipeDraft) -> str:
    payload = {
        "title": draft.title,
        "category": draft.category,
        "servings": draft.servings,
        "ingredients": draft.ingredients,
        "steps": draft.steps,
        "source_path": draft.source_path,
        "notes": draft.notes,
        "confidence": draft.confidence,
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def _parse_optional_number(raw_value: str) -> Optional[float]:
    stripped = raw_value.strip()
    if not stripped:
        return None
    try:
        return float(stripped)
    except ValueError as exc:
        raise ValueError(f"Invalid numeric value: {raw_value}") from exc
