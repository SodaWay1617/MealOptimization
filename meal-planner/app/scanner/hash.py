from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Optional, Tuple


def _blake3_hash(path: Path) -> Optional[str]:
    try:
        import blake3  # type: ignore
    except ModuleNotFoundError:
        return None
    hasher = blake3.blake3()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def _sha256_hash(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def content_hash(path: Path) -> Tuple[str, str]:
    digest = _blake3_hash(path)
    if digest is not None:
        return "blake3", digest
    return "sha256", _sha256_hash(path)


@dataclass
class FileHashCache:
    _entries: Dict[Path, Tuple[float, int, str]] = field(default_factory=dict)

    def hash_if_changed(self, path: Path, *, mtime: float, size: int) -> str:
        cached = self._entries.get(path)
        if cached is not None:
            cached_mtime, cached_size, cached_hash = cached
            if cached_mtime == mtime and cached_size == size:
                return cached_hash

        _, digest = content_hash(path)
        self._entries[path] = (mtime, size, digest)
        return digest
