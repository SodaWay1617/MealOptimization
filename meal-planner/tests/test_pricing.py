from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from app.pricing import (
    PriceBookStore,
    estimate_shopping_list_cost,
    export_price_book_seed_from_recipes,
    load_price_book_seed,
)
from app.shopping import ShoppingAmount, ShoppingList
from app.sync.store import RecipeStore


class PricingTests(unittest.TestCase):
    def test_estimate_cost_converts_units_and_marks_missing_prices(self) -> None:
        store = PriceBookStore(Path(":memory:"))
        store.upsert_entry(ingredient_name="рис", unit="г", price_per_unit=0.2, source="test")
        store.upsert_entry(ingredient_name="молоко", unit="мл", price_per_unit=0.1, source="test")

        shopping_list = ShoppingList(
            totals=[
                ShoppingAmount(name="рис", unit="кг", amount=1.5),
                ShoppingAmount(name="молоко", unit="л", amount=2),
                ShoppingAmount(name="авокадо", unit="шт", amount=3),
            ],
            null_amounts=[],
            to_taste=[],
        )

        estimate = estimate_shopping_list_cost(shopping_list, price_book_store=store)

        self.assertEqual(len(estimate.priced_items), 2)
        self.assertAlmostEqual(estimate.totals_by_currency["RUB"], 500.0, places=2)
        self.assertEqual(len(estimate.without_price), 1)
        self.assertEqual(estimate.without_price[0].name, "авокадо")

    def test_price_book_store_crud(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "price_book.sqlite"
            store = PriceBookStore(db_path)
            store.upsert_entry(ingredient_name="сыр", unit="г", price_per_unit=0.5)

            entry = store.get_entry("сыр", "г")
            self.assertIsNotNone(entry)
            assert entry is not None
            self.assertEqual(entry.ingredient_name, "сыр")
            self.assertTrue(store.delete_entry("сыр", "г"))
            self.assertIsNone(store.get_entry("сыр", "г"))

    def test_export_and_load_price_book_seed_sorted_by_usage(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            recipes_db = tmp_path / "recipes.sqlite"
            seed_path = tmp_path / "price_book.seed.json"
            source = tmp_path / "recipe.md"
            source.write_text("# Recipe\n", encoding="utf-8")

            recipe_store = RecipeStore(recipes_db)
            recipe_store.upsert_recipe(
                source_path=str(source),
                content_hash="hash-1",
                category="salad",
                recipe_payload={
                    "title": "Recipe",
                    "category": "salad",
                    "servings": 1,
                    "ingredients": [
                        {"name": "авокадо", "amount": 1, "unit": "шт", "note": None},
                        {"name": "сыр", "amount": 100, "unit": "г", "note": None},
                        {"name": "сыр", "amount": 50, "unit": "г", "note": None},
                    ],
                    "steps": ["step"],
                    "source_path": str(source),
                    "notes": None,
                },
                confidence=1.0,
            )

            count = export_price_book_seed_from_recipes(recipes_db, seed_path)
            self.assertEqual(count, 2)

            payload = json.loads(seed_path.read_text(encoding="utf-8"))
            self.assertIn("defaults", payload)
            self.assertEqual(len(payload["defaults"]), 2)
            self.assertEqual(payload["defaults"][0]["ingredient_name"], "сыр")
            self.assertEqual(payload["defaults"][0]["usage_count"], 2)
            self.assertEqual(payload["defaults"][1]["ingredient_name"], "авокадо")
            self.assertEqual(payload["defaults"][1]["usage_count"], 1)

            entries = load_price_book_seed(seed_path)
            self.assertEqual(len(entries), 2)
            self.assertEqual(entries[0].price_per_unit, None)
            self.assertEqual(entries[0].usage_count, 2)
            self.assertEqual(
                [(entry.ingredient_name, entry.unit, entry.usage_count) for entry in entries],
                [("сыр", "г", 2), ("авокадо", "шт", 1)],
            )


if __name__ == "__main__":
    unittest.main()
