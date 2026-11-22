from __future__ import annotations

import os
from pathlib import Path

from flask import Flask, abort, jsonify, request, send_file, send_from_directory

from app.config.categories import load_categories
from app.scanner.scan import scan_recipes
from app.sync.llm import LLMClient, LLMParseError, LLMSettings
from app.web.catalog import category_directories, create_recipe, list_recipes, read_recipe
from app.web.meal_plan import ai_entries, assemble, integer, period, random_entries, save_plan, saved_plans
from app.web.portion_price import estimate_portion, read_portion_price
from app.web.recipe_assistant import (
    RecipeChangedError, ask_assistant, render_recipe_body, save_draft, save_tags, validate_draft, validate_new_draft,
)
from app.web.recipe_images import IMAGE_TYPES, find_image
from app.web.recipe_nutrition import nutrition_properties
from app.web.recipe_tags import TAGS
from app.web.stores import STORES, StoreError, cart_products, preferred_products
from app.web.store_assistant import plan_search, rank_products
from app.web.recipe_index import recipe_indexes


def create_app() -> Flask:
    app = Flask(__name__, static_folder=None)
    app.config["MAX_CONTENT_LENGTH"] = 256 * 1024
    app.config["TRUSTED_HOSTS"] = ["localhost", "127.0.0.1", "[::1]"]
    project = Path(__file__).resolve().parents[2]
    root = Path(os.environ.get("RECIPES_DIR", project.parent / "Питание" / "Рецепты")).resolve()
    assets = Path(os.environ.get("WEB_DIST", project.parent / "web" / "dist")).resolve()
    plans_dir = Path(os.environ.get("PLANS_DIR", root.parent / "Планы питания")).resolve()
    categories = load_categories(project / "config" / "categories.yaml")

    def find_recipe(recipe_id: str):
        if root.is_dir():
            for entry in scan_recipes(root, categories):
                if (entry.path.relative_to(root).as_posix() == recipe_id
                        and entry.path.resolve().is_relative_to(root)):
                    return entry
        return None

    @app.get("/api/recipes")
    def catalog():
        directories = category_directories(root, categories)
        return jsonify(
            recipes=list_recipes(root, categories) if root.is_dir() else [],
            planningTags=TAGS,
            categories={category: folder.name for category, folder in directories.items()},
            indexes={category: [item.stem for item in recipe_indexes(folder)]
                     for category, folder in directories.items()},
        )

    @app.get("/api/recipe")
    def recipe():
        entry = find_recipe(request.args.get("id", ""))
        if entry:
            try:
                return jsonify(read_recipe(entry.path, root, entry.category))
            except FileNotFoundError:
                pass
        return jsonify(error="Рецепт не найден."), 404

    @app.get("/api/recipe/image")
    def recipe_image():
        entry = find_recipe(request.args.get("id", ""))
        if entry is None:
            abort(404)
        image = find_image(root, entry.path, request.args.get("ref", ""))
        if image is None or image.suffix.lower() not in IMAGE_TYPES:
            abort(404)
        response = send_file(image, mimetype=IMAGE_TYPES[image.suffix.lower()])
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    @app.post("/api/recipe/tags")
    def recipe_tags():
        entry = find_recipe(request.args.get("id", ""))
        if entry is None:
            return jsonify(error="Рецепт не найден."), 404
        try:
            save_tags(entry.path, request.get_json(silent=True))
            return jsonify(read_recipe(entry.path, root, entry.category))
        except ValueError as error:
            return jsonify(error=str(error)), 400
        except (OSError, RecipeChangedError):
            return jsonify(error="Не удалось сохранить теги. Обновите карточку и повторите."), 409

    @app.get("/api/plans")
    def plan_archive():
        return jsonify(plans=saved_plans(plans_dir))

    @app.get("/api/plan")
    def saved_plan():
        plan_id = request.args.get("id", "")
        candidate = plans_dir / plan_id
        if (not plan_id or "\x00" in plan_id or candidate.suffix != ".md"
                or candidate.stem in (plans_dir.name, "Планы питания", "Планирование")
                or not candidate.resolve().is_relative_to(plans_dir) or not candidate.is_file()):
            return jsonify(error="План не найден."), 404
        try:
            return jsonify(title=candidate.stem, body=candidate.read_text(encoding="utf-8-sig"))
        except FileNotFoundError:
            return jsonify(error="План не найден."), 404
        except (OSError, UnicodeError):
            return jsonify(error="Не удалось прочитать план."), 500

    @app.post("/api/plans")
    def plans():
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return jsonify(error="Проверьте параметры плана."), 400
        try:
            start, end, days = period(payload)
            labels = {key: path.name for key, path in category_directories(root, categories).items()}
            catalog = list_recipes(root, categories, previews=False) if root.is_dir() else []
            recipes = {item["id"]: item for item in catalog if item["isSynced"]}
            mode = payload.get("mode")
            notices = []
            if mode in ("random", "ai"):
                people = integer(payload.get("people"), 1, 50)
                if not recipes:
                    raise ValueError("Сначала синхронизируйте хотя бы один рецепт с AI.")
                if mode == "ai":
                    start, end, entries, notices, pantry = ai_entries(
                        LLMClient(LLMSettings.from_env()), recipes, payload, start, end, people
                    )
                    payload["pantry"] = list(dict.fromkeys([*payload.get("pantry", []), *pantry]))
                else:
                    entries, notices = random_entries(recipes, payload.get("slots"), days, people, labels)
                payload = dict(payload, start=start, end=end, entries=entries)
            elif mode not in ("preview", "save"):
                raise ValueError("Выберите способ сборки плана.")
            result = assemble(recipes, payload)
            if mode == "save":
                result["filename"] = save_plan(result, plans_dir)
            return jsonify(dict(result, notices=notices))
        except ValueError as error:
            return jsonify(error=str(error)), 400
        except (LLMParseError, TimeoutError):
            return jsonify(error="AI не смог собрать меню. Повторите запрос."), 502
        except OSError:
            return jsonify(error="Не удалось прочитать рецепты или сохранить план."), 500

    @app.post("/api/stores/<store_id>/<action>")
    def store_action(store_id: str, action: str):
        store = STORES.get(store_id)
        if store is None or (action not in ("search", "cart", "ai-queries", "ai-rank") and not (
            store_id == "lenta" and action in ("hubs", "details")
        )):
            return jsonify(error="Подключение магазина пока недоступно."), 404
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return jsonify(error="Проверьте данные корзины."), 400
        try:
            if action in ("ai-queries", "ai-rank"):
                client = LLMClient(LLMSettings.from_env())
                return jsonify(plan_search(client, payload, store) if action == "ai-queries" else rank_products(client, payload))
            if action == "cart":
                return jsonify(link=store.cart_link(cart_products(payload.get("products"), maximum=store.maximum)))
            if action == "hubs":
                address = payload.get("address")
                if not isinstance(address, str) or not 3 <= len(address.strip()) <= 180:
                    raise ValueError("Введите адрес для поиска магазинов Ленты.")
                return jsonify(hubs=store.hubs(address.strip()))
            if action == "details":
                product_id = payload.get("id")
                if type(product_id) is not int or product_id <= 0:
                    raise ValueError("Выберите товар Ленты.")
                return jsonify(product=store.product_details(product_id, payload))
            query = payload.get("query")
            if not isinstance(query, str) or not 1 <= len(query.strip()) <= 180:
                raise ValueError("Введите название товара.")
            preferred = preferred_products(store, payload.get("preferred", []), payload)
            try:
                products = store.search(query.strip(), payload)
            except StoreError:
                if not preferred:
                    raise
                products = []
            combined = {item["id"]: item for item in reversed([*preferred, *products]) if item.get("stock") != 0}
            order = list(dict.fromkeys(item["id"] for item in [*preferred, *products] if item["id"] in combined))
            return jsonify(products=[combined[product_id] for product_id in order])
        except ValueError as error:
            return jsonify(error=str(error)), 400
        except StoreError as error:
            return jsonify(error=str(error)), 502
        except (LLMParseError, TimeoutError):
            return jsonify(error="AI не смог подобрать товары. Повторите запрос."), 502

    @app.post("/api/recipe/assistant")
    @app.post("/api/recipe/assistant/save")
    @app.post("/api/recipes/assistant")
    @app.post("/api/recipes/assistant/save")
    def recipe_assistant():
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return jsonify(error="Некорректный запрос."), 400
        is_new = request.path.startswith("/api/recipes/")
        entry = None if is_new else find_recipe(request.args.get("id", ""))
        if not is_new and entry is None:
            return jsonify(error="Рецепт не найден."), 404
        labels = {category: path.name for category, path in category_directories(root, categories).items()}
        try:
            if request.path.endswith("/save"):
                if is_new:
                    draft = validate_new_draft(payload.get("draft"), labels)
                    draft["portion_price"] = read_portion_price(payload["draft"].get("portion_price"))
                    body = render_recipe_body(draft)
                    steps = draft.pop("steps")
                    metadata = {
                        "steps": steps,
                        "nutrition": draft.pop("nutrition"),
                        "assumptions": draft.pop("assumptions"),
                        "nutrition_estimated": True,
                        "recipe_body": "one_portion",
                        "portion_price": draft.pop("portion_price"),
                    }
                    price = metadata["portion_price"]
                    metadata["portion_price_rub"] = price["rub"] if price else None
                    metadata.update(nutrition_properties(metadata["nutrition"]))
                    return jsonify(create_recipe(root, categories, dict(
                        draft, servings=1, body=body, index=payload.get("index")
                    ), ai_metadata=metadata)), 201
                save_draft(entry.path, payload.get("revision"), payload.get("draft"))
                return jsonify(read_recipe(entry.path, root, entry.category))
            result = ask_assistant(
                entry.path.read_bytes() if entry else None, payload.get("history"), payload.get("revision"),
                LLMClient(LLMSettings.from_env()),
                categories=labels if is_new else None,
            )
            if entry is not None and result["draft"] is not None:
                current = read_recipe(entry.path, root, entry.category)
                if "budget" in current["planningTags"] and "budget" not in result["draft"]["planningTags"]:
                    result["draft"]["planningTags"].append("budget")
            context = payload.get("priceContext")
            if result["draft"] is not None and isinstance(context, dict):
                store = STORES["lenta"]
                result["draft"]["portion_price"] = estimate_portion(
                    store, result["draft"]["ingredients"], store.context(context)
                )
            return jsonify(result)
        except RecipeChangedError:
            return jsonify(error="Заметка изменилась. Закройте чат и начните синхронизацию заново."), 409
        except UnicodeError:
            return jsonify(error="Заметка должна быть сохранена в UTF-8."), 400
        except ValueError as error:
            return jsonify(error=str(error)), 400
        except (LLMParseError, TimeoutError):
            return jsonify(error="AI не вернул подходящий ответ. Проверьте настройки или повторите запрос."), 502
        except OSError:
            return jsonify(error="Не удалось прочитать или сохранить заметку."), 500

    @app.post("/api/recipes/portion-price")
    def portion_price():
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return jsonify(error="Проверьте данные рецепта."), 400
        try:
            draft = validate_draft(payload.get("draft"))
            store = STORES["lenta"]
            return jsonify(estimate_portion(store, draft["ingredients"], store.context(payload), payload.get("links")))
        except ValueError as error:
            return jsonify(error=str(error)), 400

    @app.post("/api/recipes")
    def add_recipe():
        try:
            return jsonify(create_recipe(root, categories, request.get_json(silent=True))), 201
        except ValueError as error:
            return jsonify(error=str(error)), 400
        except (OSError, UnicodeError):
            app.logger.exception("Could not save recipe")
            return jsonify(error="Не удалось сохранить рецепт и обновить таблицу Obsidian."), 500

    @app.get("/")
    def index():
        return send_from_directory(assets, "index.html")

    @app.get("/assets/<path:filename>")
    def asset(filename: str):
        return send_from_directory(assets / "assets", filename)

    return app
