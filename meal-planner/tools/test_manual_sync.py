from __future__ import annotations

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.index.file_index import FileIndex
from app.manual_sync import ManualRecipeDraft, save_manual_recipe
from app.sync.store import RecipeStore


def main() -> int:
    temp_root = Path(__file__).resolve().parents[1] / "data"
    temp_root.mkdir(parents=True, exist_ok=True)
    source_path = temp_root / "manual_sync_test_recipe.md"
    source_path.write_text("# Test Recipe\n\n- ingredient\n", encoding="utf-8")

    index_path = temp_root / "manual_sync_test_index.sqlite"
    recipes_path = temp_root / "manual_sync_test_recipes.sqlite"

    draft = ManualRecipeDraft(
        source_path=str(source_path),
        category="breakfast",
        title="Manual Test Recipe",
        servings=2,
        ingredients=[
            {"name": "яйцо", "amount": 2, "unit": "шт", "note": None},
            {"name": "соль", "amount": None, "unit": "по вкусу", "note": None},
        ],
        steps=["Смешать ингредиенты", "Приготовить"],
        notes="manual save test",
        confidence=1.0,
    )

    save_manual_recipe(
        draft=draft,
        file_index=FileIndex(index_path),
        recipe_store=RecipeStore(recipes_path),
    )

    entry = FileIndex(index_path).get_by_path(source_path)
    stored = RecipeStore(recipes_path).get_recipes_by_source_paths([source_path])

    print(f"file_index_status: {entry.status if entry else 'missing'}")
    print(f"recipes_count: {len(stored)}")
    print(f"recipe_title: {stored[0].recipe_payload['title'] if stored else 'missing'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
