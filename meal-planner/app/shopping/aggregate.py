from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Dict, Iterable, List, Tuple

from app.planner import WeeklyPlan
from app.sync.store import StoredRecipe


INGREDIENT_ALIASES = {
    "яйца": "яйцо",
    "яйцо куриное": "яйцо",
    "яйца куриные": "яйцо",
    "куриное яйцо": "яйцо",
    "куриные яйца": "яйцо",
    "огурец": "огурцы",
    "огурец свежий": "огурцы",
    "свежий огурец": "огурцы",
    "огурцы свежие": "огурцы",
    "помидор": "помидоры",
    "помидор свежий": "помидоры",
    "свежий помидор": "помидоры",
    "помидоры свежие": "помидоры",
    "томат": "помидоры",
    "томаты": "помидоры",
    "томаты свежие": "помидоры",
}


@dataclass(frozen=True)
class ShoppingAmount:
    name: str
    unit: str
    amount: float


@dataclass(frozen=True)
class ShoppingSpecialItem:
    name: str
    source_recipe: str


@dataclass(frozen=True)
class ShoppingList:
    totals: List[ShoppingAmount]
    null_amounts: List[ShoppingSpecialItem]
    to_taste: List[ShoppingSpecialItem]


@dataclass(frozen=True)
class SectionedShoppingList:
    totals_by_section: Dict[str, List[ShoppingAmount]]
    null_amounts_by_section: Dict[str, List[ShoppingSpecialItem]]
    to_taste_by_section: Dict[str, List[ShoppingSpecialItem]]


def aggregate_ingredients(recipes: Iterable[StoredRecipe]) -> ShoppingList:
    totals: Dict[Tuple[str, str], ShoppingAmount] = {}
    null_amounts: List[ShoppingSpecialItem] = []
    to_taste: List[ShoppingSpecialItem] = []

    for recipe in recipes:
        recipe_title = recipe.recipe_payload["title"]
        for ingredient in recipe.recipe_payload["ingredients"]:
            raw_name = ingredient["name"]
            normalized_name = ingredient_key(raw_name)
            display_name = raw_name.strip()
            if " ".join(display_name.casefold().split()) in INGREDIENT_ALIASES:
                display_name = normalized_name.capitalize() if display_name[:1].isupper() else normalized_name
            amount = ingredient["amount"]
            unit = ingredient["unit"]

            if unit == "по вкусу":
                to_taste.append(
                    ShoppingSpecialItem(name=display_name, source_recipe=recipe_title)
                )
                continue

            if amount is None or unit is None:
                null_amounts.append(
                    ShoppingSpecialItem(name=display_name, source_recipe=recipe_title)
                )
                continue

            key = (normalized_name, unit)
            current = totals.get(key)
            if current is None:
                totals[key] = ShoppingAmount(
                    name=display_name,
                    unit=unit,
                    amount=float(amount),
                )
                continue

            totals[key] = ShoppingAmount(
                name=current.name,
                unit=unit,
                amount=current.amount + float(amount),
            )

    return ShoppingList(
        totals=sorted(totals.values(), key=lambda item: (item.name.casefold(), item.unit)),
        null_amounts=sorted(null_amounts, key=lambda item: (item.name.casefold(), item.source_recipe.casefold())),
        to_taste=sorted(to_taste, key=lambda item: (item.name.casefold(), item.source_recipe.casefold())),
    )


def aggregate_weekly_plan(plan: WeeklyPlan) -> ShoppingList:
    return aggregate_ingredients(plan.recipes)


def format_shopping_list(shopping_list: ShoppingList) -> Tuple[str, ...]:
    lines: List[str] = []
    if shopping_list.totals:
        lines.append("totals:")
        for item in shopping_list.totals:
            lines.append(f"- {item.name}: {item.amount:g} {item.unit}")
    if shopping_list.null_amounts:
        lines.append("null_amounts:")
        for item in shopping_list.null_amounts:
            lines.append(f"- {item.name} [{item.source_recipe}]")
    if shopping_list.to_taste:
        lines.append("по вкусу:")
        for item in shopping_list.to_taste:
            lines.append(f"- {item.name} [{item.source_recipe}]")
    return tuple(lines)


def ingredient_key(name: str) -> str:
    key = " ".join(name.casefold().split())
    return INGREDIENT_ALIASES.get(key, key)


def group_shopping_list_by_section(
    shopping_list: ShoppingList,
    ingredient_sections: Dict[str, str],
    *,
    default_section: str = "other",
) -> SectionedShoppingList:
    totals_by_section: Dict[str, List[ShoppingAmount]] = defaultdict(list)
    null_amounts_by_section: Dict[str, List[ShoppingSpecialItem]] = defaultdict(list)
    to_taste_by_section: Dict[str, List[ShoppingSpecialItem]] = defaultdict(list)
    sections = {ingredient_key(name): section for name, section in ingredient_sections.items()}

    for item in shopping_list.totals:
        section = sections.get(ingredient_key(item.name), default_section)
        totals_by_section[section].append(item)
    for item in shopping_list.null_amounts:
        section = sections.get(ingredient_key(item.name), default_section)
        null_amounts_by_section[section].append(item)
    for item in shopping_list.to_taste:
        section = sections.get(ingredient_key(item.name), default_section)
        to_taste_by_section[section].append(item)

    return SectionedShoppingList(
        totals_by_section=_sort_section_mapping(totals_by_section),
        null_amounts_by_section=_sort_section_mapping(null_amounts_by_section),
        to_taste_by_section=_sort_section_mapping(to_taste_by_section),
    )


def format_sectioned_shopping_list(sectioned: SectionedShoppingList) -> Tuple[str, ...]:
    lines: List[str] = []
    all_sections = sorted(
        set(sectioned.totals_by_section)
        | set(sectioned.null_amounts_by_section)
        | set(sectioned.to_taste_by_section)
    )
    for section in all_sections:
        lines.append(f"{section}:")
        for item in sectioned.totals_by_section.get(section, []):
            lines.append(f"- {item.name}: {item.amount:g} {item.unit}")
        if section in sectioned.null_amounts_by_section:
            lines.append("  null_amounts:")
            for item in sectioned.null_amounts_by_section[section]:
                lines.append(f"  - {item.name} [{item.source_recipe}]")
        if section in sectioned.to_taste_by_section:
            lines.append("  по вкусу:")
            for item in sectioned.to_taste_by_section[section]:
                lines.append(f"  - {item.name} [{item.source_recipe}]")
    return tuple(lines)


def _sort_section_mapping(mapping: Dict[str, List[ShoppingAmount]] | Dict[str, List[ShoppingSpecialItem]]):
    result = {}
    for section in sorted(mapping):
        items = mapping[section]
        result[section] = sorted(items, key=lambda item: tuple(str(part).casefold() for part in item.__dict__.values()))
    return result
