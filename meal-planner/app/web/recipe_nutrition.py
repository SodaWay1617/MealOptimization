NUTRITION_PROPERTIES = {
    "kcal": "kcal_per_portion",
    "protein_g": "protein_g_per_portion",
    "fat_g": "fat_g_per_portion",
    "carbs_g": "carbs_g_per_portion",
}


def nutrition_properties(nutrition: dict) -> dict:
    return {property_name: nutrition[key] for key, property_name in NUTRITION_PROPERTIES.items()}


def read_nutrition(metadata: dict) -> dict:
    nested = metadata.get("nutrition")
    nested = nested if isinstance(nested, dict) else {}
    values = {}
    for key, property_name in NUTRITION_PROPERTIES.items():
        for value in (metadata.get(property_name), nested.get(key)):
            if type(value) in (int, float) and 0 <= value <= 10000:
                values[key] = value
                break
    return values
