"""Connectors ingest external data sources into the local brain."""
from __future__ import annotations

from .apple_calendar import AppleCalendarConnector
from .apple_mail import AppleMailConnector
from .base import Connector, SyncResult
from .files import FilesConnector
from .gcal import GoogleCalendarConnector
from .gdrive import GoogleDriveConnector
from .github import GitHubConnector
from .gmail import GmailConnector
from .imessage import IMessageConnector
from .linear import LinearConnector
from .notes import NotesConnector
from .notion import NotionConnector

REGISTRY: dict[str, type[Connector]] = {
    FilesConnector.name: FilesConnector,
    NotesConnector.name: NotesConnector,
    GmailConnector.name: GmailConnector,
    GoogleCalendarConnector.name: GoogleCalendarConnector,
    NotionConnector.name: NotionConnector,
    GoogleDriveConnector.name: GoogleDriveConnector,
    IMessageConnector.name: IMessageConnector,
    AppleMailConnector.name: AppleMailConnector,
    AppleCalendarConnector.name: AppleCalendarConnector,
    LinearConnector.name: LinearConnector,
    GitHubConnector.name: GitHubConnector,
}


def get_connector(name: str) -> Connector:
    # Custom user-defined API apps are addressed as "custom:<id>".
    if name.startswith("custom:"):
        from .custom_api import CustomAPIConnector, get_app
        app = get_app(name.split(":", 1)[1])
        if not app:
            raise KeyError(f"unknown custom app '{name}'")
        return CustomAPIConnector(app)
    if name not in REGISTRY:
        raise KeyError(f"unknown connector '{name}'. known: {list(REGISTRY)}")
    return REGISTRY[name]()


__all__ = ["REGISTRY", "Connector", "SyncResult", "get_connector"]
