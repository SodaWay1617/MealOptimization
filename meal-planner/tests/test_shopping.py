from __future__ import annotations

import unittest

from app.shopping import (
    aggregate_ingredients,
    format_sectioned_shopping_list,
    group_shopping_list_by_section,
)
from app.sync.store import StoredRecipe


def _recipe(title: str, category: str, ingredients):
    return StoredRecipe(
        source_path=f"/tmp/{title}.md",
        content_hash=title,
        category=category,
        confidence=1.0,
        recipe_payload={
            "title": title,
            "category": category,
            "servings": 1,
            "ingredients": ingredients,
            "steps": ["step"],
            "source_path": f"/tmp/{title}.md",
            "notes": None,
        },
        updated_at=0.0,
    )


class ShoppingAggregationTests(unittest.TestCase):
    def test_merges_chicken_egg_aliases_without_merging_other_eggs(self) -> None:
        recipes = [
            _recipe("A", "breakfast", [{"name": "яйца", "amount": 2, "unit": "шт"}]),
            _recipe("B", "breakfast", [
                {"name": "яйцо", "amount": 1, "unit": "шт"},
                {"name": "перепелиные яйца", "amount": 3, "unit": "шт"},
                {"name": "куриное яйцо", "amount": 50, "unit": "г"},
            ]),
        ]
        totals = {(item.name, item.unit): item.amount for item in aggregate_ingredients(recipes).totals}
        self.assertEqual(totals, {("яйцо", "шт"): 3, ("яйцо", "г"): 50, ("перепелиные яйца", "шт"): 3})

    def test_aggregate_ingredients_sums_by_name_and_unit(self) -> None:
        recipes = [
            _recipe(
                "A",
                "breakfast",
                [
                    {"name": "Яйцо", "amount": 2, "unit": "шт", "note": None},
                    {"name": "Соль", "amount": None, "unit": "по вкусу", "note": None},
                ],
            ),
            _recipe(
                "B",
                "breakfast",
                [
                    {"name": "яйцо", "amount": 3, "unit": "шт", "note": None},
                    {"name": "Молоко", "amount": None, "unit": None, "note": None},
                ],
            ),
        ]

        shopping_list = aggregate_ingredients(recipes)

        self.assertEqual(len(shopping_list.totals), 1)
        self.assertEqual(shopping_list.totals[0].name, "Яйцо")
        self.assertEqual(shopping_list.totals[0].amount, 5.0)
        self.assertEqual(shopping_list.totals[0].unit, "шт")
        self.assertEqual(len(shopping_list.null_amounts), 1)
        self.assertEqual(shopping_list.null_amounts[0].name, "Молоко")
        self.assertEqual(len(shopping_list.to_taste), 1)
        self.assertEqual(shopping_list.to_taste[0].name, "Соль")

    def test_group_shopping_list_by_section(self) -> None:
        recipes = [
            _recipe(
                "A",
                "breakfast",
                [
                    {"name": "Яйцо", "amount": 2, "unit": "шт", "note": None},
                    {"name": "Авокадо", "amount": 1, "unit": "шт", "note": None},
                ],
            )
        ]
        shopping_list = aggregate_ingredients(recipes)

        sectioned = group_shopping_list_by_section(
            shopping_list,
            {"яйцо": "dairy"},
        )

        self.assertIn("dairy", sectioned.totals_by_section)
        self.assertIn("other", sectioned.totals_by_section)
        rendered = "\n".join(format_sectioned_shopping_list(sectioned))
        self.assertIn("dairy:", rendered)
        self.assertIn("other:", rendered)

    def test_merges_plain_vegetables_but_preserves_distinct_products(self) -> None:
        recipe = _recipe("Salad", "salad", [
            {"name": "огурцы", "amount": 80, "unit": "г"},
            {"name": "огурец свежий", "amount": 40, "unit": "г"},
            {"name": "помидоры", "amount": 80, "unit": "г"},
            {"name": "томаты", "amount": 40, "unit": "г"},
            {"name": "помидоры черри", "amount": 50, "unit": "г"},
        ])
        totals = {item.name: item.amount for item in aggregate_ingredients([recipe]).totals}
        self.assertEqual(totals, {"огурцы": 120, "помидоры": 120, "помидоры черри": 50})


if __name__ == "__main__":
    unittest.main()
