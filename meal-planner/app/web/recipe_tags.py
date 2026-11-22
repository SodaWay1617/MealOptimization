TAGS = {
    "quick": "Быстрое",
    "simple": "Простое",
    "few_ingredients": "Мало ингредиентов",
    "high_protein": "Высокобелковое",
    "budget": "Недорогое",
}


def validate_tags(value: object) -> list[str]:
    if not isinstance(value, list) or any(not isinstance(tag, str) or tag not in TAGS for tag in value):
        raise ValueError("Выберите допустимые теги рецепта.")
    return list(dict.fromkeys(value))
