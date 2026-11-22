from __future__ import annotations

from pathlib import Path
from typing import Dict, Optional


class CategoryConfigError(ValueError):
    pass


def _strip_inline_comment(line: str) -> str:
    if "#" not in line:
        return line
    head, _ = line.split("#", 1)
    return head


def _unquote(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"\"", "'"}:
        return value[1:-1]
    return value


def _parse_simple_yaml(text: str) -> Dict[str, str]:
    categories: Dict[str, str] = {}
    in_categories = False

    for raw_line in text.splitlines():
        if raw_line.startswith("\ufeff"):
            raw_line = raw_line.lstrip("\ufeff")
        line = _strip_inline_comment(raw_line).rstrip()
        if not line:
            continue

        if not line.startswith(" "):
            in_categories = line.strip() == "categories:"
            continue

        if not in_categories:
            continue

        stripped = line.strip()
        if ":" not in stripped:
            continue
        key, value = stripped.split(":", 1)
        key = _unquote(key)
        value = _unquote(value)
        if key and value:
            categories[key] = value

    if not categories:
        raise CategoryConfigError("No categories found in categories.yaml")
    return categories


def load_categories(config_path: Path) -> Dict[str, str]:
    if not config_path.exists():
        raise FileNotFoundError(f"Missing categories config: {config_path}")

    text = config_path.read_text(encoding="utf-8")
    try:
        import yaml  # type: ignore
    except ModuleNotFoundError:
        return _parse_simple_yaml(text)

    data = yaml.safe_load(text)
    if not isinstance(data, dict) or "categories" not in data:
        raise CategoryConfigError("Expected a top-level 'categories' mapping")
    categories = data["categories"]
    if not isinstance(categories, dict) or not categories:
        raise CategoryConfigError("'categories' must be a non-empty mapping")

    normalized: Dict[str, str] = {}
    for key, value in categories.items():
        if not isinstance(key, str) or not isinstance(value, str):
            raise CategoryConfigError("Category keys and values must be strings")
        normalized[key] = value

    return normalized


def category_for_path(path: Path, categories: Dict[str, str]) -> Optional[str]:
    for part in path.parts:
        if part in categories:
            return categories[part]
    return None
