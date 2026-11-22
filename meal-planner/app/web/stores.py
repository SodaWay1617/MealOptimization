from __future__ import annotations

import json
import re
from decimal import Decimal
from html import unescape
from urllib.error import URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen


class StoreError(RuntimeError):
    pass


def _store_url(value: object, hosts: set[str]) -> str | None:
    if not isinstance(value, str) or len(value) > 4096:
        return None
    try:
        parsed = urlsplit(value)
    except ValueError:
        return None
    if parsed.scheme == "https" and parsed.hostname in hosts:
        return value
    return None


class StoreMcp:
    name: str
    endpoint: str
    hosts: set[str]
    maximum = 40

    def _call(self, tool: str, arguments: dict) -> dict:
        body = {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                "params": {"name": tool, "arguments": arguments}}
        request = Request(self.endpoint, json.dumps(body).encode(), {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        })
        try:
            with urlopen(request, timeout=15) as response:
                raw = response.read(2_000_001).decode()
                if len(raw) > 2_000_000:
                    raise StoreError(f"{self.name} прислал слишком большой ответ.")
                if response.headers.get_content_type() == "text/event-stream":
                    events = [line[5:].strip() for line in raw.splitlines() if line.startswith("data:")]
                    raw = events[-1] if events else ""
                envelope = json.loads(raw)
                result = envelope["result"]
                if result.get("isError"):
                    raise StoreError(f"{self.name} отклонил запрос. Попробуйте позже.")
                payload = result.get("structuredContent")
                if payload is None:
                    payload = json.loads(result["content"][0]["text"])
                data = payload.get("data", payload)
                if payload.get("ok") is False or not isinstance(data, dict):
                    raise StoreError(f"{self.name} отклонил запрос. Попробуйте позже.")
                return data
        except (URLError, TimeoutError) as error:
            raise StoreError(f"Магазин «{self.name}» недоступен. Попробуйте позже.") from error
        except (ValueError, TypeError, KeyError, IndexError, AttributeError) as error:
            raise StoreError(f"Магазин «{self.name}» прислал неожиданный ответ.") from error

    def _items(self, data: dict) -> list[dict]:
        items = data.get("items")
        if not isinstance(items, list):
            raise StoreError(f"{self.name} прислал неожиданный список товаров.")
        return [item for item in items if isinstance(item, dict) and type(item.get("id")) is int
                and item["id"] > 0 and isinstance(item.get("name"), str)]

    def _link(self, result: dict) -> str:
        link = _store_url(result.get("link") or result.get("url"), self.hosts)
        if not link:
            raise StoreError(f"{self.name} не вернул ссылку на корзину.")
        return link


class VkusVill(StoreMcp):
    name = "ВкусВилл"
    endpoint = "https://mcp.vkusvill.ru/mcp"
    hosts = {"vkusvill.ru", "www.vkusvill.ru", "vkusvill.onelink.me", "vkusvillapp.onelink.me"}

    def search(self, query: str, options: dict) -> list[dict]:
        data = self._call("vkusvill_products_search", {
            "q": query, "page": 1, "limit": 6, "mode": "custom",
            "fields": ["id", "name", "unit", "weight", "url", "price", "available_quantity"],
        })
        return [
            {"id": item["id"], "name": unescape(item["name"]), "unit": item.get("unit"),
             "weight": item.get("weight"), "url": _store_url(item.get("url"), self.hosts),
             "stock": item.get("available_quantity"),
             "price": (item["price"].get("current") if isinstance(item.get("price"), dict) else item.get("price"))}
            for item in self._items(data)
        ]

    def cart_link(self, products: list[dict]) -> str:
        return self._link(self._call("vkusvill_cart_link_create", {"products": products}))

    def product_details(self, product_id: int, options: dict) -> dict:
        data = self._call("vkusvill_product_details", {"id": product_id})
        item = data.get("item", data.get("product", data))
        if not isinstance(item, dict) or not isinstance(item.get("name"), str):
            raise StoreError("ВкусВилл не вернул карточку товара.")
        price = item.get("price")
        return {"id": product_id, "name": unescape(item["name"]), "unit": item.get("unit"),
                "weight": item.get("weight"), "stock": item.get("available_quantity"),
                "price": price.get("current") if isinstance(price, dict) else price,
                "url": _store_url(item.get("url"), self.hosts)}


class Lenta(StoreMcp):
    name = "Лента"
    endpoint = "https://mcp.lenta.com/mcp"
    hosts = {"lenta.com", "www.lenta.com"}
    maximum = None

    def hubs(self, address: str) -> list[dict]:
        data = self._call("storefront_resolve_store", {"address": address})
        return [
            {"id": item["aliasId"], "address": item["address"], "name": item.get("name"),
             "format": item["format"]}
            for item in data.get("hubs", [])
            if isinstance(item, dict) and type(item.get("aliasId")) is int
            and isinstance(item.get("address"), str) and item.get("format") in ("hyper", "super", "econom", "mm")
        ]

    @staticmethod
    def context(options: dict) -> dict:
        store_id, channel = options.get("storeId"), options.get("channel")
        if type(store_id) is not int or store_id <= 0 or channel not in ("lo", "locc"):
            raise ValueError("Выберите магазин Ленты и способ получения.")
        return {"storeId": store_id, "channel": channel}

    def search(self, query: str, options: dict) -> list[dict]:
        context = self.context(options)
        data = self._call("storefront_products_search", dict(context, query=query))
        products = [
            {"id": item["id"], "name": unescape(item["name"]), "unit": "шт" if item.get("package") else None,
             "package": item.get("package"), "url": _store_url(item.get("url"), self.hosts),
             "stock": item.get("stock"),
             "price": item.get("priceRegular") if item.get("priceType") == "card" else item.get("price")}
            for item in self._items(data)[:6]
        ]
        if products and products[0]["unit"] is None:
            try:
                products[0].update(self.product_details(products[0]["id"], context))
            except StoreError:
                pass
        return products

    def product_details(self, product_id: int, options: dict) -> dict:
        data = self._call("storefront_product_details", dict(self.context(options), id=product_id))
        item = data.get("item")
        if not isinstance(item, dict):
            raise StoreError("Лента не вернула карточку товара.")
        product = {
            "name": unescape(item.get("name") or ""),
            "url": _store_url(item.get("url"), self.hosts),
            "stock": item.get("stock"),
            "price": item.get("priceRegular") if item.get("priceType") == "card" else item.get("price"),
        }
        if item.get("isWeight") is not True:
            return {**product, "unit": "шт", "package": item.get("package")}
        limit = item.get("saleLimit")
        if not isinstance(limit, dict) or any(type(limit.get(key)) is not int for key in ("min", "max", "step")):
            raise StoreError("Лента не указала шаг заказа для весового товара.")
        weight = item.get("weightGrams")
        if type(weight) not in (int, float) or weight <= 0 or limit["step"] <= 0:
            raise StoreError("Лента не указала фасовку весового товара.")
        return {**product, "unit": "quanta", "weightGrams": weight,
                "limit": {key: limit[key] for key in ("min", "max", "step")}}

    def cart_link(self, products: list[dict]) -> str:
        return self._link(self._call("storefront_cart_link_create", {
            "items": [{"id": item["id"], "quantity": int(item["q"])} for item in products],
        }))


STORES = {"vkusvill": VkusVill(), "lenta": Lenta()}


def preferred_products(store, urls, options):
    if not isinstance(urls, list) or len(urls) > 3:
        raise ValueError("Укажите до трёх приоритетных ссылок.")
    products = []
    for url in urls:
        if not _store_url(url, store.hosts):
            continue
        match = re.fullmatch(r"/(?:product|goods)/(?:[^/]+-)?([0-9]{1,12})/?", urlsplit(url).path)
        if not match:
            continue
        product_id = int(match[1])
        try:
            product = store.product_details(product_id, options)
        except StoreError:
            continue
        if product.get("stock") == 0:
            continue
        products.append({**product, "id": product_id, "preferred": True})
    return products


def cart_products(value: object, *, maximum: int | None = 40) -> list[dict]:
    if not isinstance(value, list) or not 1 <= len(value) <= 100:
        raise ValueError("Выберите от 1 до 100 позиций.")
    quantities = {}
    for item in value:
        if not isinstance(item, dict):
            raise ValueError("Проверьте выбранные товары.")
        product_id, amount = item.get("id"), item.get("q")
        if type(product_id) is not int or product_id <= 0 or type(amount) not in (int, float):
            raise ValueError("Проверьте выбранные товары и количество.")
        if maximum is None:
            if not 1 <= amount <= 1_000_000 or amount != int(amount):
                raise ValueError("Лента принимает только целые количества.")
        elif not 0.01 <= amount <= maximum:
            raise ValueError(f"Количество каждого товара должно быть от 0,01 до {maximum}.")
        quantities[product_id] = quantities.get(product_id, Decimal(0)) + Decimal(str(amount))
    if maximum is not None and any(amount > maximum for amount in quantities.values()):
        raise ValueError(f"Суммарное количество одного товара превышает {maximum}.")
    return [{"id": product_id, "q": float(amount)} for product_id, amount in quantities.items()]
