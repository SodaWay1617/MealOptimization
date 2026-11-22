from __future__ import annotations

import math
import re
from pathlib import Path
from threading import Lock
from uuid import uuid4

import yaml

from app.scanner.scan import scan_recipes
from app.web.recipe_images import IMAGE_EMBED, find_image
from app.web.recipe_tags import TAGS, validate_tags
from app.web.portion_price import read_portion_price
from app.web.recipe_index import add_index_link, recipe_indexes


INDEX_WRITE_LOCK = Lock()


def category_directories(root: Path, categories: dict[str, str]) -> dict[str, Path]:
    directories: dict[str, Path] = {}
    for folder, category in categories.items():
        candidate = root / folder
        if candidate.resolve().is_relative_to(root) and (
            category not in directories or (candidate.is_dir() and not directories[category].is_dir())
        ):
            directories[category] = candidate
    return directories


def read_recipe(path: Path, root: Path, category: str | None) -> dict:
    body = path.read_text(encoding="utf-8-sig", errors="replace")
    metadata = {}
    if body.startswith("---\n"):
        front, separator, content = body[4:].partition("\n---\n")
        if separator:
            try:
                parsed = yaml.safe_load(front)
                if isinstance(parsed, dict):
                    metadata, body = parsed, content
            except yaml.YAMLError:
                pass
    heading = re.search(r"^#\s+(.+)$", body, re.MULTILINE)
    title = metadata.get("title")
    ingredients = metadata.get("ingredients")
    servings = metadata.get("servings")
    nutrition = metadata.get("nutrition")
    return {
        "id": path.relative_to(root).as_posix(),
        "title": title if isinstance(title, str) and title.strip() else (
            heading[1].strip() if heading else path.stem
        ),
        "category": category,
        "planningTags": [tag for tag in metadata.get("planning_tags", []) if isinstance(tag, str) and tag in TAGS]
        if isinstance(metadata.get("planning_tags"), list) else [],
        "ingredients": [
            {"name": item["name"], "amount": item.get("amount"), "unit": item["unit"]}
            for item in ingredients
            if isinstance(item, dict) and isinstance(item.get("name"), str)
            and isinstance(item.get("unit"), str)
            and (item.get("amount") is None or _positive_quantity(item["amount"]))
        ] if isinstance(ingredients, list) else [],
        "servings": servings if type(servings) is int and servings > 0 else None,
        "structuredBody": metadata.get("recipe_body") == "one_portion",
        "isSynced": metadata.get("nutrition_estimated") is True,
        "portionPrice": read_portion_price(metadata.get("portion_price")),
        "nutrition": {
            key: value for key, value in nutrition.items()
            if key in ("kcal", "protein_g", "fat_g", "carbs_g")
            and type(value) in (int, float) and 0 <= value <= 10000
        } if isinstance(nutrition, dict) else {},
        "steps": [step for step in metadata["steps"] if isinstance(step, str)]
        if isinstance(metadata.get("steps"), list) else [],
        "body": body.strip(),
    }


def list_recipes(root: Path, categories: dict[str, str], *, previews: bool = True) -> list[dict]:
    recipes = []
    for entry in scan_recipes(root, categories):
        if entry.path.resolve().is_relative_to(root):
            try:
                recipe = read_recipe(entry.path, root, entry.category)
            except FileNotFoundError:
                continue
            body = recipe.pop("body")
            if previews:
                recipe["previewImage"] = next((
                    target for target in (match[1].strip() for match in IMAGE_EMBED.finditer(body))
                    if find_image(root, entry.path, target) is not None
                ), None)
            recipe.pop("steps")
            recipe.pop("structuredBody")
            recipes.append(recipe)
    return sorted(recipes, key=lambda recipe: recipe["title"].casefold())


def _positive_quantity(value: object) -> bool:
    return type(value) in (int, float) and 0 < value <= 1e12 and math.isfinite(value)


def create_recipe(
    root: Path, categories: dict[str, str], payload: object, *, ai_metadata: dict | None = None
) -> dict:
    if not isinstance(payload, dict):
        raise ValueError("Заполните форму рецепта.")
    title = payload.get("title")
    servings = payload.get("servings")
    category = payload.get("category")
    body = payload.get("body")
    ingredients = payload.get("ingredients")
    if not isinstance(title, str) or not title.strip() or len(title) > 150:
        raise ValueError("Введите название длиной до 150 символов.")
    if type(servings) is not int or not 1 <= servings <= 1000:
        raise ValueError("Укажите от 1 до 1000 порций.")
    directories = category_directories(root, categories)
    directory = directories.get(category) if isinstance(category, str) else None
    if directory is None or not isinstance(body, str) or not body.strip():
        raise ValueError("Выберите категорию и опишите приготовление.")
    if not isinstance(ingredients, list) or not ingredients:
        raise ValueError("Добавьте хотя бы один ингредиент.")

    normalized = []
    for item in ingredients:
        if not isinstance(item, dict):
            raise ValueError("Проверьте список ингредиентов.")
        name, amount, unit = item.get("name"), item.get("amount"), item.get("unit")
        if not isinstance(name, str) or not name.strip():
            raise ValueError("Введите название каждого ингредиента.")
        if unit == "по вкусу":
            amount = None
        elif unit not in ("г", "мл", "шт") or not _positive_quantity(amount):
            raise ValueError("Введите положительное количество и выберите единицу.")
        normalized.append({"name": name.strip(), "amount": amount, "unit": unit})

    selected_index = payload.get("index")
    indexes = recipe_indexes(directory)
    index = next((item for item in indexes if item.stem == selected_index), None)
    if index is None:
        if selected_index or len(indexes) != 1:
            raise ValueError("Выберите таблицу для рецепта.")
        index = indexes[0]
    notes = directory / "Заметки"
    destination = notes if notes.is_dir() else directory
    if not all(item.resolve().is_relative_to(root) for item in (destination, index)):
        raise ValueError("Выбранная папка или таблица находится за пределами каталога.")
    destination.mkdir(parents=True, exist_ok=True)
    slug = re.sub(r"[^\w-]+", "-", title.strip().lower()).strip("-_")[:70] or "recipe"
    path = destination / f"{slug}-{uuid4().hex[:12]}.md"
    metadata = dict(title=title.strip(), category=category, servings=servings, ingredients=normalized,
                    planning_tags=validate_tags(payload.get("planningTags", [])))
    if ai_metadata is not None:
        metadata.update(ai_metadata)
    body = body.strip()
    if metadata.get("recipe_body") != "one_portion":
        body = f"## Приготовление\n\n{body}"
    front = yaml.safe_dump(metadata, allow_unicode=True, sort_keys=False)
    note = path.open("x", encoding="utf-8", newline="\n")
    try:
        with note:
            note.write(f"---\n{front}---\n\n{body}\n")
        with INDEX_WRITE_LOCK:
            add_index_link(index, path, title)
    except (OSError, UnicodeError):
        path.unlink(missing_ok=True)
        raise
    return read_recipe(path, root, category)
