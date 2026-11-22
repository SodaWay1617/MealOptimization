from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
import argparse

from app.index.file_index import FileIndex
from app.planner import (
    build_weekly_plan,
    check_category_availability,
    hydrate_weekly_plan,
    load_weekly_plan_state,
    prepare_planning_data,
    rebuild_weekly_plan_slot,
    save_weekly_plan_state,
)
from app.scanner.scan import RecipeFile
from cli import _resolve_plan_quotas
from app.sync.llm import LLMClient, LLMSettings
from app.sync.pipeline import run_sync_pipeline
from app.sync.store import RecipeStore


class FakeLLMClient:
    def __init__(self, payload):
        self.payload = payload

    def parse_recipe(self, markdown_text: str, *, source_path: str, category_hint: str | None):
        return self.payload


class SyncAndPlannerTests(unittest.TestCase):
    @staticmethod
    def _store_recipe(recipe_store: RecipeStore, root: Path, stem: str, category: str):
        source = root / f"{stem}.md"
        source.write_text(f"# {stem}\n", encoding="utf-8")
        payload = {
            "title": stem,
            "category": category,
            "servings": 1,
            "ingredients": [{"name": "яйцо", "amount": 1, "unit": "шт", "note": None}],
            "steps": ["step"],
            "source_path": str(source),
            "notes": None,
        }
        recipe_store.upsert_recipe(
            source_path=str(source),
            content_hash=f"hash-{stem}",
            category=category,
            recipe_payload=payload,
            confidence=1.0,
        )
        stored = recipe_store.get_recipes_by_source_paths([source])
        return stored[0]

    def test_resolve_plan_quotas_overrides_selected_categories(self) -> None:
        quotas = _resolve_plan_quotas(
            argparse.Namespace(
                soup=0,
                main=2,
                salad=None,
                breakfast=1,
                snack=None,
                drink=0,
            )
        )
        self.assertEqual(quotas["soup"], 0)
        self.assertEqual(quotas["main"], 2)
        self.assertEqual(quotas["breakfast"], 1)
        self.assertEqual(quotas["drink"], 0)
        self.assertEqual(quotas["salad"], 1)
        self.assertEqual(quotas["snack"], 1)

    def test_sync_pipeline_marks_recipe_as_synced_with_mock_llm(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            source = tmp_path / "Breakfast.md"
            source.write_text("# Omelette\n\n- eggs\n", encoding="utf-8")

            file_index = FileIndex(tmp_path / "file_index.sqlite")
            recipe_store = RecipeStore(tmp_path / "recipes.sqlite")
            file_index.reconcile_scan(
                [
                    RecipeFile(
                        path=source,
                        category="breakfast",
                        mtime=source.stat().st_mtime,
                        size=source.stat().st_size,
                        content_hash="hash-1",
                    )
                ]
            )

            summary = run_sync_pipeline(
                file_index=file_index,
                recipe_store=recipe_store,
                llm_client=LLMClient(
                    LLMSettings(
                        provider="mock",
                        model="mock-model",
                        api_key=None,
                        api_base="https://example.test/v1",
                        api_path="/chat/completions",
                        temperature=0.0,
                        timeout_seconds=10,
                        json_mode=True,
                        log_path=tmp_path / "llm.log",
                    )
                ),
            )

            self.assertEqual(summary.selected, 1)
            self.assertEqual(summary.synced, 1)
            synced_entries = file_index.get_by_status("synced")
            self.assertEqual(len(synced_entries), 1)

    def test_prepare_planning_data_and_build_weekly_plan(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            file_index = FileIndex(tmp_path / "file_index.sqlite")
            recipe_store = RecipeStore(tmp_path / "recipes.sqlite")

            quotas = {
                "soup": 1,
                "main": 2,
                "salad": 1,
                "breakfast": 2,
                "snack": 1,
                "drink": 1,
            }
            counts = {
                "soup": 1,
                "main": 2,
                "salad": 1,
                "breakfast": 2,
                "snack": 1,
                "drink": 1,
            }
            counter = 0
            for category, total in counts.items():
                for idx in range(total):
                    counter += 1
                    source = tmp_path / f"{category}_{idx}.md"
                    source.write_text(f"# {category} {idx}\n", encoding="utf-8")
                    payload = {
                        "title": f"{category} {idx}",
                        "category": category,
                        "servings": 1,
                        "ingredients": [{"name": "яйцо", "amount": 1, "unit": "шт", "note": None}],
                        "steps": ["step"],
                        "source_path": str(source),
                        "notes": None,
                    }
                    recipe_store.upsert_recipe(
                        source_path=str(source),
                        content_hash=f"hash-{counter}",
                        category=category,
                        recipe_payload=payload,
                        confidence=1.0,
                    )
                    file_index.upsert_synced_record(
                        RecipeFile(
                            path=source,
                            category=category,
                            mtime=source.stat().st_mtime,
                            size=source.stat().st_size,
                            content_hash=f"hash-{counter}",
                        ),
                        last_synced_hash=f"hash-{counter}",
                    )

            prepared = prepare_planning_data(file_index=file_index, recipe_store=recipe_store)
            availability = check_category_availability(prepared.recipes, quotas=quotas)
            self.assertTrue(availability.is_sufficient)

            weekly_plan = build_weekly_plan(prepared.recipes, quotas=quotas)
            self.assertEqual(len(weekly_plan.by_category["breakfast"]), 2)
            self.assertEqual(len(weekly_plan.recipes), sum(quotas.values()))

    def test_save_load_and_rebuild_plan_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            recipe_store = RecipeStore(tmp_path / "recipes.sqlite")

            breakfast = self._store_recipe(recipe_store, tmp_path, "breakfast_1", "breakfast")
            soup_one = self._store_recipe(recipe_store, tmp_path, "soup_1", "soup")
            soup_two = self._store_recipe(recipe_store, tmp_path, "soup_2", "soup")
            salad = self._store_recipe(recipe_store, tmp_path, "salad_1", "salad")
            main_one = self._store_recipe(recipe_store, tmp_path, "main_1", "main")
            main_two = self._store_recipe(recipe_store, tmp_path, "main_2", "main")
            snack = self._store_recipe(recipe_store, tmp_path, "snack_1", "snack")
            drink = self._store_recipe(recipe_store, tmp_path, "drink_1", "drink")

            plan = build_weekly_plan(
                [breakfast, soup_one, soup_two, salad, main_one, main_two, snack, drink],
                quotas={"breakfast": 1, "soup": 1, "salad": 1, "main": 2, "snack": 1, "drink": 1},
            )
            state_path = tmp_path / "week.plan.json"
            save_weekly_plan_state(plan, title="Week", destination=state_path)

            saved = load_weekly_plan_state(state_path)
            hydrated = hydrate_weekly_plan(saved, recipe_store=recipe_store)
            rebuilt = rebuild_weekly_plan_slot(
                hydrated,
                all_recipes=[breakfast, soup_one, soup_two, salad, main_one, main_two, snack, drink],
                category="soup",
                slot_index=0,
            )

            original_soup = hydrated.by_category["soup"][0].source_path
            rebuilt_soup = rebuilt.by_category["soup"][0].source_path
            self.assertIn(original_soup, {soup_one.source_path, soup_two.source_path})
            self.assertIn(rebuilt_soup, {soup_one.source_path, soup_two.source_path})
            self.assertNotEqual(original_soup, rebuilt_soup)

    def test_sync_pipeline_normalizes_common_llm_units(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            source = tmp_path / "Breakfast.md"
            source.write_text("# Breakfast\n", encoding="utf-8")

            file_index = FileIndex(tmp_path / "file_index.sqlite")
            recipe_store = RecipeStore(tmp_path / "recipes.sqlite")
            file_index.reconcile_scan(
                [
                    RecipeFile(
                        path=source,
                        category="breakfast",
                        mtime=source.stat().st_mtime,
                        size=source.stat().st_size,
                        content_hash="hash-2",
                    )
                ]
            )

            summary = run_sync_pipeline(
                file_index=file_index,
                recipe_store=recipe_store,
                llm_client=FakeLLMClient(
                    {
                        "title": "Breakfast",
                        "category": "breakfast",
                        "servings": 1,
                        "ingredients": [
                            {"name": "Хлеб", "amount": 2, "unit": "ломтика", "note": None},
                            {"name": "Протеин", "amount": 1, "unit": "мерная ложка", "note": None},
                            {"name": "Корица", "amount": 1, "unit": "щепотка", "note": None},
                            {"name": "Гвоздика", "amount": 2, "unit": "бутон", "note": None},
                            {"name": "Зелень", "amount": 1, "unit": "горсть", "note": None},
                            {"name": "Имбирь", "amount": 3, "unit": "см", "note": None},
                            {"name": "Сыр", "amount": None, "unit": "по желанию", "note": None},
                        ],
                        "steps": ["step"],
                        "confidence": 0.9,
                    }
                ),
            )

            self.assertEqual(summary.synced, 1)
            stored = recipe_store.get_recipes_by_source_paths([source])
            self.assertEqual(len(stored), 1)
            units = [item["unit"] for item in stored[0].recipe_payload["ingredients"]]
            self.assertEqual(units, ["шт", "шт", "щепотка", "шт", "по вкусу", "по вкусу", "по вкусу"])


    def test_sync_pipeline_collapses_duplicate_range_ingredients(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            source = tmp_path / "Salad.md"
            source.write_text("# Salad\n", encoding="utf-8")

            file_index = FileIndex(tmp_path / "file_index.sqlite")
            recipe_store = RecipeStore(tmp_path / "recipes.sqlite")
            file_index.reconcile_scan(
                [
                    RecipeFile(
                        path=source,
                        category="salad",
                        mtime=source.stat().st_mtime,
                        size=source.stat().st_size,
                        content_hash="hash-3",
                    )
                ]
            )

            summary = run_sync_pipeline(
                file_index=file_index,
                recipe_store=recipe_store,
                llm_client=FakeLLMClient(
                    {
                        "title": "Salad",
                        "category": "salad",
                        "servings": 2,
                        "ingredients": [
                            {"name": "Креветки", "amount": 200, "unit": "г", "note": None},
                            {"name": "Креветки", "amount": 250, "unit": "г", "note": None},
                            {"name": "Руккола", "amount": 60, "unit": "г", "note": None},
                            {"name": "Руккола", "amount": 80, "unit": "г", "note": None},
                            {"name": "Чеснок", "amount": 1, "unit": "зубчик", "note": None},
                        ],
                        "steps": ["step"],
                        "confidence": 0.95,
                    }
                ),
            )

            self.assertEqual(summary.synced, 1)
            stored = recipe_store.get_recipes_by_source_paths([source])
            self.assertEqual(len(stored), 1)
            ingredients = stored[0].recipe_payload["ingredients"]
            self.assertEqual(len(ingredients), 3)
            self.assertEqual(ingredients[0]["name"], "Креветки")
            self.assertEqual(ingredients[0]["amount"], 225.0)
            self.assertEqual(ingredients[1]["name"], "Руккола")
            self.assertEqual(ingredients[1]["amount"], 70.0)

    def test_sync_pipeline_force_reparses_synced_and_ignores_cache(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            source = tmp_path / "Breakfast.md"
            source.write_text("# Breakfast\n", encoding="utf-8")

            file_index = FileIndex(tmp_path / "file_index.sqlite")
            recipe_store = RecipeStore(tmp_path / "recipes.sqlite")
            file_index.upsert_synced_record(
                RecipeFile(
                    path=source,
                    category="breakfast",
                    mtime=source.stat().st_mtime,
                    size=source.stat().st_size,
                    content_hash="hash-force",
                ),
                last_synced_hash="hash-force",
            )
            recipe_store.put_cached(
                "hash-force",
                {
                    "title": "Old Cached",
                    "category": "breakfast",
                    "servings": 1,
                    "ingredients": [{"name": "яйцо", "amount": 1, "unit": "шт", "note": None}],
                    "steps": ["old"],
                    "source_path": str(source),
                    "notes": None,
                },
                confidence=0.1,
            )

            summary = run_sync_pipeline(
                file_index=file_index,
                recipe_store=recipe_store,
                llm_client=FakeLLMClient(
                    {
                        "title": "Fresh Parse",
                        "category": "breakfast",
                        "servings": 1,
                        "ingredients": [{"name": "творог", "amount": 200, "unit": "г", "note": None}],
                        "steps": ["fresh"],
                        "confidence": 0.9,
                    }
                ),
                force=True,
            )

            self.assertEqual(summary.selected, 1)
            self.assertEqual(summary.synced, 1)
            self.assertEqual(summary.cached, 0)
            stored = recipe_store.get_recipes_by_source_paths([source])
            self.assertEqual(stored[0].recipe_payload["title"], "Fresh Parse")


if __name__ == "__main__":
    unittest.main()
