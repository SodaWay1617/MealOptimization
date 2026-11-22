from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Optional, Set

from app.config.categories import category_for_path
from app.scanner.hash import FileHashCache


IGNORE_DIRS: Set[str] = {".obsidian", ".trash", "Категории"}


@dataclass(frozen=True)
class RecipeFile:
    path: Path
    category: Optional[str]
    mtime: float
    size: int
    content_hash: Optional[str] = None


def _should_ignore(path: Path) -> bool:
    return any(part in IGNORE_DIRS for part in path.parts)


def _is_index_note(path: Path, root: Path) -> bool:
    stem = path.stem.strip().casefold()
    if stem == root.name.strip().casefold():
        return True
    parent_name = path.parent.name.strip().casefold()
    return stem == parent_name


def scan_recipes(
    root: Path,
    categories: dict[str, str],
    *,
    hash_cache: Optional[FileHashCache] = None,
) -> List[RecipeFile]:
    if not root.exists():
        raise FileNotFoundError(f"Recipes root not found: {root}")

    results: List[RecipeFile] = []
    for file_path in root.rglob("*.md"):
        if _should_ignore(file_path):
            continue
        if not file_path.is_file():
            continue
        if _is_index_note(file_path, root):
            continue
        stat = file_path.stat()
        content_hash: Optional[str] = None
        if hash_cache is not None:
            content_hash = hash_cache.hash_if_changed(
                file_path,
                mtime=stat.st_mtime,
                size=stat.st_size,
            )
        results.append(
            RecipeFile(
                path=file_path,
                category=category_for_path(file_path, categories),
                mtime=stat.st_mtime,
                size=stat.st_size,
                content_hash=content_hash,
            )
        )
    return results


def to_tsv(records: Iterable[RecipeFile]) -> str:
    lines: List[str] = []
    for item in records:
        category = item.category or ""
        content_hash = item.content_hash or ""
        lines.append(
            f"{item.path}\t{category}\t{item.mtime}\t{item.size}\t{content_hash}"
        )
    return "\n".join(lines)
