from __future__ import annotations

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.pricing import PriceBookStore, estimate_shopping_list_cost, format_cost_estimate
from app.shopping import ShoppingAmount, ShoppingList


def main() -> int:
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
    for line in format_cost_estimate(estimate):
        print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
