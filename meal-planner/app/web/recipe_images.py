from __future__ import annotations

import re
from pathlib import Path, PurePosixPath


IMAGE_EMBED = re.compile(
    r"!?\[\[!?([^\[\]|\r\n]+?\.(?:png|jpe?g|gif|webp|avif|bmp))(?:\|[^\]\r\n]*)?\]\]",
    re.IGNORECASE,
)
IMAGE_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".avif": "image/avif",
    ".bmp": "image/bmp",
}


def find_image(root: Path, recipe: Path, target: str) -> Path | None:
    if not target or "\\" in target or "\x00" in target:
        return None
    relative = PurePosixPath(target)
    if relative.is_absolute() or ".." in relative.parts or relative.suffix.lower() not in IMAGE_TYPES:
        return None

    category = root / recipe.relative_to(root).parts[0]
    locations = (recipe.parent, category / "Картинки", root)
    for directory in locations:
        candidate = (directory / relative).resolve()
        if candidate.is_relative_to(root) and candidate.is_file():
            return candidate

    if len(relative.parts) != 1:
        return None
    matches = [
        candidate.resolve()
        for candidate in root.rglob("*")
        if candidate.name.casefold() == relative.name.casefold()
        and candidate.is_file() and candidate.resolve().is_relative_to(root)
    ]
    unique = set(matches)
    return unique.pop() if len(unique) == 1 else None
