"""Running a sync, and reporting what it is doing."""
from __future__ import annotations

from fastapi import APIRouter

from ...config import get_settings
from ...log import get_logger
from ...scheduler import get_scheduler

log = get_logger(__name__)
router = APIRouter()


@router.get("/api/sync/status")
def sync_status():
    s = get_scheduler()
    st = get_settings()
    return {"enabled": st.sync_enabled, "interval_minutes": st.sync_interval_minutes,
            "syncing": s.syncing, "last_run": s.last_run, "last_result": s.last_result}


@router.post("/api/sync/cancel")
def sync_cancel():
    """Stop an in-flight sync. Cooperative — the current source finishes but no
    further sources are synced, and `syncing` clears shortly after."""
    return {"cancelled": get_scheduler().cancel_sync()}


@router.post("/api/sync/now")
def sync_now():
    import threading
    s = get_scheduler()
    if s.syncing:
        return {"started": False, "reason": "already syncing"}
    threading.Thread(target=s.sync_all, kwargs={"interactive": False},
                     daemon=True).start()
    return {"started": True}
