from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from math import isfinite
import re
from statistics import mean
from urllib.parse import urlsplit

from app.web.stores import StoreError


PACKAGE = re.compile(r"(\d+(?:[.,]\d+)?)\s*(кг|мл|шт|г|л)\b", re.I)
UNITS = {"кг": ("г", 1000), "г": ("г", 1), "л": ("мл", 1000), "мл": ("мл", 1), "шт": ("шт", 1)}
MOSCOW_TIME = timezone(timedelta(hours=3))
REASONS = {"not_found", "unavailable", "no_price", "unit"}


def lenta_product_id(link):
    if not isinstance(link, str) or len(link) > 1500:
        raise ValueError("Вставьте ссылку на товар с сайта lenta.com.")
    parsed = urlsplit(link.strip())
    match = re.fullmatch(r"/product/(?:[^/]+-)?([0-9]{1,12})/?", parsed.path)
    if parsed.scheme != "https" or parsed.hostname not in ("lenta.com", "www.lenta.com") or not match:
        raise ValueError("Вставьте ссылку на карточку товара с сайта lenta.com.")
    return int(match[1])


def unit_price(product, unit):
    price = product.get("price")
    if type(price) not in (int, float) or not isfinite(price) or price <= 0:
        return None
    if product["unit"] == "quanta" and unit == "г":
        return price / product["weightGrams"]
    if product["unit"] != "шт":
        return None
    for amount, raw_unit in PACKAGE.findall(f'{product.get("package") or ""} {product["name"]}'):
        normalized, multiplier = UNITS[raw_unit.lower()]
        size = float(amount.replace(",", ".")) * multiplier
        if normalized == unit and size > 0:
            return price / size
    return None


def estimate_portion(store, ingredients, context, links=None):
    links = {} if links is None else links
    if not isinstance(links, dict) or len(links) > len(ingredients):
        raise ValueError("Проверьте ссылки на товары.")
    replacements = {}
    for key, link in links.items():
        if not isinstance(key, str) or not re.fullmatch(r"[0-9]{1,2}", key) or int(key) >= len(ingredients):
            raise ValueError("Выберите ингредиент для ссылки.")
        product_id = lenta_product_id(link)
        replacements[int(key)] = (link.strip(), product_id)

    def estimate(position_item):
        position, item = position_item
        name, unit, amount = item["name"], item["unit"], item["amount"]
        line = {"index": position, "name": name, "rub": None}
        replacement = replacements.get(position)
        query = re.sub(r"\([^)]*\)|\b(сырой|сырая|сырое|свежий|свежая|свежее)\b", "", name, flags=re.I).strip() or name
        try:
            if replacement:
                line["link"] = replacement[0]
                products = [store.product_details(replacement[1], context)]
                line["product"] = products[0]["name"]
            else:
                products = store.search(query, context)
        except StoreError:
            return dict(line, reason="unavailable")
        hint = re.search(r"[а-яёa-z]{3,}", query.casefold())
        matches = [product for product in products
                   if replacement or not hint or hint[0][:4] in product["name"].casefold()]
        if not matches:
            return dict(line, reason="not_found")
        priced = [product for product in matches if type(product.get("price")) in (int, float) and product["price"] > 0]
        if not priced:
            return dict(line, reason="no_price")
        prices = [price for product in priced if (price := unit_price(product, unit)) is not None]
        return dict(line, rub=round(mean(prices) * amount, 2)) if prices else dict(line, reason="unit")

    with ThreadPoolExecutor(max_workers=3) as workers:
        items = list(workers.map(estimate, ((i, item) for i, item in enumerate(ingredients) if item["amount"] is not None)))
    priced = [item["rub"] for item in items if item["rub"] is not None]
    return {
        "rub": round(sum(priced), 2) if priced else None,
        "date": datetime.now(MOSCOW_TIME).date().isoformat(),
        "storeId": context["storeId"], "channel": context["channel"],
        "missing": [item["name"] for item in items if item["rub"] is None],
        "items": items,
    }


def read_portion_price(value):
    if not isinstance(value, dict):
        return None
    rub, missing = value.get("rub"), value.get("missing")
    if (rub is not None and (type(rub) not in (int, float) or not 0 <= rub <= 10_000_000)
            or not isinstance(missing, list) or len(missing) > 50
            or any(not isinstance(item, str) or len(item) > 200 for item in missing)
            or not isinstance(value.get("date"), str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value["date"])
            or type(value.get("storeId")) is not int or value.get("channel") not in ("lo", "locc")):
        return None
    result = {**{key: value[key] for key in ("date", "storeId", "channel", "missing")}, "rub": rub}
    if isinstance(value.get("items"), list):
        result["items"] = [
            {key: item[key] for key in ("index", "name", "rub", "reason", "link", "product") if key in item}
            for item in value["items"][:50]
            if isinstance(item, dict) and type(item.get("index")) is int and isinstance(item.get("name"), str)
            and (item.get("rub") is None or type(item["rub"]) in (int, float))
            and (item.get("reason") is None or isinstance(item["reason"], str) and item["reason"] in REASONS)
            and all(isinstance(item.get(key, ""), str) for key in ("link", "product"))
        ]
    return result
