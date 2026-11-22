from __future__ import annotations

import sys
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.index.file_index import FileIndex, default_db_path
from app.manual_sync import (
    ManualRecipeDraft,
    export_recipe_json,
    parse_ingredients_text,
    parse_steps_text,
    save_manual_recipe,
)
from app.sync.recipe_schema import ALLOWED_CATEGORIES, ALLOWED_UNITS
from app.sync.store import RecipeStore, default_recipes_db_path


CLI_ROOT = Path(__file__).resolve().parents[1]


class ManualRecipeApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("Manual Recipe Sync")
        self.root.geometry("980x760")

        self.index_db_var = tk.StringVar(value=str(default_db_path(CLI_ROOT)))
        self.recipes_db_var = tk.StringVar(value=str(default_recipes_db_path(CLI_ROOT)))
        self.source_path_var = tk.StringVar()
        self.category_var = tk.StringVar(value=ALLOWED_CATEGORIES[0])
        self.title_var = tk.StringVar()
        self.servings_var = tk.StringVar()
        self.confidence_var = tk.StringVar(value="1.0")
        self.notes_var = tk.StringVar()

        self._build_layout()

    def _build_layout(self) -> None:
        frame = ttk.Frame(self.root, padding=12)
        frame.pack(fill=tk.BOTH, expand=True)
        frame.columnconfigure(1, weight=1)

        self._add_labeled_entry(frame, 0, "Index DB", self.index_db_var)
        self._add_labeled_entry(frame, 1, "Recipes DB", self.recipes_db_var)

        ttk.Label(frame, text="Source markdown").grid(row=2, column=0, sticky="w", pady=4)
        source_row = ttk.Frame(frame)
        source_row.grid(row=2, column=1, sticky="ew", pady=4)
        source_row.columnconfigure(0, weight=1)
        ttk.Entry(source_row, textvariable=self.source_path_var).grid(row=0, column=0, sticky="ew")
        ttk.Button(source_row, text="Browse", command=self._browse_source_path).grid(row=0, column=1, padx=(8, 0))

        ttk.Label(frame, text="Category").grid(row=3, column=0, sticky="w", pady=4)
        ttk.Combobox(
            frame,
            textvariable=self.category_var,
            values=ALLOWED_CATEGORIES,
            state="readonly",
        ).grid(row=3, column=1, sticky="ew", pady=4)

        self._add_labeled_entry(frame, 4, "Title", self.title_var)
        self._add_labeled_entry(frame, 5, "Servings", self.servings_var)
        self._add_labeled_entry(frame, 6, "Confidence", self.confidence_var)
        self._add_labeled_entry(frame, 7, "Notes", self.notes_var)

        ttk.Label(
            frame,
            text="Ingredients: one per line as name|amount|unit|note",
        ).grid(row=8, column=0, columnspan=2, sticky="w", pady=(12, 4))
        self.ingredients_text = tk.Text(frame, height=10, wrap="word")
        self.ingredients_text.grid(row=9, column=0, columnspan=2, sticky="nsew")

        ttk.Label(
            frame,
            text="Steps: one step per line",
        ).grid(row=10, column=0, columnspan=2, sticky="w", pady=(12, 4))
        self.steps_text = tk.Text(frame, height=10, wrap="word")
        self.steps_text.grid(row=11, column=0, columnspan=2, sticky="nsew")

        ttk.Label(
            frame,
            text=f"Allowed units: {', '.join(ALLOWED_UNITS)}",
        ).grid(row=12, column=0, columnspan=2, sticky="w", pady=(12, 4))

        buttons = ttk.Frame(frame)
        buttons.grid(row=13, column=0, columnspan=2, sticky="ew", pady=(12, 0))
        ttk.Button(buttons, text="Preview JSON", command=self._preview_json).pack(side=tk.LEFT)
        ttk.Button(buttons, text="Save as Synced", command=self._save_recipe).pack(side=tk.LEFT, padx=(8, 0))

        ttk.Label(frame, text="Preview / result").grid(row=14, column=0, columnspan=2, sticky="w", pady=(12, 4))
        self.preview_text = tk.Text(frame, height=12, wrap="word")
        self.preview_text.grid(row=15, column=0, columnspan=2, sticky="nsew")

        frame.rowconfigure(9, weight=1)
        frame.rowconfigure(11, weight=1)
        frame.rowconfigure(15, weight=1)

    def _add_labeled_entry(self, parent: ttk.Frame, row: int, label: str, variable: tk.StringVar) -> None:
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", pady=4)
        ttk.Entry(parent, textvariable=variable).grid(row=row, column=1, sticky="ew", pady=4)

    def _browse_source_path(self) -> None:
        path = filedialog.askopenfilename(
            title="Select markdown file",
            filetypes=[("Markdown", "*.md"), ("All files", "*.*")],
        )
        if path:
            self.source_path_var.set(path)

    def _build_draft(self) -> ManualRecipeDraft:
        ingredients = parse_ingredients_text(self.ingredients_text.get("1.0", tk.END))
        steps = parse_steps_text(self.steps_text.get("1.0", tk.END))
        servings = self._parse_optional_number(self.servings_var.get())
        confidence = self._parse_required_float(self.confidence_var.get(), "confidence")
        return ManualRecipeDraft(
            source_path=self.source_path_var.get().strip(),
            category=self.category_var.get().strip(),
            title=self.title_var.get().strip(),
            servings=servings,
            ingredients=ingredients,
            steps=steps,
            notes=self.notes_var.get().strip() or None,
            confidence=confidence,
        )

    def _preview_json(self) -> None:
        try:
            draft = self._build_draft()
            preview = export_recipe_json(draft)
        except Exception as exc:  # pragma: no cover - UI feedback path
            messagebox.showerror("Preview failed", str(exc))
            return
        self._set_preview(preview)

    def _save_recipe(self) -> None:
        try:
            draft = self._build_draft()
            file_index = FileIndex(Path(self.index_db_var.get()).expanduser())
            recipe_store = RecipeStore(Path(self.recipes_db_var.get()).expanduser())
            recipe_payload = save_manual_recipe(
                draft=draft,
                file_index=file_index,
                recipe_store=recipe_store,
            )
        except Exception as exc:  # pragma: no cover - UI feedback path
            messagebox.showerror("Save failed", str(exc))
            return

        self._set_preview(export_recipe_json(draft))
        messagebox.showinfo(
            "Saved",
            f"Recipe saved as manually synced:\n{recipe_payload['title']}",
        )

    def _set_preview(self, value: str) -> None:
        self.preview_text.delete("1.0", tk.END)
        self.preview_text.insert("1.0", value)

    @staticmethod
    def _parse_optional_number(raw_value: str):
        value = raw_value.strip()
        if not value:
            return None
        return float(value)

    @staticmethod
    def _parse_required_float(raw_value: str, field: str) -> float:
        value = raw_value.strip()
        if not value:
            raise ValueError(f"{field} is required")
        return float(value)


def main() -> int:
    root = tk.Tk()
    ManualRecipeApp(root)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
