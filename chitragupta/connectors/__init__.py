"""Connectors ingest external data sources into the local brain."""
from __future__ import annotations

from .apple_calendar import AppleCalendarConnector
from .apple_health import AppleHealthConnector
from .apple_mail import AppleMailConnector
from .base import Connector, SyncResult
from .files import FilesConnector
from .gcal import GoogleCalendarConnector
from .gdrive import GoogleDriveConnector
from .github import GitHubConnector
from .gmail import GmailConnector
from .google_fit import GoogleFitConnector
from .imessage import IMessageConnector
from .linear import LinearConnector
from .notes import NotesConnector
from .notion import NotionConnector
from .slack import SlackConnector
from .telegram import TelegramConnector

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
    SlackConnector.name: SlackConnector,
    TelegramConnector.name: TelegramConnector,
    AppleHealthConnector.name: AppleHealthConnector,
    GoogleFitConnector.name: GoogleFitConnector,
}


def get_connector(name: str) -> Connector:
    # MCP-backed connectors are addressed as "mcp:<id>". They are not in
    # REGISTRY because there is one per server the user configured, not one per
    # class — the same reason custom apps are not.
    if name.startswith("mcp:"):
        from .mcp_source import MCPConnector, get_server
        spec = get_server(name.split(":", 1)[1])
        if not spec:
            raise KeyError(f"unknown MCP connector '{name}'")
        return MCPConnector(spec)
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
