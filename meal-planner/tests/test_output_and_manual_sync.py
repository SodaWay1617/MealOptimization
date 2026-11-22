from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app.index.file_index import FileIndex
from app.manual_sync import ManualRecipeDraft, save_manual_recipe
from app.output import WeeklyNoteContext, render_weekly_note
from app.planner import WeeklyPlan
from app.pricing import CostEstimate, PricedShoppingItem, UnpricedShoppingItem
from app.shopping import ShoppingAmount, ShoppingList, ShoppingSpecialItem
from app.sync.store import RecipeStore, StoredRecipe


def _stored_recipe(title: str, category: str) -> StoredRecipe:
    return StoredRecipe(
        source_path=f"/tmp/{title}.md",
        content_hash=title,
        category=category,
        confidence=1.0,
        recipe_payload={
            "title": title,
            "category": category,
            "servings": 1,
            "ingredients": [{"name": "яйцо", "amount": 2, "unit": "шт", "note": None}],
            "steps": ["step"],
            "source_path": f"/tmp/{title}.md",
            "notes": None,
        },
        updated_at=0.0,
    )


class OutputAndManualSyncTests(unittest.TestCase):
    def test_render_weekly_note_contains_obsidian_links_and_cost_template(self) -> None:
        breakfast_one = _stored_recipe("Breakfast One", "breakfast")
        breakfast_two = _stored_recipe("Breakfast Two", "breakfast")
        soup = _stored_recipe("Soup One", "soup")
        salad = _stored_recipe("Salad One", "salad")
        main_one = _stored_recipe("Main One", "main")
        main_two = _stored_recipe("Main Two", "main")
        snack = _stored_recipe("Snack One", "snack")
        drink = _stored_recipe("Drink One", "drink")
        weekly_plan = WeeklyPlan(
            recipes=[breakfast_one, breakfast_two, soup, salad, main_one, main_two, snack, drink],
            by_category={
                "breakfast": [breakfast_one, breakfast_two],
                "soup": [soup],
                "salad": [salad],
                "main": [main_one, main_two],
                "snack": [snack],
                "drink": [drink],
            },
            quotas={"breakfast": 2, "soup": 1, "salad": 1, "main": 2, "snack": 1, "drink": 1},
        )
        shopping_list = ShoppingList(
            totals=[ShoppingAmount(name="Яйцо", unit="шт", amount=8)],
            null_amounts=[ShoppingSpecialItem(name="Молоко", source_recipe="Drink One")],
            to_taste=[ShoppingSpecialItem(name="Соль", source_recipe="Soup One")],
        )
        cost_estimate = CostEstimate(
            priced_items=[
                PricedShoppingItem(
                    name="Яйцо",
                    requested_amount=8,
                    requested_unit="шт",
                    base_amount=8,
                    base_unit="шт",
                    price_per_base_unit=12.0,
                    currency="RUB",
                    total_price=96.0,
                )
            ],
            without_price=[
                UnpricedShoppingItem(
                    name="Молоко",
                    requested_amount=1.5,
                    requested_unit="л",
                    reason="price not found",
                )
            ],
            totals_by_currency={"RUB": 96.0},
        )

        note = render_weekly_note(
            WeeklyNoteContext(
                title="Test Week",
                weekly_plan=weekly_plan,
                shopping_list=shopping_list,
                cost_estimate=cost_estimate,
                warnings=["Recipes pending sync: 2"],
            )
        )

        self.assertIn("# Test Week", note)
        self.assertIn("[[Breakfast One]]", note)
        self.assertNotIn("Breakfast One [[Breakfast One]]", note)
        self.assertIn("Понедельник / Вторник / Среда:", note)
        self.assertIn("Четверг / Пятница / Суббота:", note)
        self.assertIn("## Список продуктов по блюдам", note)
        self.assertIn("## Объединённый итоговый список продуктов", note)
        self.assertIn("| Продукт | Цена, ₽ |", note)
        self.assertIn("| Яйцо | 96.00 |", note)
        self.assertIn("| Молоко | неизвестно |", note)
        self.assertIn("### **~96.00 ₽**", note)
        self.assertIn("План: **~96.00 ₽**", note)
        self.assertIn("Итог после покупки: **_____ ₽**", note)
        self.assertIn("# Комментарии", note)
        self.assertIn("Recipes pending sync: 2", note)

    def test_save_manual_recipe_marks_file_as_synced(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            source = tmp_path / "recipe.md"
            source.write_text("# Recipe\n", encoding="utf-8")
            file_index = FileIndex(tmp_path / "file_index.sqlite")
            recipe_store = RecipeStore(tmp_path / "recipes.sqlite")

            draft = ManualRecipeDraft(
                source_path=str(source),
                category="breakfast",
                title="Manual Recipe",
                servings=2,
                ingredients=[
                    {"name": "яйцо", "amount": 2, "unit": "шт", "note": None},
                ],
                steps=["Mix", "Cook"],
                notes="manual",
                confidence=1.0,
            )

            save_manual_recipe(draft=draft, file_index=file_index, recipe_store=recipe_store)

            entry = file_index.get_by_path(source)
            stored = recipe_store.get_recipes_by_source_paths([source])
            self.assertIsNotNone(entry)
            assert entry is not None
            self.assertEqual(entry.status, "synced")
            self.assertEqual(len(stored), 1)
            self.assertEqual(stored[0].recipe_payload["title"], "Manual Recipe")


if __name__ == "__main__":
    unittest.main()
