from __future__ import annotations

import re
from pathlib import Path
from tempfile import NamedTemporaryFile


TABLE_SEPARATOR = re.compile(r"\s*\|(?:\s*:?-{3,}:?\s*\|)+\s*")
INDEX_LINK = re.compile(r"^\s*(?:-\s*)?\[\[([^\]|]+)\]\]\s*$", re.MULTILINE)


def recipe_indexes(directory: Path) -> list[Path]:
    index = directory / f"{directory.name}.md"
    if not index.is_file():
        return [index]
    text = index.read_text(encoding="utf-8-sig")
    if any(TABLE_SEPARATOR.fullmatch(line) for line in text.splitlines()):
        return [index]
    linked = []
    for name in INDEX_LINK.findall(text):
        if Path(name).name != name or "\\" in name:
            continue
        child = directory / "Категории" / f"{name}.md"
        if child.is_file() and child.resolve().is_relative_to(directory.resolve()):
            linked.append(child)
    return list(dict.fromkeys(linked)) or [index]


def add_index_link(index: Path, recipe: Path, title: str) -> None:
    if index.exists() and index.is_symlink():
        raise OSError("Recipe index is a symbolic link")
    previous = index.read_bytes() if index.exists() else b""
    text = previous.decode("utf-8")
    newline = "\r\n" if "\r\n" in text else "\n"
    lines = text.splitlines(keepends=True)
    label = " ".join(title.split()).translate(str.maketrans({"[": "(", "]": ")", "|": "¦"}))
    link = f"[[{recipe.stem}\\|{label}]]"
    for number, line in enumerate(lines):
        separator = TABLE_SEPARATOR.fullmatch(line)
        if not separator:
            continue
        columns = line.count("|") - 1
        position = number + 1
        while position < len(lines) and lines[position].strip().startswith("|"):
            position += 1
        if not lines[position - 1].endswith(("\n", "\r")):
            lines[position - 1] += newline
        lines.insert(position, f"| {link} |" + " - |" * (columns - 1) + newline)
        updated = "".join(lines)
        break
    else:
        prefix = text + ("" if not text or text.endswith(newline * 2) else newline if text.endswith(newline) else newline * 2)
        updated = prefix + newline.join((
            "| Рецепт | Готовил | Оценка |",
            "| --- | --- | --- |",
            f"| {link} | - | - |",
            "",
        ))

    with NamedTemporaryFile(dir=index.parent, delete=False) as output:
        pending = Path(output.name)
        try:
            output.write(updated.encode("utf-8"))
        except OSError:
            output.close()
            pending.unlink()
            raise
    try:
        if (index.read_bytes() if index.exists() else b"") != previous:
            raise OSError("Recipe index changed while saving")
        pending.replace(index)
    finally:
        pending.unlink(missing_ok=True)
