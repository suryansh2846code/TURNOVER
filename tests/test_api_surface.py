"""The HTTP surface is a contract, and it is now assembled from six modules.

`api/app.py` used to be one 1500-line file holding all 105 routes. It is now a
composition root that includes routers from `api/routes/`, which is a better
shape to work in and a worse shape to be careless in: a router that is written
but never added to `ALL_ROUTERS` disappears in silence, and the frontend calls
relative paths, so the failure shows up as a dead button rather than an error
anyone sees at startup.

`api_surface.json` is the frozen list. Update it deliberately when adding or
removing an endpoint — never to make this test pass.
"""
import json
import pathlib

from fastapi.testclient import TestClient

from chitragupta.api.app import app
from chitragupta.api.routes import ALL_ROUTERS

FROZEN = pathlib.Path(__file__).parent / "api_surface.json"


def _live_surface():
    return sorted(f"{method.upper()} {path}"
                  for path, ops in app.openapi()["paths"].items() for method in ops)


def test_every_route_is_still_served():
    expected = json.loads(FROZEN.read_text())
    live = _live_surface()
    missing = sorted(set(expected) - set(live))
    added = sorted(set(live) - set(expected))
    assert not missing, (
        f"{len(missing)} endpoint(s) vanished — a router that is not in "
        f"ALL_ROUTERS fails exactly this way: {missing[:8]}")
    assert not added, (
        f"{len(added)} new endpoint(s). If that is intended, regenerate "
        f"{FROZEN.name}: {added[:8]}")


def test_every_router_is_mounted():
    """A module can define a perfectly good router and never be included."""
    import chitragupta.api.routes as pkg

    modules = [p.stem for p in pathlib.Path(pkg.__file__).parent.glob("*.py")
               if p.stem != "__init__"]
    mounted = {id(r) for r in ALL_ROUTERS}
    for name in modules:
        module = getattr(pkg, name)
        assert id(module.router) in mounted, f"routes/{name}.py is never mounted"
    assert len(ALL_ROUTERS) == len(modules)


def test_no_router_is_empty():
    for router in ALL_ROUTERS:
        assert router.routes, "a mounted router contributes no routes"


def test_a_literal_path_is_never_shadowed_by_a_parameter():
    """FastAPI matches in registration order, so `/api/brain/canonical/review`
    registered after `/api/brain/canonical/{section}` becomes a request for a
    section named "review" — a 200 with the wrong body, not an error.

    This is the specific hazard the router split introduced, because relative
    order now depends on which module a route landed in.
    """
    client = TestClient(app)
    for literal in ("/api/brain/canonical/review", "/api/brain/canonical/evaluate"):
        r = client.get(literal)
        assert r.status_code == 200, literal
        body = r.json()
        # `{section}` answers with a section payload; the literal routes do not.
        assert not (isinstance(body, dict) and body.get("section")), (
            f"{literal} is being served by /api/brain/canonical/{{section}} — "
            "the parameterised route was registered first")


def test_the_composition_root_stays_a_composition_root():
    """The file was split because 105 routes in one module could not be read.
    Nothing stops the next route being added straight back into it."""
    source = pathlib.Path(app.__module__.replace(".", "/") + ".py")
    source = pathlib.Path(__file__).parent.parent / "chitragupta/api/app.py"
    text = source.read_text()
    for verb in ("@app.get(", "@app.post(", "@app.put(", "@app.delete(", "@app.patch("):
        assert verb not in text, (
            f"a route is declared in app.py ({verb}…) — it belongs in api/routes/")
    assert len(text.splitlines()) < 200, "app.py is growing back into a monolith"
