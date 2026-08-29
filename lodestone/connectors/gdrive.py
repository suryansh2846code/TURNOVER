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
DOCX_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
PPTX_TYPE = "application/vnd.openxmlformats-officedocument.presentationml.presentation"
# Google-native Slides/Sheets export to text too
GSLIDES = "application/vnd.google-apps.presentation"


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
            all_types = [EXPORT_AS_TEXT, PDF_TYPE, DOCX_TYPE, PPTX_TYPE,
                         GSLIDES, *PLAIN_TYPES]
            mime_filter = (
                "(" + " or ".join(f"mimeType='{m}'" for m in all_types)
                + ")"
            )
            q = query or f"{mime_filter} and trashed=false"
            # paginate + include Shared-with-me and Shared Drives
            files: list[dict] = []
            page_token = None
            while len(files) < max_results:
                listing = (
                    service.files()
                    .list(q=q, pageSize=min(100, max_results - len(files)),
                          pageToken=page_token,
                          includeItemsFromAllDrives=True, supportsAllDrives=True,
                          corpora="allDrives",
                          fields="nextPageToken,files(id,name,mimeType,webViewLink,"
                                 "modifiedTime,owners(displayName))")
                    .execute()
                )
                files += listing.get("files", [])
                page_token = listing.get("nextPageToken")
                if not page_token:
                    break
            for f in files:
                try:
                    text = self._read_file(service, f, MediaIoBaseDownload)
                except Exception as exc:
                    result.errors.append(f"{f['name']}: {exc}")
                    continue
                if not text.strip():
                    result.skipped += 1
                    continue
                event_date = (f.get("modifiedTime") or "")[:10] or None
                owner = ""
                if f.get("owners"):
                    owner = f["owners"][0].get("displayName", "")
                for i, chunk in enumerate(chunk_text(text)):
                    mem = self.store.add(
                        text=chunk,
                        source=self.name,
                        kind="doc",
                        title=f["name"] if i == 0 else f"{f['name']} (part {i + 1})",
                        uri=f.get("webViewLink"),
                        event_date=event_date,
                        metadata={"file_id": f["id"], "chunk": i, "owner": owner},
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
        # Google-native docs/slides export straight to text
        if mime in (EXPORT_AS_TEXT, GSLIDES):
            data = service.files().export(
                fileId=f["id"], mimeType="text/plain"
            ).execute()
            return data.decode("utf-8", errors="ignore") if isinstance(data, bytes) else data

        buf = io.BytesIO()
        request = service.files().get_media(fileId=f["id"], supportsAllDrives=True)
        downloader = downloader_cls(buf, request)
        done = False
        while not done:
            _, done = downloader.next_chunk()
        raw = buf.getvalue()
        if mime == PDF_TYPE:
            return self._pdf_text(raw)
        if mime == DOCX_TYPE:
            return self._docx_text(raw)
        if mime == PPTX_TYPE:
            return self._pptx_text(raw)
        return raw.decode("utf-8", errors="ignore")

    def _pdf_text(self, raw: bytes) -> str:
        try:
            from pypdf import PdfReader  # lazy
        except ImportError:
            return ""
        reader = PdfReader(io.BytesIO(raw))
        return "\n".join((page.extract_text() or "") for page in reader.pages)

    def _docx_text(self, raw: bytes) -> str:
        try:
            from docx import Document  # python-docx, lazy
        except ImportError:
            return ""
        doc = Document(io.BytesIO(raw))
        parts = [p.text for p in doc.paragraphs if p.text.strip()]
        for table in doc.tables:
            for row in table.rows:
                cells = [c.text.strip() for c in row.cells if c.text.strip()]
                if cells:
                    parts.append(" | ".join(cells))
        return "\n".join(parts)

    def _pptx_text(self, raw: bytes) -> str:
        try:
            from pptx import Presentation  # python-pptx, lazy
        except ImportError:
            return ""
        prs = Presentation(io.BytesIO(raw))
        parts = []
        for slide in prs.slides:
            for shape in slide.shapes:
                if shape.has_text_frame and shape.text_frame.text.strip():
                    parts.append(shape.text_frame.text)
        return "\n".join(parts)
