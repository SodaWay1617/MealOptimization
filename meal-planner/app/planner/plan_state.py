from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

from app.planner.data_prep import WeeklyPlan
from app.sync.store import RecipeStore, StoredRecipe


@dataclass(frozen=True)
class SavedWeeklyPlan:
    title: str
    quotas: Dict[str, int]
    by_category_paths: Dict[str, List[str]]


def save_weekly_plan_state(weekly_plan: WeeklyPlan, *, title: str, destination: Path) -> Path:
    payload = {
        "title": title,
        "quotas": weekly_plan.quotas,
        "by_category_paths": {
            category: [recipe.source_path for recipe in recipes]
            for category, recipes in weekly_plan.by_category.items()
        },
    }
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return destination


def load_weekly_plan_state(path: Path) -> SavedWeeklyPlan:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return SavedWeeklyPlan(
        title=str(payload["title"]),
        quotas={str(key): int(value) for key, value in dict(payload["quotas"]).items()},
        by_category_paths={
            str(category): [str(item) for item in values]
            for category, values in dict(payload["by_category_paths"]).items()
        },
    )


def hydrate_weekly_plan(saved: SavedWeeklyPlan, *, recipe_store: RecipeStore) -> WeeklyPlan:
    by_category: Dict[str, List[StoredRecipe]] = {}
    recipes: List[StoredRecipe] = []
    for category, source_paths in saved.by_category_paths.items():
        stored = recipe_store.get_recipes_by_source_paths(source_paths)
        recipe_map = {item.source_path: item for item in stored}
        ordered = [recipe_map[path] for path in source_paths if path in recipe_map]
        by_category[category] = ordered
        recipes.extend(ordered)
    return WeeklyPlan(
        recipes=recipes,
        by_category=by_category,
        quotas=dict(saved.quotas),
    )


def default_plan_state_path(note_path: Path) -> Path:
    return note_path.with_suffix(".plan.json")


def rebuild_weekly_plan_slot(
    current_plan: WeeklyPlan,
    *,
    all_recipes: List[StoredRecipe],
    category: str,
    slot_index: int = 0,
) -> WeeklyPlan:
    current_slots = list(current_plan.by_category.get(category, []))
    if not current_slots:
        raise ValueError(f"Current plan has no recipes in category '{category}'")
    if slot_index < 0 or slot_index >= len(current_slots):
        raise ValueError(f"Slot index out of range for category '{category}': {slot_index + 1}")

    used_paths = {recipe.source_path for recipe in current_plan.recipes}
    current_recipe = current_slots[slot_index]
    used_paths.discard(current_recipe.source_path)

    candidates = [
        recipe
        for recipe in all_recipes
        if recipe.recipe_payload["category"] == category and recipe.source_path not in used_paths
    ]
    if not candidates:
        raise ValueError(f"No replacement candidates available for category '{category}'")

    replacement = candidates[0]
    for candidate in candidates:
        if candidate.source_path != current_recipe.source_path:
            replacement = candidate
            break
    if replacement.source_path == current_recipe.source_path and len(candidates) == 1:
        raise ValueError(f"No alternative recipe available for category '{category}'")

    updated_by_category = {key: list(value) for key, value in current_plan.by_category.items()}
    updated_by_category[category][slot_index] = replacement

    updated_recipes: List[StoredRecipe] = []
    for recipes in updated_by_category.values():
        updated_recipes.extend(recipes)

    return WeeklyPlan(
        recipes=updated_recipes,
        by_category=updated_by_category,
        quotas=dict(current_plan.quotas),
    )
