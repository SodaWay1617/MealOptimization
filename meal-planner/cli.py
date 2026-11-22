from __future__ import annotations

import argparse
from datetime import date
import json
import logging
import os
import random
from pathlib import Path
import subprocess
import sys
from typing import Callable, Optional

from app.config.categories import load_categories
from app.config.ingredient_sections import load_ingredient_sections
from app.index.file_index import FileIndex, default_db_path
from app.output import (
    WeeklyNoteContext,
    default_week_filename,
    default_week_title,
    render_weekly_note,
    save_weekly_note,
)
from app.planner import (
    DEFAULT_WEEKLY_QUOTAS,
    build_weekly_plan,
    check_category_availability,
    default_plan_state_path,
    format_availability_report,
    format_weekly_plan,
    hydrate_weekly_plan,
    load_weekly_plan_state,
    prepare_planning_data,
    rebuild_weekly_plan_slot,
    save_weekly_plan_state,
)
from app.pricing import (
    estimate_shopping_list_cost,
    export_price_book_seed_from_recipes,
    format_cost_estimate,
    PriceBookConfigError,
    PriceBookStore,
    default_price_book_db_path,
    load_price_book_defaults,
    load_price_book_seed,
)
from app.scanner.hash import FileHashCache
from app.scanner.scan import scan_recipes, to_tsv
from app.shopping import (
    aggregate_weekly_plan,
    format_sectioned_shopping_list,
    format_shopping_list,
    group_shopping_list_by_section,
)
from app.sync.llm import LLMClient, LLMParseError, LLMSettings
from app.sync.pipeline import run_sync_pipeline
from app.sync.recipe_schema import RecipeValidationError, validate_recipe
from app.sync.store import RecipeStore, default_recipes_db_path


CLI_ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = CLI_ROOT.parent
LOCAL_SCAN_ROOT = PROJECT_ROOT / "Питание" / "Рецепты"
DEMO_SCAN_ROOT = PROJECT_ROOT / "Пример базы" / "Рецепты"
DEFAULT_SCAN_ROOT = LOCAL_SCAN_ROOT if LOCAL_SCAN_ROOT.is_dir() else DEMO_SCAN_ROOT
DEFAULT_PLAN_OUTPUT_DIR = PROJECT_ROOT / "Питание" / "Планирование"


def load_env(env_path: Path) -> None:
    if not env_path.exists():
        return

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


def configure_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )


def cmd_scan(args: argparse.Namespace) -> None:
    logger = logging.getLogger(__name__)
    root = Path(args.root).expanduser()
    config_path = Path(args.config).expanduser()
    categories = load_categories(config_path)
    hash_cache = FileHashCache() if args.with_hash else None
    records = scan_recipes(root, categories, hash_cache=hash_cache)
    logger.info("scan: %s recipes", len(records))
    missing = sum(1 for item in records if item.category is None)
    if missing:
        logger.warning("scan: %s recipes without category", missing)
    if args.update_index:
        index_path = Path(args.index).expanduser()
        file_index = FileIndex(index_path)
        synced, needs_sync, removed = file_index.reconcile_scan(records)
        logger.info(
            "index: synced=%s needs_sync=%s removed=%s",
            synced,
            needs_sync,
            removed,
        )
    if args.output == "tsv":
        print(to_tsv(records))


def cmd_status(args: argparse.Namespace) -> None:
    index_path = Path(args.index).expanduser()
    file_index = FileIndex(index_path)
    total = file_index.count_active()
    by_status = file_index.count_by_status()
    needs_sync = by_status.get("needs_sync", 0)
    by_category = file_index.count_by_category()

    print(f"total: {total}")
    print(f"needs_sync: {needs_sync}")
    print("by_category:")
    for category, count in by_category.items():
        label = category if category else "(uncategorized)"
        print(f"- {label}: {count}")


def cmd_sync(args: argparse.Namespace) -> None:
    logger = logging.getLogger(__name__)
    index_path = Path(args.index).expanduser()
    recipes_db_path = Path(args.recipes_db).expanduser()
    selected_paths = _resolve_selected_paths(args.select)
    if args.all and selected_paths:
        raise SystemExit("sync failed: --all cannot be combined with --select")
    if args.all and args.category:
        raise SystemExit("sync failed: --all cannot be combined with --category")
    if args.force and not args.all:
        raise SystemExit("sync failed: --force currently requires --all")

    file_index = FileIndex(index_path)
    recipe_store = RecipeStore(recipes_db_path)
    try:
        settings = LLMSettings.from_env()
        llm_client = LLMClient(settings)
        logger.info(
            "sync llm: provider=%s model=%s base=%s path=%s json_mode=%s",
            settings.provider,
            settings.model,
            settings.api_base,
            settings.api_path,
            settings.json_mode,
        )
        logger.info(
            "sync filter: all=%s category=%s select=%s limit=%s dry_run=%s",
            args.all,
            args.category,
            len(selected_paths) if selected_paths else 0,
            args.limit,
            args.dry_run,
        )
        summary = run_sync_pipeline(
            file_index=file_index,
            recipe_store=recipe_store,
            llm_client=llm_client,
            category=args.category,
            selected_paths=selected_paths,
            limit=args.limit,
            dry_run=args.dry_run,
            force=args.force,
        )
    except LLMParseError as exc:
        raise SystemExit(f"sync failed: {exc}") from exc

    logger.info(
        "sync: selected=%s synced=%s cached=%s failed=%s skipped=%s dry_run=%s",
        summary.selected,
        summary.synced,
        summary.cached,
        summary.failed,
        summary.skipped,
        args.dry_run,
    )


def cmd_validate_recipe(args: argparse.Namespace) -> None:
    recipe_path = Path(args.file).expanduser()
    payload = json.loads(recipe_path.read_text(encoding="utf-8"))
    try:
        validate_recipe(payload)
    except RecipeValidationError as exc:
        raise SystemExit(f"invalid recipe schema: {exc}") from exc
    print("recipe schema: valid")


def cmd_plan(args: argparse.Namespace) -> None:
    if args.categories:
        print("available_categories:")
        for category, default in DEFAULT_WEEKLY_QUOTAS.items():
            print(f"- {category}: default={default}")
        return

    index_path = Path(args.index).expanduser()
    recipes_db_path = Path(args.recipes_db).expanduser()
    sections_config_path = Path(args.ingredient_sections).expanduser()
    price_book_db_path = Path(args.price_book_db).expanduser()
    output_dir = Path(args.output_dir).expanduser()
    file_index = FileIndex(index_path)
    recipe_store = RecipeStore(recipes_db_path)
    quotas = _resolve_plan_quotas(args)

    prepared = prepare_planning_data(
        file_index=file_index,
        recipe_store=recipe_store,
    )
    availability = check_category_availability(prepared.recipes, quotas=quotas)
    needs_sync_entries = file_index.get_by_status("needs_sync")
    warnings = _build_weekly_warnings(availability, needs_sync_entries)
    weekly_plan = None
    shopping_list = None
    sectioned = None
    cost_estimate = None

    print(f"synced_recipes: {len(prepared.recipes)}")
    print("by_category:")
    for line in format_availability_report(availability):
        print(line)
    print(f"sufficient_for_week: {'yes' if availability.is_sufficient else 'no'}")
    if not availability.is_sufficient:
        print("errors:")
        for category, missing in availability.missing_categories.items():
            print(f"- {category}: missing {missing}")
    else:
        weekly_plan = build_weekly_plan(
            prepared.recipes,
            quotas=quotas,
            rng=random.Random(args.seed) if args.seed is not None else None,
        )
        print("weekly_plan:")
        for line in format_weekly_plan(weekly_plan):
            print(line)
        shopping_list = aggregate_weekly_plan(weekly_plan)
        if shopping_list.totals or shopping_list.null_amounts or shopping_list.to_taste:
            print("shopping_list:")
            for line in format_shopping_list(shopping_list):
                print(line)
            ingredient_sections = load_ingredient_sections(sections_config_path)
            sectioned = group_shopping_list_by_section(shopping_list, ingredient_sections)
            print("shopping_list_by_section:")
            for line in format_sectioned_shopping_list(sectioned):
                print(line)
            cost_estimate = estimate_shopping_list_cost(
                shopping_list,
                price_book_store=PriceBookStore(price_book_db_path),
            )
            print("cost_estimate:")
            for line in format_cost_estimate(cost_estimate):
                print(line)

    note_title = args.week_title or default_week_title(date.today())
    weekly_note = render_weekly_note(
        WeeklyNoteContext(
            title=note_title,
            weekly_plan=weekly_plan,
            shopping_list=shopping_list,
            cost_estimate=cost_estimate,
            warnings=warnings,
        )
    )
    filename = default_week_filename(note_title, date.today())
    output_path = save_weekly_note(weekly_note, output_dir, filename)
    state_path = None
    if weekly_plan is not None:
        state_path = save_weekly_plan_state(
            weekly_plan,
            title=note_title,
            destination=default_plan_state_path(output_path),
        )
    print("weekly_note_template:")
    print(weekly_note, end="")
    print(f"weekly_note_saved: {output_path}")
    if state_path is not None:
        print(f"weekly_plan_state_saved: {state_path}")


def cmd_plan_rebuild(args: argparse.Namespace) -> None:
    index_path = Path(args.index).expanduser()
    recipes_db_path = Path(args.recipes_db).expanduser()
    price_book_db_path = Path(args.price_book_db).expanduser()
    plan_file = Path(args.file).expanduser()
    state_path = _resolve_plan_state_input(plan_file)
    category, slot_index = _resolve_rebuild_target(args)

    file_index = FileIndex(index_path)
    recipe_store = RecipeStore(recipes_db_path)
    saved_plan = load_weekly_plan_state(state_path)
    current_plan = hydrate_weekly_plan(saved_plan, recipe_store=recipe_store)

    prepared = prepare_planning_data(
        file_index=file_index,
        recipe_store=recipe_store,
    )
    updated_plan = rebuild_weekly_plan_slot(
        current_plan,
        all_recipes=prepared.recipes,
        category=category,
        slot_index=slot_index,
    )
    shopping_list = aggregate_weekly_plan(updated_plan)
    cost_estimate = estimate_shopping_list_cost(
        shopping_list,
        price_book_store=PriceBookStore(price_book_db_path),
    )
    note_path = _resolve_note_path_from_state(state_path)
    weekly_note = render_weekly_note(
        WeeklyNoteContext(
            title=saved_plan.title,
            weekly_plan=updated_plan,
            shopping_list=shopping_list,
            cost_estimate=cost_estimate,
            warnings=_build_weekly_warnings(
                check_category_availability(prepared.recipes, quotas=updated_plan.quotas),
                file_index.get_by_status("needs_sync"),
            ),
        )
    )
    save_weekly_note(weekly_note, note_path.parent, note_path.name)
    save_weekly_plan_state(updated_plan, title=saved_plan.title, destination=state_path)
    print(f"rebuilt_category: {category}")
    print(f"rebuilt_slot: {slot_index + 1}")
    print(f"weekly_note_saved: {note_path}")
    print(f"weekly_plan_state_saved: {state_path}")


def cmd_price_book_list(args: argparse.Namespace) -> None:
    store = PriceBookStore(Path(args.db).expanduser())
    entries = store.list_entries()
    if not entries:
        print("price_book: empty")
        return
    for entry in entries:
        print(
            f"{entry.ingredient_name}\t{entry.unit}\t{entry.price_per_unit:g}\t"
            f"{entry.currency}\t{entry.source}"
        )


def cmd_price_book_get(args: argparse.Namespace) -> None:
    store = PriceBookStore(Path(args.db).expanduser())
    entry = store.get_entry(args.ingredient, args.unit)
    if entry is None:
        raise SystemExit("price-book: entry not found")
    print(
        f"{entry.ingredient_name}\t{entry.unit}\t{entry.price_per_unit:g}\t"
        f"{entry.currency}\t{entry.source}"
    )


def cmd_price_book_set(args: argparse.Namespace) -> None:
    store = PriceBookStore(Path(args.db).expanduser())
    store.upsert_entry(
        ingredient_name=args.ingredient,
        unit=args.unit,
        price_per_unit=args.price,
        currency=args.currency,
        source=args.source,
    )
    print("price-book: saved")


def cmd_price_book_delete(args: argparse.Namespace) -> None:
    store = PriceBookStore(Path(args.db).expanduser())
    deleted = store.delete_entry(args.ingredient, args.unit)
    print("price-book: deleted" if deleted else "price-book: entry not found")


def cmd_price_book_seed_defaults(args: argparse.Namespace) -> None:
    store = PriceBookStore(Path(args.db).expanduser())
    try:
        defaults = load_price_book_defaults(Path(args.defaults).expanduser())
    except PriceBookConfigError as exc:
        raise SystemExit(f"price-book defaults invalid: {exc}") from exc
    count = store.seed_defaults(defaults)
    print(f"price-book: seeded {count} entries")


def cmd_price_book_export_seed(args: argparse.Namespace) -> None:
    count = export_price_book_seed_from_recipes(
        Path(args.recipes_db).expanduser(),
        Path(args.output).expanduser(),
        currency=args.currency,
        source=args.source,
    )
    print(f"price-book: exported {count} entries")
    print(f"price-book_seed_saved: {Path(args.output).expanduser()}")


def cmd_price_book_import_seed(args: argparse.Namespace) -> None:
    store = PriceBookStore(Path(args.db).expanduser())
    try:
        seed_entries = load_price_book_seed(Path(args.seed).expanduser())
    except PriceBookConfigError as exc:
        raise SystemExit(f"price-book seed invalid: {exc}") from exc

    imported = 0
    skipped = 0
    for entry in seed_entries:
        if entry.price_per_unit is None:
            skipped += 1
            continue
        store.upsert_entry(
            ingredient_name=entry.ingredient_name,
            unit=entry.unit,
            price_per_unit=entry.price_per_unit,
            currency=entry.currency,
            source=entry.source,
        )
        imported += 1
    print(f"price-book: imported {imported} entries")
    print(f"price-book: skipped {skipped} entries without price")


def cmd_run_mvp(args: argparse.Namespace) -> None:
    logger = logging.getLogger(__name__)
    index_path = Path(args.index).expanduser()
    recipes_db_path = Path(args.recipes_db).expanduser()

    if not args.skip_scan:
        logger.info("mvp: scan")
        cmd_scan(
            argparse.Namespace(
                root=args.root,
                config=args.config,
                output="none",
                with_hash=True,
                update_index=True,
                index=str(index_path),
            )
        )

    logger.info("mvp: status")
    cmd_status(argparse.Namespace(index=str(index_path)))

    if not args.skip_sync:
        logger.info("mvp: sync")
        cmd_sync(
            argparse.Namespace(
                index=str(index_path),
                recipes_db=str(recipes_db_path),
                all=True,
                category=None,
                select=None,
                limit=args.sync_limit,
                dry_run=args.dry_run_sync,
            )
        )

    if not args.skip_plan:
        logger.info("mvp: plan")
        cmd_plan(
            argparse.Namespace(
                index=str(index_path),
                recipes_db=str(recipes_db_path),
                ingredient_sections=args.ingredient_sections,
                price_book_db=args.price_book_db,
                output_dir=args.output_dir,
                week_title=args.week_title,
                seed=args.seed,
            )
        )


def cmd_manual_sync_ui(_: argparse.Namespace) -> None:
    script_path = CLI_ROOT / "tools" / "manual_recipe_ui.py"
    subprocess.run([sys.executable, str(script_path)], check=True)


def _resolve_selected_paths(raw_paths: Optional[list[str]]) -> Optional[list[Path]]:
    if not raw_paths:
        return None
    return [Path(value).expanduser() for value in raw_paths]


def _resolve_plan_quotas(args: argparse.Namespace) -> dict[str, int]:
    quotas = dict(DEFAULT_WEEKLY_QUOTAS)
    for category in DEFAULT_WEEKLY_QUOTAS:
        value = getattr(args, category, None)
        if value is not None:
            if value < 0:
                raise SystemExit(f"plan failed: --{category} must be >= 0")
            quotas[category] = value
    return quotas


def _resolve_rebuild_target(args: argparse.Namespace) -> tuple[str, int]:
    selected: list[tuple[str, int]] = []
    for category in DEFAULT_WEEKLY_QUOTAS:
        value = getattr(args, category, None)
        if value is None:
            continue
        if value < 1:
            raise SystemExit(f"plan-rebuild failed: --{category} index must be >= 1")
        selected.append((category, value - 1))
    if not selected:
        raise SystemExit("plan-rebuild failed: choose one category flag, for example --soup or --main 2")
    if len(selected) > 1:
        raise SystemExit("plan-rebuild failed: only one category can be rebuilt at a time")
    return selected[0]


def _resolve_plan_state_input(path: Path) -> Path:
    if path.suffix == ".json":
        return path
    return default_plan_state_path(path)


def _resolve_note_path_from_state(path: Path) -> Path:
    if path.name.endswith(".plan.json"):
        return path.with_name(path.name[: -len(".plan.json")] + ".md")
    return path.with_suffix(".md")


def _build_weekly_warnings(availability, needs_sync_entries) -> list[str]:
    warnings: list[str] = []
    if availability.missing_categories:
        for category, missing in availability.missing_categories.items():
            warnings.append(f"Not enough recipes in category '{category}': missing {missing}")
    if needs_sync_entries:
        warnings.append(f"Recipes pending sync: {len(needs_sync_entries)}")
        for entry in needs_sync_entries[:5]:
            warnings.append(f"needs_sync: {entry.path}")
        if len(needs_sync_entries) > 5:
            warnings.append(f"... and {len(needs_sync_entries) - 5} more")
    return warnings


def _add_subcommand(
    subparsers: argparse._SubParsersAction, name: str, handler: Callable[[argparse.Namespace], None]
) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(name)
    parser.set_defaults(handler=handler)
    return parser


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="meal-planner")
    parser.add_argument("--log-level", default="INFO")
    subparsers = parser.add_subparsers(dest="command", required=True)

    scan_parser = _add_subcommand(subparsers, "scan", cmd_scan)
    scan_parser.add_argument("--root", default=str(DEFAULT_SCAN_ROOT))
    scan_parser.add_argument("--config", default=str(CLI_ROOT / "config" / "categories.yaml"))
    scan_parser.add_argument("--output", choices=["none", "tsv"], default="none")
    scan_parser.add_argument("--with-hash", action="store_true")
    scan_parser.add_argument("--update-index", action="store_true")
    scan_parser.add_argument(
        "--index",
        default=str(default_db_path(CLI_ROOT)),
    )

    status_parser = _add_subcommand(subparsers, "status", cmd_status)
    status_parser.add_argument(
        "--index",
        default=str(default_db_path(CLI_ROOT)),
    )
    sync_parser = _add_subcommand(subparsers, "sync", cmd_sync)
    sync_parser.add_argument(
        "--index",
        default=str(default_db_path(CLI_ROOT)),
    )
    sync_parser.add_argument(
        "--recipes-db",
        default=str(default_recipes_db_path(CLI_ROOT)),
    )
    sync_parser.add_argument(
        "--all",
        action="store_true",
        help="Sync all recipes currently marked as needs_sync.",
    )
    sync_parser.add_argument(
        "--category",
        choices=["soup", "main", "salad", "breakfast", "snack", "drink"],
        help="Sync only recipes from one category.",
    )
    sync_parser.add_argument(
        "--select",
        nargs="+",
        help="Sync only the specified recipe markdown files.",
    )
    sync_parser.add_argument("--limit", type=int, default=None)
    sync_parser.add_argument(
        "--force",
        action="store_true",
        help="Re-parse even already synced recipes and ignore cached content_hash results. Requires --all.",
    )
    sync_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run selection, cache and validation without writing DB changes.",
    )
    validate_parser = _add_subcommand(subparsers, "validate-recipe", cmd_validate_recipe)
    validate_parser.add_argument("--file", required=True)
    plan_parser = _add_subcommand(subparsers, "plan", cmd_plan)
    plan_parser.add_argument(
        "--index",
        default=str(default_db_path(CLI_ROOT)),
    )
    plan_parser.add_argument(
        "--recipes-db",
        default=str(default_recipes_db_path(CLI_ROOT)),
    )
    plan_parser.add_argument(
        "--ingredient-sections",
        default=str(CLI_ROOT / "config" / "ingredient_sections.yaml"),
    )
    plan_parser.add_argument(
        "--price-book-db",
        default=str(default_price_book_db_path(CLI_ROOT)),
    )
    plan_parser.add_argument(
        "--output-dir",
        default=str(DEFAULT_PLAN_OUTPUT_DIR),
        help="Directory where the weekly markdown note will be written.",
    )
    plan_parser.add_argument(
        "--week-title",
        default=None,
        help="Optional markdown title for the weekly note.",
    )
    plan_parser.add_argument(
        "--seed",
        type=int,
        default=None,
        help="Optional seed for reproducible random meal selection.",
    )
    plan_parser.add_argument(
        "--categories",
        action="store_true",
        help="Print all configurable categories with default quotas and exit.",
    )
    for category, default in DEFAULT_WEEKLY_QUOTAS.items():
        plan_parser.add_argument(
            f"--{category}",
            type=int,
            default=None,
            help=f"Override weekly quota for '{category}' (default: {default}).",
        )

    rebuild_parser = _add_subcommand(subparsers, "plan-rebuild", cmd_plan_rebuild)
    rebuild_parser.add_argument(
        "--index",
        default=str(default_db_path(CLI_ROOT)),
    )
    rebuild_parser.add_argument(
        "--recipes-db",
        default=str(default_recipes_db_path(CLI_ROOT)),
    )
    rebuild_parser.add_argument(
        "--price-book-db",
        default=str(default_price_book_db_path(CLI_ROOT)),
    )
    rebuild_parser.add_argument(
        "--file",
        required=True,
        help="Path to weekly note markdown or adjacent .plan.json state file.",
    )
    for category in DEFAULT_WEEKLY_QUOTAS:
        rebuild_parser.add_argument(
            f"--{category}",
            nargs="?",
            const=1,
            type=int,
            default=None,
            help=f"Rebuild only this category. Optional 1-based slot index for categories with multiple recipes.",
        )

    run_parser = _add_subcommand(subparsers, "run-mvp", cmd_run_mvp)
    run_parser.add_argument("--root", default=str(DEFAULT_SCAN_ROOT))
    run_parser.add_argument("--config", default=str(CLI_ROOT / "config" / "categories.yaml"))
    run_parser.add_argument("--index", default=str(default_db_path(CLI_ROOT)))
    run_parser.add_argument("--recipes-db", default=str(default_recipes_db_path(CLI_ROOT)))
    run_parser.add_argument("--ingredient-sections", default=str(CLI_ROOT / "config" / "ingredient_sections.yaml"))
    run_parser.add_argument("--price-book-db", default=str(default_price_book_db_path(CLI_ROOT)))
    run_parser.add_argument("--output-dir", default=str(DEFAULT_PLAN_OUTPUT_DIR))
    run_parser.add_argument("--week-title", default=None)
    run_parser.add_argument("--seed", type=int, default=None)
    run_parser.add_argument("--sync-limit", type=int, default=None)
    run_parser.add_argument("--dry-run-sync", action="store_true")
    run_parser.add_argument("--skip-scan", action="store_true")
    run_parser.add_argument("--skip-sync", action="store_true")
    run_parser.add_argument("--skip-plan", action="store_true")

    _add_subcommand(subparsers, "manual-sync-ui", cmd_manual_sync_ui)

    price_book_parser = _add_subcommand(subparsers, "price-book", lambda _: None)
    price_book_subparsers = price_book_parser.add_subparsers(dest="price_book_command", required=True)
    default_price_db = str(default_price_book_db_path(CLI_ROOT))
    default_price_defaults = str(CLI_ROOT / "config" / "price_book.defaults.json")

    price_list_parser = _add_subcommand(price_book_subparsers, "list", cmd_price_book_list)
    price_list_parser.add_argument("--db", default=default_price_db)

    price_get_parser = _add_subcommand(price_book_subparsers, "get", cmd_price_book_get)
    price_get_parser.add_argument("ingredient")
    price_get_parser.add_argument("unit")
    price_get_parser.add_argument("--db", default=default_price_db)

    price_set_parser = _add_subcommand(price_book_subparsers, "set", cmd_price_book_set)
    price_set_parser.add_argument("ingredient")
    price_set_parser.add_argument("unit")
    price_set_parser.add_argument("price", type=float)
    price_set_parser.add_argument("--currency", default="RUB")
    price_set_parser.add_argument("--source", default="manual")
    price_set_parser.add_argument("--db", default=default_price_db)

    price_delete_parser = _add_subcommand(price_book_subparsers, "delete", cmd_price_book_delete)
    price_delete_parser.add_argument("ingredient")
    price_delete_parser.add_argument("unit")
    price_delete_parser.add_argument("--db", default=default_price_db)

    price_seed_parser = _add_subcommand(price_book_subparsers, "seed-defaults", cmd_price_book_seed_defaults)
    price_seed_parser.add_argument("--db", default=default_price_db)
    price_seed_parser.add_argument("--defaults", default=default_price_defaults)

    price_export_seed_parser = _add_subcommand(price_book_subparsers, "export-seed", cmd_price_book_export_seed)
    price_export_seed_parser.add_argument("--recipes-db", default=str(default_recipes_db_path(CLI_ROOT)))
    price_export_seed_parser.add_argument("--output", default=str(CLI_ROOT / "data" / "price_book.seed.json"))
    price_export_seed_parser.add_argument("--currency", default="RUB")
    price_export_seed_parser.add_argument("--source", default="seed")

    price_import_seed_parser = _add_subcommand(price_book_subparsers, "import-seed", cmd_price_book_import_seed)
    price_import_seed_parser.add_argument("--db", default=default_price_db)
    price_import_seed_parser.add_argument("--seed", default=str(CLI_ROOT / "data" / "price_book.seed.json"))

    return parser


def main() -> int:
    root = Path(__file__).resolve().parent
    load_env(root / "config" / ".env")
    parser = build_parser()
    args = parser.parse_args()
    configure_logging(args.log_level)
    handler = getattr(args, "handler", None)
    if handler is None:
        parser.error("Missing command handler")
    handler(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
