"""Every path the frontend calls must be a path the server serves.

The workspace calls relative paths from `app.js`, so a call to an endpoint that
does not exist is not an error anybody sees. `api()` rejects on a non-ok
response and most call sites have no `catch`, so the click becomes an unhandled
promise rejection: nothing happens, nothing is said, and the button looks
merely unresponsive.

That is not hypothetical. The brain-search delete button shipped in `cefe525`
calling `DELETE /api/memories/{id}`, which was never written — the same commit
added the button and two *other* endpoints. It stayed dead for two weeks
because no test connects the two sides.

`test_api_surface.py` pins the server's side of the contract. This pins the
client's: the two lists have to meet.
"""
import re

from web_sources import app_source

from lodestone.api.app import app

#: `api("/api/x")`, `api(`/api/x/${y}`)`, and the bare `fetch("/api/…")` calls.
_CALL = re.compile(r"""(?:\bapi|\bfetch)\(\s*(?:`([^`]+)`|"(/[^"]*)")""")

#: A `${…}` interpolation is exactly one path segment at request time. What it
#: holds is unknowable here — `${id}` is a value, but `${path}` in the approvals
#: handler is the literal "approve" or "reject" — so it matches any one segment.
_INTERP = re.compile(r"\$\{[^}]*\}")

#: `{ method: "POST" }` in the options object, which may start on the next line.
_METHOD = re.compile(r'method:\s*"([A-Z]+)"')

_ANY = "\x00"


def _segments(path: str) -> list[str]:
    return path.strip("/").split("/")


def _frontend_calls() -> set[tuple[str, str]]:
    """Every (method, path) pair `app.js` asks for, interpolations blanked.

    The verb matters as much as the path: `/api/brain/memories/{id}` answers GET
    whether or not anyone wrote the DELETE, so a path-only check would have gone
    green on the very bug this file exists for.
    """
    src = app_source()
    found = set()
    for m in _CALL.finditer(src):
        raw = m.group(1) or m.group(2)
        if not raw.startswith("/"):
            continue                      # `api(p, o)` — the helper's own body
        path = _INTERP.sub(_ANY, raw).split("?", 1)[0].rstrip("/") or "/"
        # The options object belongs to this call only, so stop at the next one.
        tail = src[m.end():m.end() + 200].split("api(")[0].split("fetch(")[0]
        verb = _METHOD.search(tail)
        found.add((verb.group(1) if verb else "GET", path))
    return found


def _matches(called: str, served: str) -> bool:
    """Could a request for `called` be routed to `served`?

    Both sides carry wildcards — `${…}` on the client, `{param}` on the server —
    so this is pattern against pattern, not string against pattern. A segment
    pair agrees when either side is a wildcard, or both are the same literal.
    """
    a, b = _segments(called), _segments(served)
    if len(a) != len(b):
        return False
    return all(x in (_ANY, y) or y.startswith("{")
               for x, y in zip(a, b, strict=True))


def _serves(verb: str, path: str) -> bool:
    for served, ops in app.openapi()["paths"].items():
        if _matches(path, served) and verb.lower() in ops:
            return True
    return False


def test_every_call_the_frontend_makes_is_served():
    dead = sorted(c for c in _frontend_calls() if not _serves(*c))
    assert not dead, (
        f"{len(dead)} call(s) in app.js reach no endpoint — each is a control "
        f"that silently does nothing when clicked: "
        f"{[f'{v} ' + p.replace(_ANY, '${…}') for v, p in dead]}")


def test_the_extractor_actually_finds_the_calls():
    """A regex that matched nothing would make the test above vacuously green."""
    calls = _frontend_calls()
    assert len(calls) > 50, f"only found {len(calls)} calls — the regex has drifted"
    assert ("GET", "/api/brain/stats") in calls             # a plain string call
    assert ("POST", f"/api/agents/{_ANY}/chat/stream") in calls   # template + verb
    assert ("DELETE", f"/api/brain/memories/{_ANY}") in calls     # the fixed button


def test_a_call_with_no_route_is_actually_caught():
    """The matcher is permissive by design; prove it still fails on a real miss."""
    assert not _serves("DELETE", f"/api/memories/{_ANY}")   # the original bug
    assert not _serves("DELETE", "/api/brain/stats")        # right path, wrong verb
    assert _serves("POST", f"/api/agents/{_ANY}/clear")     # a real one still passes


# ── the endpoint that was missing ────────────────────────────────────────────
# The contract test above only proves a route answers. These prove it does the
# thing the button promises: the memory is gone from the brain, gone from the
# count the panel refreshes, and a second click reports "not found" rather than
# claiming success twice.

def test_deleting_a_memory_removes_it_from_the_brain():
    from fastapi.testclient import TestClient

    from lodestone.brain import get_brain

    client = TestClient(app)
    brain = get_brain()
    before = brain.store.count()
    mem = brain.store.add("A memory the user picked out of a search result.",
                          source="manual", kind="fact")

    assert client.get(f"/api/brain/memories/{mem.id}").status_code == 200
    assert brain.store.count() == before + 1

    r = client.delete(f"/api/brain/memories/{mem.id}")
    assert r.status_code == 200, r.text
    assert r.json()["deleted"] == mem.id

    assert brain.store.get(mem.id) is None
    # A retraction would leave the row — and `count()` counts every row — so the
    # panel's "memories" number would not move and the delete would read as a
    # no-op. Hard delete is what this button means.
    assert brain.store.count() == before


def test_deleting_a_memory_that_is_not_there_is_a_404_not_a_success():
    from fastapi.testclient import TestClient

    client = TestClient(app)
    assert client.delete("/api/brain/memories/no-such-memory").status_code == 404
