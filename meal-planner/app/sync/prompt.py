from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.sync.recipe_schema import ALLOWED_CATEGORIES, ALLOWED_UNITS, RECIPE_JSON_SCHEMA


SYSTEM_PROMPT = """You extract structured recipe data from markdown notes.

Rules:
1. Do not invent facts that are not present in the markdown.
2. Return ONLY valid JSON object, no markdown, no prose.
3. If value is unknown, use null.
4. If ingredient amount is unspecified but implies "по вкусу", set:
   - amount: null
   - unit: "по вкусу"
5. Use only allowed category and unit enums.
6. Keep ingredient and step order as in source text.
7. Output must contain "confidence" (0.0 to 1.0) that reflects extraction certainty.
8. Do not include "source_path" in the output.

Output contract:
- Must satisfy the provided recipe schema.
- Include one extra top-level field:
  confidence: number (0.0..1.0)
"""


def build_user_prompt(
    markdown_text: str,
    *,
    source_path: str,
    category_hint: Optional[str] = None,
) -> str:
    file_name = Path(source_path).name
    payload = {
        "task": "Parse markdown recipe into JSON",
        "file_name": file_name,
        "category_hint": category_hint,
        "allowed_categories": list(ALLOWED_CATEGORIES),
        "allowed_units": list(ALLOWED_UNITS),
        "recipe_schema": _llm_recipe_schema(),
        "required_extra_field": {
            "confidence": {
                "type": "number",
                "minimum": 0.0,
                "maximum": 1.0,
            }
        },
        "markdown": markdown_text,
    }
    return json.dumps(payload, ensure_ascii=False)


def _llm_recipe_schema() -> Dict[str, Any]:
    schema = deepcopy(RECIPE_JSON_SCHEMA)
    required = schema.get("required")
    if isinstance(required, list):
        schema["required"] = [field for field in required if field != "source_path"]
    properties = schema.get("properties")
    if isinstance(properties, dict):
        properties.pop("source_path", None)
    return schema


def build_llm_messages(
    markdown_text: str,
    *,
    source_path: str,
    category_hint: Optional[str] = None,
) -> List[Dict[str, Any]]:
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": build_user_prompt(
                markdown_text,
                source_path=source_path,
                category_hint=category_hint,
            ),
        },
    ]
