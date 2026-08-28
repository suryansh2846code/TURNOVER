"""Google Drive connector — ingests Docs / text / PDF files (read-only)."""
from __future__ import annotations

import io
from typing import Any

from ..core.chunk import chunk_text
from .base import Connector, SyncResult
from .google_auth import get_credentials, google_ready

# Which Drive mime types we know how to read, and how.
EXPORT_AS_TEXT = "application/vnd.google-apps.document"
PLAIN_TYPES = {"text/plain", "text/markdown", "text/csv"}
PDF_TYPE = "application/pdf"


class GoogleDriveConnector(Connector):
    name = "gdrive"
    label = "Google Drive"

    def is_configured(self) -> tuple[bool, str]:
        return google_ready()

    def sync(self, *, query: str | None = None, max_results: int = 50,
             interactive: bool = True, **_: Any) -> SyncResult:
        result = SyncResult(connector=self.name)
        try:
            from googleapiclient.discovery import build  # lazy
            from googleapiclient.http import MediaIoBaseDownload
        except ImportError:
            result.errors.append("pip install .[gdrive] to use the Drive connector")
            return self._finish(result)

        try:
            creds = get_credentials(interactive=interactive)
            service = build("drive", "v3", credentials=creds, cache_discovery=False)
            mime_filter = (
                f"(mimeType='{EXPORT_AS_TEXT}' or mimeType='{PDF_TYPE}' or "
                + " or ".join(f"mimeType='{m}'" for m in PLAIN_TYPES)
                + ")"
            )
            q = query or f"{mime_filter} and trashed=false"
            listing = (
                service.files()
                .list(q=q, pageSize=max_results,
                      fields="files(id,name,mimeType,webViewLink)")
                .execute()
            )
            files = listing.get("files", [])
            for f in files:
                try:
                    text = self._read_file(service, f, MediaIoBaseDownload)
                except Exception as exc:
                    result.errors.append(f"{f['name']}: {exc}")
                    continue
                if not text.strip():
                    result.skipped += 1
                    continue
                for i, chunk in enumerate(chunk_text(text)):
                    mem = self.store.add(
                        text=chunk,
                        source=self.name,
                        kind="doc",
                        title=f["name"] if i == 0 else f"{f['name']} (part {i + 1})",
                        uri=f.get("webViewLink"),
                        metadata={"file_id": f["id"], "chunk": i},
                    )
                    if mem:
                        result.added += 1
                    else:
                        result.skipped += 1
            result.detail = f"{len(files)} files"
        except Exception as exc:
            result.errors.append(str(exc))
            result.detail = "sync failed"
        return self._finish(result)

    def _read_file(self, service, f: dict, downloader_cls) -> str:
        mime = f["mimeType"]
        if mime == EXPORT_AS_TEXT:
            data = service.files().export(
                fileId=f["id"], mimeType="text/plain"
            ).execute()
            return data.decode("utf-8", errors="ignore") if isinstance(data, bytes) else data

        buf = io.BytesIO()
        request = service.files().get_media(fileId=f["id"])
        downloader = downloader_cls(buf, request)
        done = False
        while not done:
            _, done = downloader.next_chunk()
        raw = buf.getvalue()
        if mime == PDF_TYPE:
            return self._pdf_text(raw)
        return raw.decode("utf-8", errors="ignore")

    def _pdf_text(self, raw: bytes) -> str:
        try:
            from pypdf import PdfReader  # lazy
        except ImportError:
            return ""
        reader = PdfReader(io.BytesIO(raw))
        return "\n".join((page.extract_text() or "") for page in reader.pages)
