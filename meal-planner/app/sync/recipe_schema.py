from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict, Iterable, Tuple


class RecipeValidationError(ValueError):
    pass


ALLOWED_CATEGORIES: Tuple[str, ...] = (
    "soup",
    "main",
    "salad",
    "breakfast",
    "snack",
    "drink",
)

ALLOWED_UNITS: Tuple[str, ...] = (
    "г",
    "кг",
    "мл",
    "л",
    "ч.л.",
    "ст.л.",
    "стакан",
    "шт",
    "зубчик",
    "щепотка",
    "пучок",
    "по вкусу",
)

RECIPE_JSON_SCHEMA: Dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "title": "Recipe",
    "type": "object",
    "additionalProperties": False,
    "required": [
        "title",
        "category",
        "servings",
        "ingredients",
        "steps",
        "source_path",
    ],
    "properties": {
        "title": {"type": "string", "minLength": 1},
        "category": {"type": "string", "enum": list(ALLOWED_CATEGORIES)},
        "servings": {"type": ["number", "null"], "minimum": 0},
        "ingredients": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["name", "amount", "unit"],
                "properties": {
                    "name": {"type": "string", "minLength": 1},
                    "amount": {"type": ["number", "null"], "minimum": 0},
                    "unit": {"type": ["string", "null"], "enum": list(ALLOWED_UNITS) + [None]},
                    "note": {"type": ["string", "null"]},
                },
            },
        },
        "steps": {
            "type": "array",
            "minItems": 1,
            "items": {"type": "string", "minLength": 1},
        },
        "source_path": {"type": "string", "minLength": 1},
        "notes": {"type": ["string", "null"]},
    },
}


def validate_recipe(payload: Dict[str, Any]) -> Dict[str, Any]:
    try:
        import jsonschema  # type: ignore
    except ModuleNotFoundError:
        _validate_recipe_fallback(payload)
        return deepcopy(payload)

    try:
        jsonschema.validate(payload, RECIPE_JSON_SCHEMA)
    except jsonschema.ValidationError as exc:  # type: ignore[attr-defined]
        path = ".".join(str(x) for x in exc.absolute_path) or "<root>"
        raise RecipeValidationError(f"Invalid recipe at {path}: {exc.message}") from exc
    return deepcopy(payload)


def _validate_recipe_fallback(payload: Dict[str, Any]) -> None:
    if not isinstance(payload, dict):
        raise RecipeValidationError("Recipe must be an object")

    required = {"title", "category", "servings", "ingredients", "steps", "source_path"}
    allowed = required | {"notes"}
    _require_keys(payload, required, allowed)

    _require_non_empty_string(payload["title"], "title")
    _require_enum(payload["category"], ALLOWED_CATEGORIES, "category")
    _require_optional_number(payload["servings"], "servings")
    _require_non_empty_string(payload["source_path"], "source_path")

    notes = payload.get("notes")
    if notes is not None and not isinstance(notes, str):
        raise RecipeValidationError("notes must be a string or null")

    ingredients = payload["ingredients"]
    if not isinstance(ingredients, list) or not ingredients:
        raise RecipeValidationError("ingredients must be a non-empty array")
    for idx, ingredient in enumerate(ingredients):
        _validate_ingredient(ingredient, idx)

    steps = payload["steps"]
    if not isinstance(steps, list) or not steps:
        raise RecipeValidationError("steps must be a non-empty array")
    for idx, step in enumerate(steps):
        _require_non_empty_string(step, f"steps[{idx}]")


def _validate_ingredient(ingredient: Any, idx: int) -> None:
    if not isinstance(ingredient, dict):
        raise RecipeValidationError(f"ingredients[{idx}] must be an object")
    required = {"name", "amount", "unit"}
    allowed = required | {"note"}
    _require_keys(ingredient, required, allowed, prefix=f"ingredients[{idx}]")

    _require_non_empty_string(ingredient["name"], f"ingredients[{idx}].name")
    _require_optional_number(ingredient["amount"], f"ingredients[{idx}].amount")
    _require_optional_enum(ingredient["unit"], ALLOWED_UNITS, f"ingredients[{idx}].unit")

    note = ingredient.get("note")
    if note is not None and not isinstance(note, str):
        raise RecipeValidationError(f"ingredients[{idx}].note must be a string or null")


def _require_keys(
    data: Dict[str, Any],
    required: Iterable[str],
    allowed: Iterable[str],
    *,
    prefix: str = "recipe",
) -> None:
    required_set = set(required)
    allowed_set = set(allowed)
    missing = sorted(required_set - set(data.keys()))
    if missing:
        raise RecipeValidationError(f"{prefix} is missing required fields: {', '.join(missing)}")

    extra = sorted(set(data.keys()) - allowed_set)
    if extra:
        raise RecipeValidationError(f"{prefix} has unknown fields: {', '.join(extra)}")


def _require_non_empty_string(value: Any, field: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise RecipeValidationError(f"{field} must be a non-empty string")


def _require_optional_number(value: Any, field: str) -> None:
    if value is None:
        return
    if not isinstance(value, (int, float)) or isinstance(value, bool) or value < 0:
        raise RecipeValidationError(f"{field} must be a non-negative number or null")


def _require_enum(value: Any, allowed: Tuple[str, ...], field: str) -> None:
    if not isinstance(value, str) or value not in allowed:
        raise RecipeValidationError(f"{field} must be one of: {', '.join(allowed)}")


def _require_optional_enum(value: Any, allowed: Tuple[str, ...], field: str) -> None:
    if value is None:
        return
    _require_enum(value, allowed, field)
