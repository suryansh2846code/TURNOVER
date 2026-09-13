"""The FastAPI application: middleware, lifespan, and the routers it is made of.

This module is the composition root and nothing else. The routes themselves live
in `api/routes/`, grouped by subject — see that package's docstring for why the
order they are mounted in matters.
"""
from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from ..config import get_settings
from ..log import get_logger
from ..scheduler import get_scheduler
from .assets import WEB
from .concurrency import _apply_thread_limit
from .routes import ALL_ROUTERS
from .security import refusal as _origin_refusal

log = get_logger(__name__)


@asynccontextmanager
async def _lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Start the background sync loop with the server, and stop it with it.

    `on_event("startup")` is deprecated, but the reason to move was the missing
    other half: there was no shutdown hook, so the scheduler thread outlived a
    reload and two of them ran at once.
    """
    await _apply_thread_limit()
    get_scheduler().start()
    try:
        yield
    finally:
        try:
            get_scheduler().stop()
        except Exception as exc:                            # pragma: no cover
            log.debug("scheduler did not stop cleanly: %s", exc)


app = FastAPI(title="Lodestone", version="0.2.0", lifespan=_lifespan)


@app.middleware("http")
async def _guard_origin(request: Request,
                        call_next: Callable[[Request], Awaitable[Response]]) -> Response:
    """Refuse requests that a website — rather than this app — sent us.

    See `api/security.py`. This server lists the user's home directory, stores
    provider credentials and can erase the brain, so "it only listens on
    loopback" is not by itself a security boundary: every browser on the machine
    is also on the machine.
    """
    reason = _origin_refusal(request.method, request.headers)
    if reason:
        return JSONResponse({"detail": reason}, status_code=403)

    resp = await call_next(request)
    # Nothing here is meant to be framed, embedded or sniffed by another page.
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    resp.headers.setdefault("Cross-Origin-Resource-Policy", "same-origin")
    resp.headers.setdefault("X-Frame-Options", "DENY")
    resp.headers.setdefault("Referrer-Policy", "no-referrer")
    return resp


@app.middleware("http")
async def _no_cache_assets(request: Request,
                           call_next: Callable[[Request], Awaitable[Response]]) -> Response:
    """Never cache the UI assets, so a code update is picked up on a normal
    reload — no hard-refresh needed."""
    resp = await call_next(request)
    p = request.url.path
    if p == "/" or p == "/onboarding" or p.startswith("/static"):
        resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    return resp


for _router in ALL_ROUTERS:
    app.include_router(_router)

app.mount("/static", StaticFiles(directory=str(WEB)), name="static")


def run(reload: bool = False) -> None:
    import uvicorn

    s = get_settings()
    print(f"\n  ◆ Lodestone workspace → http://{s.host}:{s.port}")
    print(f"    model: {s.model_provider}   brain: {s.home}"
          + ("   (dev: backend auto-reloads)" if reload else "") + "\n")
    if reload:
        # watch the package so edits to any .py hot-reload the server
        uvicorn.run("lodestone.api.app:app", host=s.host, port=s.port, reload=True,
                    reload_dirs=[str(Path(__file__).resolve().parent.parent)],
                    log_level="info")
    else:
        uvicorn.run(app, host=s.host, port=s.port, log_level="info")
