from __future__ import annotations

from pathlib import Path
from typing import Dict


class IngredientSectionConfigError(ValueError):
    pass


def load_ingredient_sections(config_path: Path) -> Dict[str, str]:
    if not config_path.exists():
        raise FileNotFoundError(f"Missing ingredient sections config: {config_path}")

    text = config_path.read_text(encoding="utf-8")
    try:
        import yaml  # type: ignore
    except ModuleNotFoundError:
        return _parse_simple_yaml(text)

    data = yaml.safe_load(text)
    if not isinstance(data, dict) or "ingredient_sections" not in data:
        raise IngredientSectionConfigError("Expected a top-level 'ingredient_sections' mapping")
    mapping = data["ingredient_sections"]
    if not isinstance(mapping, dict):
        raise IngredientSectionConfigError("'ingredient_sections' must be a mapping")

    normalized: Dict[str, str] = {}
    for key, value in mapping.items():
        if not isinstance(key, str) or not isinstance(value, str):
            raise IngredientSectionConfigError("Ingredient section keys and values must be strings")
        normalized[_normalize_name(key)] = value.strip()
    return normalized


def _parse_simple_yaml(text: str) -> Dict[str, str]:
    mapping: Dict[str, str] = {}
    in_block = False
    for raw_line in text.splitlines():
        if raw_line.startswith("\ufeff"):
            raw_line = raw_line.lstrip("\ufeff")
        line = raw_line.split("#", 1)[0].rstrip()
        if not line:
            continue
        if not line.startswith(" "):
            in_block = line.strip() == "ingredient_sections:"
            continue
        if not in_block:
            continue
        stripped = line.strip()
        if ":" not in stripped:
            continue
        key, value = stripped.split(":", 1)
        key = _unquote(key.strip())
        value = _unquote(value.strip())
        if key and value:
            mapping[_normalize_name(key)] = value
    if not mapping:
        raise IngredientSectionConfigError("No ingredient sections found in config")
    return mapping


def _unquote(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def _normalize_name(value: str) -> str:
    return " ".join(value.strip().casefold().split())
