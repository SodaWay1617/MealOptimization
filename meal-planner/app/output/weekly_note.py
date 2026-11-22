from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Dict, Iterable, List, Optional

from app.planner import WeeklyPlan
from app.pricing import CostEstimate
from app.shopping import ShoppingList, ShoppingSpecialItem
from app.sync.store import StoredRecipe


@dataclass(frozen=True)
class WeeklyNoteContext:
    title: str
    weekly_plan: Optional[WeeklyPlan]
    shopping_list: Optional[ShoppingList]
    cost_estimate: Optional[CostEstimate]
    warnings: List[str]


def default_week_title(today: Optional[date] = None) -> str:
    current = today or date.today()
    iso_year, iso_week, _ = current.isocalendar()
    return f"План питания недели {iso_year}-W{iso_week:02d}"


def render_weekly_note(context: WeeklyNoteContext) -> str:
    lines: List[str] = [f"# {context.title}", ""]
    lines.extend(_render_schedule_block(context.weekly_plan))
    lines.append("")
    lines.extend(_render_recipe_shopping_blocks(context.weekly_plan))
    lines.append("")
    lines.extend(_render_combined_shopping_block(context.shopping_list))
    lines.append("")
    lines.extend(_render_cost_block(context.cost_estimate))
    if context.warnings:
        lines.append("")
        lines.extend(_render_warnings_block(context.warnings))
    return "\n".join(lines).rstrip() + "\n"


def _render_schedule_block(weekly_plan: Optional[WeeklyPlan]) -> List[str]:
    lines: List[str] = ["## План по дням"]
    if weekly_plan is None:
        lines.append("_План пока не собран._")
        return lines

    slots = _resolve_week_slots(weekly_plan)
    lines.append("")
    lines.append("Понедельник / Вторник / Среда:")
    lines.extend(_render_day_group(slots, first_half=True))
    lines.append("")
    lines.append("Четверг / Пятница / Суббота:")
    lines.extend(_render_day_group(slots, first_half=False))
    return lines


def _render_day_group(slots: Dict[str, List[StoredRecipe]], *, first_half: bool) -> List[str]:
    breakfast = _pick_slot(slots, "breakfast", 0 if first_half else 1)
    soup = _pick_slot(slots, "soup", 0)
    salad = _pick_slot(slots, "salad", 0)
    main = _pick_slot(slots, "main", 0 if first_half else 1)
    snack = _pick_slot(slots, "snack", 0)
    drink = _pick_slot(slots, "drink", 0)

    recipes = [breakfast, soup, salad, main, snack, drink]
    return [f"- {_obsidian_link(recipe.recipe_payload['source_path'])}" for recipe in recipes if recipe is not None]


def _render_recipe_shopping_blocks(weekly_plan: Optional[WeeklyPlan]) -> List[str]:
    lines: List[str] = ["## Список продуктов по блюдам"]
    if weekly_plan is None:
        lines.append("_Список продуктов пока недоступен._")
        return lines

    slots = _resolve_week_slots(weekly_plan)
    block_specs = [
        ("Завтрак 1", _pick_slot(slots, "breakfast", 0)),
        ("Завтрак 2", _pick_slot(slots, "breakfast", 1)),
        ("Суп", _pick_slot(slots, "soup", 0)),
        ("Салат", _pick_slot(slots, "salad", 0)),
        ("Второе 1", _pick_slot(slots, "main", 0)),
        ("Второе 2", _pick_slot(slots, "main", 1)),
        ("Перекус", _pick_slot(slots, "snack", 0)),
        ("Напиток", _pick_slot(slots, "drink", 0)),
    ]
    for heading, recipe in block_specs:
        if recipe is None:
            continue
        lines.append("")
        lines.append(f"### {heading} — {_obsidian_link(recipe.recipe_payload['source_path'])}")
        lines.extend(_render_recipe_ingredients(recipe))
    return lines


def _render_recipe_ingredients(recipe: StoredRecipe) -> List[str]:
    lines: List[str] = []
    for ingredient in recipe.recipe_payload.get("ingredients", []):
        if not isinstance(ingredient, dict):
            continue
        name = str(ingredient.get("name") or "").strip()
        if not name:
            continue
        amount = ingredient.get("amount")
        unit = ingredient.get("unit")
        note = ingredient.get("note")
        lines.append(f"- {name} — {_format_amount(amount, unit, note)}")
    return lines or ["- _Ингредиенты не распознаны._"]


def _render_combined_shopping_block(shopping_list: Optional[ShoppingList]) -> List[str]:
    lines = ["## Объединённый итоговый список продуктов"]
    if shopping_list is None:
        lines.append("_Общий список пока недоступен._")
        return lines
    if shopping_list.totals:
        for item in shopping_list.totals:
            lines.append(f"- {item.name} — {item.amount:g} {item.unit}")
    if shopping_list.null_amounts:
        lines.append("")
        lines.append("### Без точного количества")
        for item in shopping_list.null_amounts:
            lines.append(f"- {item.name} [{item.source_recipe}]")
    if shopping_list.to_taste:
        lines.append("")
        lines.append("### По вкусу")
        for item in _dedupe_special_items(shopping_list.to_taste):
            lines.append(f"- {item.name}")
    if len(lines) == 1:
        lines.append("_Общий список пуст._")
    return lines


def _render_cost_block(cost_estimate: Optional[CostEstimate]) -> List[str]:
    lines = ["# 💰 **Оценка стоимости (ориентировочно)**", ""]
    lines.append("| Продукт | Цена, ₽ |")
    lines.append("| --- | --- |")
    rows = _build_cost_rows(cost_estimate)
    if rows:
        lines.extend(rows)
    else:
        lines.append("| | |")

    lines.append("")
    lines.append("### **Примерный итог:**")
    lines.append("")
    lines.append(f"### **{_format_planned_total(cost_estimate)}**")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("# 📌 Шаблон для итоговой записи")
    lines.append("")
    lines.append("**Цена (оценка / итог):**  ")
    lines.append(f"План: **{_format_planned_total(cost_estimate)}**  ")
    lines.append("Итог после покупки: **_____ ₽**")
    lines.append("")
    lines.append("# Комментарии")
    return lines


def _render_warnings_block(warnings: Iterable[str]) -> List[str]:
    lines = ["## Предупреждения"]
    for warning in warnings:
        lines.append(f"- {warning}")
    return lines


def _build_cost_rows(cost_estimate: Optional[CostEstimate]) -> List[str]:
    if cost_estimate is None:
        return []
    rows: List[str] = []
    for item in cost_estimate.priced_items:
        rows.append(f"| {item.name} | {item.total_price:.2f} |")
    for item in cost_estimate.without_price:
        rows.append(f"| {item.name} | неизвестно |")
    return rows


def _format_planned_total(cost_estimate: Optional[CostEstimate]) -> str:
    if cost_estimate is None or not cost_estimate.totals_by_currency:
        return "~? – ? ₽"
    rub_total = cost_estimate.totals_by_currency.get("RUB")
    if rub_total is None:
        currency, total = next(iter(cost_estimate.totals_by_currency.items()))
        return f"~{total:.2f} {currency}"
    return f"~{rub_total:.2f} ₽"


def default_week_filename(title: str, today: Optional[date] = None) -> str:
    current = today or date.today()
    sanitized = _sanitize_filename(title)
    return f"{current.isoformat()} - {sanitized}.md"


def save_weekly_note(content: str, output_dir: Path, filename: str) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    destination = output_dir / filename
    destination.write_text(content, encoding="utf-8")
    return destination


def _resolve_week_slots(weekly_plan: WeeklyPlan) -> Dict[str, List[StoredRecipe]]:
    return {category: list(recipes) for category, recipes in weekly_plan.by_category.items()}


def _pick_slot(slots: Dict[str, List[StoredRecipe]], category: str, index: int) -> Optional[StoredRecipe]:
    recipes = slots.get(category, [])
    if not recipes:
        return None
    if index < len(recipes):
        return recipes[index]
    return recipes[-1]


def _format_amount(amount: object, unit: object, note: object) -> str:
    if amount is None and unit == "по вкусу":
        return "по вкусу"
    if amount is None and unit is None:
        return str(note).strip() if isinstance(note, str) and note.strip() else "без количества"
    if amount is None:
        if isinstance(note, str) and note.strip():
            return f"{unit} ({note.strip()})"
        return str(unit)
    suffix = f" {unit}" if unit else ""
    if isinstance(note, str) and note.strip():
        return f"{amount:g}{suffix} ({note.strip()})"
    return f"{amount:g}{suffix}"


def _dedupe_special_items(items: List[ShoppingSpecialItem]) -> List[ShoppingSpecialItem]:
    seen = set()
    result: List[ShoppingSpecialItem] = []
    for item in items:
        key = item.name.casefold()
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result


def _obsidian_link(source_path: str) -> str:
    path = Path(source_path)
    return f"[[{path.stem}]]"


def _sanitize_filename(value: str) -> str:
    invalid = '<>:"/\\|?*'
    sanitized = "".join("_" if char in invalid else char for char in value.strip())
    return " ".join(sanitized.split()) or "Weekly Note"
