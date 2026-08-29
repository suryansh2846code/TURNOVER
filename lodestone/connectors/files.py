"""Local files connector — ingest a folder of text/markdown/code docs."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from .base import Connector, SyncResult

TEXT_EXT = {
    ".md", ".markdown", ".txt", ".rst", ".org",
    ".py", ".js", ".ts", ".tsx", ".jsx", ".json", ".yaml", ".yml",
    ".html", ".css", ".sh", ".java", ".go", ".rs", ".c", ".cpp", ".sql",
}
# Only prose feeds the knowledge graph; code is still stored + searchable, but
# extracting entities from source produces junk (TitleCase identifiers).
PROSE_EXT = {".md", ".markdown", ".txt", ".rst", ".org"}
IGNORE_DIRS = {
    ".git", "node_modules", "__pycache__", ".venv", "venv", "env",
    "dist", "build", "out", ".next", ".nuxt", "target", "coverage",
    "vendor", ".cache", ".turbo", ".parcel-cache", "bower_components",
    ".pytest_cache", ".mypy_cache", ".gradle", ".idea", ".vscode",
    "site-packages", "migrations", ".terraform",
}
# generated / lock / minified files that are noise in a knowledge base
IGNORE_FILES = {
    "package-lock.json", "yarn.lock", "pnpm-lock.yaml", "poetry.lock",
    "composer.lock", "cargo.lock", "go.sum",
}
def _is_junk_file(name: str) -> bool:
    n = name.lower()
    if n in IGNORE_FILES:
        return True
    return n.endswith((".min.js", ".min.css", ".map", ".bundle.js", ".lock"))

MAX_BYTES = 2_000_000
# guardrail default; overridable via LODESTONE_MAX_FILES for large corpora


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
        from ..config import get_settings
        max_files = get_settings().max_files
        if len(files) > max_files:
            result.errors.append(
                f"{len(files)} files found — that's a lot. Refusing to ingest more "
                f"than {max_files} at once. Point at a smaller/more specific folder, "
                "or raise the limit with LODESTONE_MAX_FILES.")
            result.detail = f"too many files ({len(files)}) under {root}"
            return self._finish(result)
        for fp in files:
            try:
                if fp.stat().st_size > MAX_BYTES:
                    result.skipped += 1
                    continue
                text = fp.read_text(encoding="utf-8", errors="ignore")
            except Exception as exc:  # unreadable file
                result.errors.append(f"{fp.name}: {exc}")
                continue
            # Route through the brain so the knowledge graph is built too.
            # fast=True → offline heuristic extraction, so bulk imports stay quick.
            # Only prose builds the graph; code is stored + searchable but skipped.
            from ..brain import get_brain
            out = get_brain().ingest(
                text, source=self.name, kind="doc", title=fp.name,
                uri=str(fp), fast=True,
                build_graph=fp.suffix.lower() in PROSE_EXT,
            )
            if out["memories"]:
                result.added += out["memories"]
            else:
                result.skipped += 1
        result.detail = f"scanned {len(files)} files under {root}"
        self._remember_path(str(root))
        return self._finish(result)

    def _remember_path(self, path: str) -> None:
        """Record synced folders so background sync can re-index them."""
        import json
        state = self.store.get_connector_state(self.name) or {}
        try:
            paths = set(json.loads(state.get("cursor") or "[]"))
        except Exception:
            paths = set()
        paths.add(path)
        self.store.set_connector_state(
            self.name, cursor=json.dumps(sorted(paths)), status="ok")

    @classmethod
    def synced_paths(cls, store) -> list[str]:
        import json
        state = store.get_connector_state(cls.name) or {}
        try:
            return json.loads(state.get("cursor") or "[]")
        except Exception:
            return []

    def _walk(self, root: Path, recursive: bool, allow: set[str]) -> list[Path]:
        if root.is_file():
            return [root]
        out: list[Path] = []
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in IGNORE_DIRS]
            for fn in filenames:
                if Path(fn).suffix.lower() in allow and not _is_junk_file(fn):
                    out.append(Path(dirpath) / fn)
            if not recursive:
                break
        return out
