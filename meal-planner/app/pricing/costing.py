from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Tuple

from app.pricing.store import PriceBookEntry, PriceBookStore
from app.shopping import ShoppingAmount, ShoppingList


UNIT_TO_BASE: Dict[str, Tuple[str, float]] = {
    "г": ("г", 1.0),
    "кг": ("г", 1000.0),
    "мл": ("мл", 1.0),
    "л": ("мл", 1000.0),
    "шт": ("шт", 1.0),
    "зубчик": ("зубчик", 1.0),
    "щепотка": ("щепотка", 1.0),
    "ч.л.": ("ч.л.", 1.0),
    "ст.л.": ("ст.л.", 1.0),
    "стакан": ("стакан", 1.0),
    "пучок": ("пучок", 1.0),
}


@dataclass(frozen=True)
class PricedShoppingItem:
    name: str
    requested_amount: float
    requested_unit: str
    base_amount: float
    base_unit: str
    price_per_base_unit: float
    currency: str
    total_price: float


@dataclass(frozen=True)
class UnpricedShoppingItem:
    name: str
    requested_amount: float
    requested_unit: str
    reason: str


@dataclass(frozen=True)
class CostEstimate:
    priced_items: List[PricedShoppingItem]
    without_price: List[UnpricedShoppingItem]
    totals_by_currency: Dict[str, float]


def estimate_shopping_list_cost(
    shopping_list: ShoppingList,
    *,
    price_book_store: PriceBookStore,
) -> CostEstimate:
    price_index = _build_price_index(price_book_store.list_entries())
    priced_items: List[PricedShoppingItem] = []
    without_price: List[UnpricedShoppingItem] = []
    totals_by_currency: Dict[str, float] = {}

    for item in shopping_list.totals:
        normalized = _normalize_amount(item)
        if normalized is None:
            without_price.append(
                UnpricedShoppingItem(
                    name=item.name,
                    requested_amount=item.amount,
                    requested_unit=item.unit,
                    reason="unsupported unit conversion",
                )
            )
            continue

        lookup_key = (_normalize_name(item.name), normalized[1])
        price_entry = price_index.get(lookup_key)
        if price_entry is None:
            without_price.append(
                UnpricedShoppingItem(
                    name=item.name,
                    requested_amount=item.amount,
                    requested_unit=item.unit,
                    reason="price not found",
                )
            )
            continue

        base_amount, base_unit = normalized
        total_price = base_amount * price_entry.price_per_unit
        priced_items.append(
            PricedShoppingItem(
                name=item.name,
                requested_amount=item.amount,
                requested_unit=item.unit,
                base_amount=base_amount,
                base_unit=base_unit,
                price_per_base_unit=price_entry.price_per_unit,
                currency=price_entry.currency,
                total_price=total_price,
            )
        )
        totals_by_currency[price_entry.currency] = totals_by_currency.get(price_entry.currency, 0.0) + total_price

    return CostEstimate(
        priced_items=sorted(priced_items, key=lambda item: (item.name.casefold(), item.requested_unit)),
        without_price=sorted(without_price, key=lambda item: (item.name.casefold(), item.requested_unit)),
        totals_by_currency=dict(sorted(totals_by_currency.items())),
    )


def format_cost_estimate(cost_estimate: CostEstimate) -> Tuple[str, ...]:
    lines: List[str] = []
    if cost_estimate.priced_items:
        lines.append("priced_items:")
        for item in cost_estimate.priced_items:
            lines.append(
                f"- {item.name}: {item.requested_amount:g} {item.requested_unit} -> "
                f"{item.total_price:.2f} {item.currency}"
            )
    if cost_estimate.without_price:
        lines.append("without_price:")
        for item in cost_estimate.without_price:
            lines.append(
                f"- {item.name}: {item.requested_amount:g} {item.requested_unit} ({item.reason})"
            )
    if cost_estimate.totals_by_currency:
        lines.append("total:")
        for currency, total in cost_estimate.totals_by_currency.items():
            lines.append(f"- {total:.2f} {currency}")
    return tuple(lines)


def _build_price_index(entries: Iterable[PriceBookEntry]) -> Dict[Tuple[str, str], PriceBookEntry]:
    index: Dict[Tuple[str, str], PriceBookEntry] = {}
    for entry in entries:
        normalized = _normalize_price_entry(entry)
        if normalized is None:
            continue
        index[(_normalize_name(entry.ingredient_name), normalized[1])] = PriceBookEntry(
            ingredient_name=entry.ingredient_name,
            unit=normalized[1],
            price_per_unit=normalized[0],
            currency=entry.currency,
            source=entry.source,
            updated_at=entry.updated_at,
        )
    return index


def _normalize_price_entry(entry: PriceBookEntry) -> Optional[Tuple[float, str]]:
    base = UNIT_TO_BASE.get(entry.unit)
    if base is None:
        return None
    base_unit, factor = base
    return entry.price_per_unit / factor, base_unit


def _normalize_amount(item: ShoppingAmount) -> Optional[Tuple[float, str]]:
    base = UNIT_TO_BASE.get(item.unit)
    if base is None:
        return None
    base_unit, factor = base
    return item.amount * factor, base_unit


def _normalize_name(value: str) -> str:
    return " ".join(value.strip().casefold().split())
