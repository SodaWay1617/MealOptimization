# Repository Guidelines

## Project Structure

- `meal-planner/cli.py` is the Python 3.11+ CLI entry point. `meal-planner/app/web/` contains the Flask API. Other modules under `meal-planner/app/` own scanning, indexing, synchronization, planning, shopping, pricing, and Markdown output.
- `web/` contains the React application. `meal-planner/config/` contains schemas and defaults, `meal-planner/data/` contains public seed data, and `meal-planner/tests/` contains the Python test suite.
- `Пример базы/` is the public sample vault. `Питание/` is an ignored local workspace.

## Development

From the repository root, run `docker compose up --build -d` and open `http://127.0.0.1:8080`. Use the root `.env.example` for vault paths and `meal-planner/config/.env.example` for LLM settings. See `README.md` for setup.

From `meal-planner/`, run `python cli.py --help` for CLI options and `python -m unittest discover -s tests` for tests. Use the sample vault and README for browser checks. Use temporary notes and SQLite stores for write tests.

## Code and Recipes

Follow nearby Python type annotations and naming. Use four-space indentation, `snake_case` for modules and functions, `PascalCase` for classes, and uppercase constants. Name standard-library unittest files `test_*.py` and methods `test_*`.

When saving a new recipe from the app, add an Obsidian wikilink to the matching Markdown index table. Use the selected subcategory table when the category has several indexes. Preserve existing rows and ratings.

## Commits and Pull Requests

Use concise commit subjects. Summarize behavior changes and verification in PRs. Link related issues when available. Include an example note or screenshot for changes to generated output or the interface.

Keep credentials, personal notes, local SQLite stores, generated logs, and IDE settings out of commits. Use test data for examples and external integration checks.
