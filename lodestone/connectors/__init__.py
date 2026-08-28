"""Connectors ingest external data sources into the local brain."""
from __future__ import annotations

from .base import Connector, SyncResult
from .files import FilesConnector
from .notes import NotesConnector
from .gmail import GmailConnector
from .notion import NotionConnector
from .gdrive import GoogleDriveConnector

REGISTRY: dict[str, type[Connector]] = {
    FilesConnector.name: FilesConnector,
    NotesConnector.name: NotesConnector,
    GmailConnector.name: GmailConnector,
    NotionConnector.name: NotionConnector,
    GoogleDriveConnector.name: GoogleDriveConnector,
}


def get_connector(name: str) -> Connector:
    if name not in REGISTRY:
        raise KeyError(f"unknown connector '{name}'. known: {list(REGISTRY)}")
    return REGISTRY[name]()


__all__ = ["Connector", "SyncResult", "REGISTRY", "get_connector"]
