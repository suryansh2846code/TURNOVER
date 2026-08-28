"""Local files connector — ingest a folder of text/markdown/code docs."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from ..core.chunk import chunk_text
from .base import Connector, SyncResult

TEXT_EXT = {
    ".md", ".markdown", ".txt", ".rst", ".org",
    ".py", ".js", ".ts", ".tsx", ".jsx", ".json", ".yaml", ".yml",
    ".html", ".css", ".sh", ".java", ".go", ".rs", ".c", ".cpp", ".sql",
}
IGNORE_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", "dist", "build"}
MAX_BYTES = 2_000_000


class FilesConnector(Connector):
    name = "files"
    label = "Local Files"
    always_available = True

    def sync(self, *, path: str = "", recursive: bool = True,
             exts: list[str] | None = None, **_: Any) -> SyncResult:
        result = SyncResult(connector=self.name)
        root = Path(path).expanduser()
        if not root.exists():
            result.errors.append(f"path not found: {root}")
            result.detail = "path not found"
            return self._finish(result)

        allow = {e if e.startswith(".") else f".{e}" for e in (exts or [])} or TEXT_EXT
        files = self._walk(root, recursive, allow)
        for fp in files:
            try:
                if fp.stat().st_size > MAX_BYTES:
                    result.skipped += 1
                    continue
                text = fp.read_text(encoding="utf-8", errors="ignore")
            except Exception as exc:  # unreadable file
                result.errors.append(f"{fp.name}: {exc}")
                continue
            chunks = chunk_text(text)
            for i, chunk in enumerate(chunks):
                mem = self.store.add(
                    text=chunk,
                    source=self.name,
                    kind="doc",
                    title=fp.name if i == 0 else f"{fp.name} (part {i + 1})",
                    uri=str(fp),
                    metadata={"chunk": i, "chunks": len(chunks)},
                )
                if mem:
                    result.added += 1
                else:
                    result.skipped += 1
        result.detail = f"scanned {len(files)} files under {root}"
        return self._finish(result)

    def _walk(self, root: Path, recursive: bool, allow: set[str]) -> list[Path]:
        if root.is_file():
            return [root]
        out: list[Path] = []
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in IGNORE_DIRS]
            for fn in filenames:
                if Path(fn).suffix.lower() in allow:
                    out.append(Path(dirpath) / fn)
            if not recursive:
                break
        return out
