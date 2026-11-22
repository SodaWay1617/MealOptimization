from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import logging
from pathlib import Path
from typing import Any, Dict, Optional, Sequence

from app.index.file_index import FileIndex
from app.sync.llm import LLMClient, LLMParseError
from app.sync.recipe_schema import RecipeValidationError, validate_recipe
from app.sync.store import RecipeStore


UNIT_ALIASES = {
    "грамм": "г",
    "грамма": "г",
    "граммов": "г",
    "килограмм": "кг",
    "килограмма": "кг",
    "килограммов": "кг",
    "миллилитр": "мл",
    "миллилитра": "мл",
    "миллилитров": "мл",
    "литр": "л",
    "литра": "л",
    "литров": "л",
    "чайная ложка": "ч.л.",
    "чайные ложки": "ч.л.",
    "чайных ложек": "ч.л.",
    "столовая ложка": "ст.л.",
    "столовые ложки": "ст.л.",
    "столовых ложек": "ст.л.",
    "штука": "шт",
    "штуки": "шт",
    "штук": "шт",
    "кусочек": "шт",
    "кусочка": "шт",
    "кусочков": "шт",
    "ломтик": "шт",
    "ломтика": "шт",
    "ломтиков": "шт",
    "зубчик чеснока": "зубчик",
    "зубчика": "зубчик",
    "зубчиков": "зубчик",
    "бутон": "шт",
    "бутона": "шт",
    "бутонов": "шт",
    "мерная ложка": "шт",
    "мерные ложки": "шт",
    "порция": "шт",
    "порции": "шт",
    "порций": "шт",
    "по желанию": "по вкусу",
    "горсть": "по вкусу",
    "горсти": "по вкусу",
    "см": "по вкусу",
}


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SyncSummary:
    selected: int
    synced: int
    cached: int
    failed: int
    skipped: int


def run_sync_pipeline(
    *,
    file_index: FileIndex,
    recipe_store: RecipeStore,
    llm_client: LLMClient,
    category: Optional[str] = None,
    selected_paths: Optional[Sequence[Path | str]] = None,
    limit: Optional[int] = None,
    dry_run: bool = False,
    force: bool = False,
) -> SyncSummary:
    if force:
        entries = _select_force_entries(
            file_index=file_index,
            category=category,
            selected_paths=selected_paths,
            limit=limit,
        )
    else:
        entries = file_index.get_by_status(
            "needs_sync",
            category=category,
            paths=selected_paths,
            limit=limit,
        )
    synced = 0
    cached = 0
    failed = 0
    skipped = 0

    for entry in entries:
        if not entry.content_hash:
            logger.warning("sync skipped: missing content_hash path=%s", entry.path)
            skipped += 1
            continue

        source_path = Path(entry.path)
        if not source_path.exists():
            logger.warning("sync skipped: source file missing path=%s", entry.path)
            skipped += 1
            continue

        try:
            recipe_payload, confidence, from_cache = _prepare_recipe(
                recipe_store=recipe_store,
                llm_client=llm_client,
                source_path=source_path,
                content_hash=entry.content_hash,
                category_hint=entry.category,
                force=force,
            )
        except (OSError, LLMParseError, RecipeValidationError, ValueError) as exc:
            logger.error(
                "sync failed: path=%s category=%s error_type=%s error=%s",
                entry.path,
                entry.category,
                type(exc).__name__,
                exc,
            )
            failed += 1
            continue

        if from_cache:
            cached += 1

        if not dry_run:
            recipe_store.upsert_recipe(
                source_path=entry.path,
                content_hash=entry.content_hash,
                category=entry.category,
                recipe_payload=recipe_payload,
                confidence=confidence,
            )
            file_index.mark_synced(Path(entry.path), entry.content_hash)
        synced += 1

    return SyncSummary(
        selected=len(entries),
        synced=synced,
        cached=cached,
        failed=failed,
        skipped=skipped,
    )


def _prepare_recipe(
    *,
    recipe_store: RecipeStore,
    llm_client: LLMClient,
    source_path: Path,
    content_hash: str,
    category_hint: Optional[str],
    force: bool,
) -> tuple[Dict[str, Any], float, bool]:
    cached = None if force else recipe_store.get_cached(content_hash)
    if cached is not None:
        cached_payload, confidence = cached
        payload = deepcopy(cached_payload)
        payload["source_path"] = str(source_path)
        if category_hint:
            payload["category"] = category_hint
        recipe = validate_recipe(payload)
        return recipe, confidence, True

    markdown = source_path.read_text(encoding="utf-8")
    parsed = llm_client.parse_recipe(
        markdown,
        source_path=str(source_path),
        category_hint=category_hint,
    )
    parsed = _normalize_llm_recipe_payload(parsed)
    confidence = _extract_confidence(parsed)
    recipe_payload = {k: v for k, v in parsed.items() if k != "confidence"}
    recipe_payload["source_path"] = str(source_path)
    if category_hint:
        recipe_payload["category"] = category_hint

    recipe = validate_recipe(recipe_payload)
    recipe_store.put_cached(content_hash, recipe, confidence=confidence)
    return recipe, confidence, False


def _select_force_entries(
    *,
    file_index: FileIndex,
    category: Optional[str],
    selected_paths: Optional[Sequence[Path | str]],
    limit: Optional[int],
) -> list:
    synced_entries = file_index.get_by_status(
        "synced",
        category=category,
        paths=selected_paths,
        limit=None,
    )
    needs_sync_entries = file_index.get_by_status(
        "needs_sync",
        category=category,
        paths=selected_paths,
        limit=None,
    )
    merged = {entry.path: entry for entry in synced_entries}
    for entry in needs_sync_entries:
        merged[entry.path] = entry
    entries = sorted(merged.values(), key=lambda item: (item.updated_at, item.path))
    if limit is not None and limit > 0:
        return entries[:limit]
    return entries


def _extract_confidence(parsed: Dict[str, Any]) -> float:
    raw = parsed.get("confidence")
    if not isinstance(raw, (int, float)) or isinstance(raw, bool):
        raise ValueError("confidence must be a number")
    value = float(raw)
    if value < 0.0 or value > 1.0:
        raise ValueError("confidence must be in range [0.0, 1.0]")
    return value


def _normalize_llm_recipe_payload(parsed: Dict[str, Any]) -> Dict[str, Any]:
    normalized = deepcopy(parsed)
    ingredients = normalized.get("ingredients")
    if not isinstance(ingredients, list):
        return normalized
    for ingredient in ingredients:
        if not isinstance(ingredient, dict):
            continue
        _normalize_ingredient_unit(ingredient)
    normalized["ingredients"] = _collapse_duplicate_ranges(ingredients)
    return normalized


def _normalize_ingredient_unit(ingredient: Dict[str, Any]) -> None:
    raw_unit = ingredient.get("unit")
    if not isinstance(raw_unit, str):
        return
    unit = " ".join(raw_unit.strip().casefold().split())
    mapped = UNIT_ALIASES.get(unit, raw_unit.strip())
    ingredient["unit"] = mapped
    if mapped in {"по вкусу"}:
        ingredient["amount"] = None
        return
    if ingredient.get("amount") is None and mapped in {"шт", "зубчик", "ч.л.", "ст.л.", "пучок"}:
        _fill_amount_from_name_or_note(ingredient)


def _fill_amount_from_name_or_note(ingredient: Dict[str, Any]) -> None:
    name = str(ingredient.get("name") or "")
    note = str(ingredient.get("note") or "")
    text = f"{name} {note}".casefold()
    if "пол" in text:
        ingredient["amount"] = 0.5


def _collapse_duplicate_ranges(ingredients: list[Dict[str, Any]]) -> list[Dict[str, Any]]:
    collapsed: list[Dict[str, Any]] = []
    index = 0
    while index < len(ingredients):
        current = ingredients[index]
        if not isinstance(current, dict):
            index += 1
            continue
        if index + 1 >= len(ingredients):
            collapsed.append(current)
            index += 1
            continue

        nxt = ingredients[index + 1]
        if not isinstance(nxt, dict):
            collapsed.append(current)
            index += 1
            continue

        if _is_range_pair(current, nxt):
            merged = deepcopy(current)
            current_amount = float(current["amount"])
            next_amount = float(nxt["amount"])
            merged["amount"] = (current_amount + next_amount) / 2.0
            collapsed.append(merged)
            index += 2
            continue

        collapsed.append(current)
        index += 1
    return collapsed


def _is_range_pair(left: Dict[str, Any], right: Dict[str, Any]) -> bool:
    left_name = str(left.get("name") or "").strip().casefold()
    right_name = str(right.get("name") or "").strip().casefold()
    left_unit = left.get("unit")
    right_unit = right.get("unit")
    left_amount = left.get("amount")
    right_amount = right.get("amount")
    if not left_name or left_name != right_name:
        return False
    if left_unit != right_unit or left_unit is None:
        return False
    if not _is_number(left_amount) or not _is_number(right_amount):
        return False
    if float(left_amount) == float(right_amount):
        return False
    return True


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)
