"""Slow work must not be able to freeze the window.

Every route handler here is a plain `def`, so FastAPI runs it in one shared
worker-thread pool — and the app's own interface is served by the same server.
That shared pool has no priority in it: when enough slow handlers are in flight,
the cheap ones the UI polls cannot get a thread and the window stops responding.
It has happened: `/auth/status` polled every 2s called `/refresh` (1.6–6.4s per
provider), requests queued faster than they finished, and the whole app froze.

`api/concurrency.py` moves slow handlers into their own bounded lanes. These
tests hold the shared pool down to a *tiny* number of threads on purpose — if
the slow routes were still using it, they could not possibly all be served, so
a passing result is evidence the isolation is real rather than incidental.
"""
import threading
import time

import anyio
import httpx
import pytest

from chitragupta.api import concurrency
from chitragupta.api.app import app

SLOW = 0.25          # long enough to overlap, short enough to keep the suite fast


class _Recorder:
    """Counts how many calls are inside the block at once."""

    def __init__(self):
        self.lock = threading.Lock()
        self.live = 0
        self.peak = 0

    def __enter__(self):
        with self.lock:
            self.live += 1
            self.peak = max(self.peak, self.live)
        return self

    def __exit__(self, *_):
        with self.lock:
            self.live -= 1


@pytest.fixture
def slow_probe(monkeypatch):
    """Make the sign-in status probe block, the way a real CLI call does."""
    rec = _Recorder()

    class _Flow:
        def status(self):
            with rec:
                time.sleep(SLOW)
            from chitragupta.models.auth_flows import AuthStatus
            return AuthStatus(provider_id="cursor", status="idle")

    monkeypatch.setattr("chitragupta.models.auth_flows.get_flow", lambda _n: _Flow())
    return rec


def _run(coro_fn):
    return anyio.run(coro_fn)


async def _client():
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1")


def test_the_ui_still_answers_while_slow_probes_are_saturated(slow_probe):
    """The whole point. Twenty blocking probes are in flight and the shared
    pool is throttled to two threads — the interface must still be served."""
    async def scenario():
        limiter = anyio.to_thread.current_default_thread_limiter()
        original, limiter.total_tokens = limiter.total_tokens, 2
        try:
            async with await _client() as c:
                slow = [c.get("/api/providers/cursor/auth/status") for _ in range(20)]
                async with anyio.create_task_group() as tg:
                    for request in slow:
                        tg.start_soon(lambda r=request: r)
                    await anyio.sleep(SLOW / 3)          # let the lane fill up
                    started = time.perf_counter()
                    ui = await c.get("/api/sync/status")
                    took = time.perf_counter() - started
            return ui.status_code, took
        finally:
            limiter.total_tokens = original

    status, took = _run(scenario)
    assert status == 200
    # Generous bound: the assertion is "it answered at all while 20 blocking
    # probes were running", not a latency target.
    assert took < SLOW * 4, f"the UI waited {took:.2f}s behind slow probes"


def test_the_probe_lane_is_actually_bounded(slow_probe):
    """A lane that does not cap concurrency is not a lane. Without this, 200
    simultaneous sign-in polls would spawn 200 vendor-CLI subprocesses."""
    async def scenario():
        async with await _client() as c, anyio.create_task_group() as tg:
            for _ in range(25):
                tg.start_soon(lambda: c.get("/api/providers/cursor/auth/status"))
    _run(scenario)
    cap = int(concurrency.PROBES.total_tokens)
    assert slow_probe.peak <= cap, (
        f"{slow_probe.peak} probes ran at once with a cap of {cap}")
    assert slow_probe.peak > 1, "nothing ran concurrently — the test proved nothing"


def test_model_turns_and_provider_probes_do_not_share_a_lane():
    """A chat turn can run for a minute. If it shared the probe lane, a single
    conversation could hold up every sign-in check behind it."""
    assert concurrency.MODEL_CALLS is not concurrency.PROBES


def test_the_slow_routes_are_the_ones_on_a_lane():
    """The decorator is easy to forget on the next slow endpoint. These are the
    handlers measured in seconds — model turns, and anything that spawns a
    vendor CLI or queries a provider."""
    import inspect

    from chitragupta.api.routes import agents, brain, connectors, providers

    must_be_offloaded = [
        (agents, "chat"),
        (brain, "brain_digest"), (brain, "brain_enrich"),
        (providers, "models_catalog"), (providers, "providers"),
        (providers, "refresh_provider_endpoint"), (providers, "auth_start_endpoint"),
        (providers, "auth_status_endpoint"), (providers, "save_provider_key"),
        (connectors, "connectors"), (connectors, "sync"),
    ]
    for module, name in must_be_offloaded:
        fn = getattr(module, name)
        assert inspect.iscoroutinefunction(fn), (
            f"{module.__name__}.{name} blocks for seconds but still runs in the "
            "shared pool — give it a lane in api/concurrency.py")


def test_offloading_does_not_change_what_fastapi_sees():
    """FastAPI builds path, query and body parameters from the signature. If the
    decorator hid it, every offloaded route would take an untyped `**kwargs` and
    silently stop validating anything."""
    import inspect

    from chitragupta.api.routes import providers

    sig = inspect.signature(providers.disconnect_provider_endpoint)
    assert list(sig.parameters) == ["name", "scope"]
    assert sig.parameters["scope"].default == "all"


def test_the_shared_pool_is_widened_at_startup():
    """40 threads shared by every handler is the framework default, not a
    considered number."""
    assert concurrency.DEFAULT_THREAD_LIMIT >= 64
