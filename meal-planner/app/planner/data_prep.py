from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import random
from typing import Dict, Iterable, List, Tuple

from app.index.file_index import FileIndex
from app.sync.recipe_schema import ALLOWED_CATEGORIES, validate_recipe
from app.sync.store import RecipeStore, StoredRecipe


DEFAULT_WEEKLY_QUOTAS: Dict[str, int] = {
    "soup": 1,
    "main": 2,
    "salad": 1,
    "breakfast": 2,
    "snack": 1,
    "drink": 1,
}


@dataclass(frozen=True)
class PreparedPlanningData:
    recipes: List[StoredRecipe]
    counts_by_category: Dict[str, int]


@dataclass(frozen=True)
class CategoryAvailability:
    required: int
    available: int


@dataclass(frozen=True)
class AvailabilityCheck:
    is_sufficient: bool
    by_category: Dict[str, CategoryAvailability]
    missing_categories: Dict[str, int]


@dataclass(frozen=True)
class WeeklyPlan:
    recipes: List[StoredRecipe]
    by_category: Dict[str, List[StoredRecipe]]
    quotas: Dict[str, int]


def prepare_planning_data(
    *,
    file_index: FileIndex,
    recipe_store: RecipeStore,
) -> PreparedPlanningData:
    synced_entries = file_index.get_by_status("synced")
    source_paths = [entry.path for entry in synced_entries]
    stored_recipes = recipe_store.get_recipes_by_source_paths(source_paths)

    validated_recipes: List[StoredRecipe] = []
    counts = Counter()
    for recipe in stored_recipes:
        payload = validate_recipe(recipe.recipe_payload)
        category = payload["category"]
        validated_recipes.append(
            StoredRecipe(
                source_path=recipe.source_path,
                content_hash=recipe.content_hash,
                category=recipe.category,
                confidence=recipe.confidence,
                recipe_payload=payload,
                updated_at=recipe.updated_at,
            )
        )
        counts[category] += 1

    return PreparedPlanningData(
        recipes=validated_recipes,
        counts_by_category={category: counts.get(category, 0) for category in ALLOWED_CATEGORIES},
    )


def check_category_availability(
    recipes: Iterable[StoredRecipe],
    *,
    quotas: Dict[str, int] | None = None,
) -> AvailabilityCheck:
    active_quotas = dict(DEFAULT_WEEKLY_QUOTAS if quotas is None else quotas)
    counts = Counter()
    for recipe in recipes:
        category = recipe.recipe_payload["category"]
        counts[category] += 1

    by_category: Dict[str, CategoryAvailability] = {}
    missing_categories: Dict[str, int] = {}
    for category, required in active_quotas.items():
        available = counts.get(category, 0)
        by_category[category] = CategoryAvailability(required=required, available=available)
        if available < required:
            missing_categories[category] = required - available

    return AvailabilityCheck(
        is_sufficient=not missing_categories,
        by_category=by_category,
        missing_categories=missing_categories,
    )


def format_availability_report(check: AvailabilityCheck) -> Tuple[str, ...]:
    lines = []
    for category, item in check.by_category.items():
        status = "ok" if item.available >= item.required else "missing"
        lines.append(
            f"- {category}: available={item.available} required={item.required} status={status}"
        )
    return tuple(lines)


def build_weekly_plan(
    recipes: Iterable[StoredRecipe],
    *,
    quotas: Dict[str, int] | None = None,
    rng: random.Random | None = None,
) -> WeeklyPlan:
    active_quotas = dict(DEFAULT_WEEKLY_QUOTAS if quotas is None else quotas)
    availability = check_category_availability(recipes, quotas=active_quotas)
    if not availability.is_sufficient:
        missing = ", ".join(
            f"{category}:+{count}" for category, count in availability.missing_categories.items()
        )
        raise ValueError(f"Not enough recipes for weekly plan: {missing}")

    recipes_by_category: Dict[str, List[StoredRecipe]] = {category: [] for category in active_quotas}
    for recipe in recipes:
        category = recipe.recipe_payload["category"]
        if category in recipes_by_category:
            recipes_by_category[category].append(recipe)

    random_source = rng if rng is not None else random.Random()
    selected_by_category: Dict[str, List[StoredRecipe]] = {}
    selected_recipes: List[StoredRecipe] = []
    for category, required in active_quotas.items():
        pool = list(recipes_by_category.get(category, []))
        picked = random_source.sample(pool, required)
        selected_by_category[category] = picked
        selected_recipes.extend(picked)

    return WeeklyPlan(
        recipes=selected_recipes,
        by_category=selected_by_category,
        quotas=active_quotas,
    )


def format_weekly_plan(plan: WeeklyPlan) -> Tuple[str, ...]:
    lines = []
    for category, recipes in plan.by_category.items():
        lines.append(f"{category}:")
        for recipe in recipes:
            title = recipe.recipe_payload["title"]
            source_path = recipe.recipe_payload["source_path"]
            lines.append(f"- {title} [{source_path}]")
    return tuple(lines)
