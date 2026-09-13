"""An expensive singleton must be built once, even when callers arrive together.

`@lru_cache` stores its result *after* the call returns, so it does not keep a
second caller out while the first is still building. That is invisible until the
constructor is slow and the callers are concurrent — which is exactly this app,
where loading the local embedding model takes ~10s and the scheduler thread plus
FastAPI's worker threads all reach for it during startup.

Measured before the fix, on a single launch of the real server:

    misses=1,2,3,4,5   hits=0   currsize=0

Five copies of the same model — **+44 MB resident** and ~40s of redundant CPU on
the threads serving the UI.

These tests use a deliberately slow factory, because a fast one cannot reproduce
the bug: the whole failure lives in the window between "call started" and "value
cached", and with a quick constructor that window is too small to lose a race in.
"""
from __future__ import annotations

import threading
import time

from lodestone.core.once import once


def build_concurrently(factory, threads: int = 8):
    """Call `factory` from N threads released as close to simultaneously as
    possible, and return what each of them got back."""
    start = threading.Barrier(threads)
    got: list = [None] * threads

    def worker(i: int) -> None:
        start.wait()
        got[i] = factory()

    workers = [threading.Thread(target=worker, args=(i,)) for i in range(threads)]
    for w in workers:
        w.start()
    for w in workers:
        w.join()
    return got


def test_a_slow_factory_runs_once_under_concurrent_callers():
    calls = []

    @once
    def build():
        calls.append(1)
        time.sleep(0.25)          # long enough for the others to arrive
        return object()

    build_concurrently(build)

    assert len(calls) == 1, (
        f"built {len(calls)} times — the second caller did not wait for the "
        "first, which is precisely how five embedding models got loaded")


def test_every_caller_gets_the_same_instance():
    @once
    def build():
        time.sleep(0.2)
        return object()

    results = build_concurrently(build)

    assert len({id(r) for r in results}) == 1


def test_lru_cache_really_does_fail_this_way():
    """The control. Without it this suite proves only that `once` works, not
    that it was needed — and the fix would look like superstition to the next
    reader."""
    from functools import lru_cache

    calls = []

    @lru_cache
    def build():
        calls.append(1)
        time.sleep(0.25)
        return object()

    build_concurrently(build)

    assert len(calls) > 1, (
        "lru_cache serialised concurrent first calls — if this ever passes, "
        "the reason `once` exists has changed and should be re-checked")


def test_the_value_is_reused_after_the_first_build():
    calls = []

    @once
    def build():
        calls.append(1)
        return object()

    first = build()
    assert build() is first
    assert build() is first
    assert len(calls) == 1


def test_it_can_be_cleared_like_the_cache_it_replaces():
    """The suite resets these between tests; a singleton that cannot be cleared
    would pin one test's temporary home for the whole run."""
    @once
    def build():
        return object()

    first = build()
    build.cache_clear()

    assert build() is not first


def test_clearing_mid_flight_does_not_wedge_it():
    @once
    def build():
        return object()

    build()
    build.cache_clear()
    build.cache_clear()          # clearing an empty cell must be harmless

    assert build() is not None


# ── the real singletons ────────────────────────────────────────────────────


def test_the_app_singletons_use_it():
    """Named individually rather than scanned, because these three are the ones
    that are expensive: each holds a database handle or a loaded model."""
    from lodestone.brain.brain import get_brain
    from lodestone.core.embeddings import get_embedder
    from lodestone.core.store import get_store

    for fn in (get_embedder, get_store, get_brain):
        assert hasattr(fn, "cache_clear"), f"{fn.__name__} lost cache_clear()"
        assert hasattr(fn, "cache_info"), f"{fn.__name__} lost cache_info()"


def test_the_store_is_built_once_under_concurrent_callers():
    """The end-to-end version: threads racing for the store the way the
    scheduler and the request handlers actually do."""
    from lodestone.core.store import get_store

    get_store.cache_clear()
    results = build_concurrently(get_store, threads=6)

    assert len({id(r) for r in results}) == 1, (
        "concurrent callers got different stores — each carries its own "
        "connection and its own embedder")
