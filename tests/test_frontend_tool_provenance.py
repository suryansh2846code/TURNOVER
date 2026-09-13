"""Where each of an agent's skills came from, executed rather than parsed.

A tool that reads the user's mail and a tool that searches their brain look
identical in a flat list, and until now the Tools panel showed exactly that
flat list. `GET /api/agents/tools` now carries provenance additively —
`source` plus `connector`, the connector's own user-facing label — and rows
that predate it carry no `source` at all, so a missing one means builtin.

Two rules make this more than a cosmetic grouping, and both are executed here:

* **The acronym for the protocol never reaches the screen.** `mcp_source.py`
  says so in as many words, for the same reason "vendor CLI" never reaches the
  sign-in card. The user added Linear; the user sees Linear.
* **A connector the user configured that cannot answer must say so**, in the
  panel they are looking at, instead of quietly contributing nothing — which
  renders as "Lodestone lost my connector".

`node --check` passes on a temporal dead-zone `ReferenceError`, and one of
those blanked the whole Models drawer. Source-order assertions miss a button
that is drawn but wired to nothing. So `tests/js/tool_provenance.mjs` runs the
real `renderToolList` and then clicks what it drew.
"""
from __future__ import annotations

import json
import pathlib
import re
import shutil
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
APP_JS = ROOT / "lodestone" / "web" / "app.js"
HARNESS = ROOT / "tests" / "js" / "tool_provenance.mjs"

pytestmark = pytest.mark.skipif(shutil.which("node") is None,
                                reason="node is needed to execute the frontend")


def render(scenario: dict, app_js: pathlib.Path | None = None) -> dict:
    proc = subprocess.run(
        ["node", str(HARNESS), str(app_js or APP_JS)],
        input=json.dumps(scenario), capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, f"harness crashed:\n{proc.stderr[:800]}"
    return json.loads(proc.stdout)


def group(report: dict, name: str) -> dict:
    found = [g for g in report["groups"] if g["name"] == name]
    assert found, f"no {name!r} group — rendered {[g['name'] for g in report['groups']]}"
    return found[0]


# A payload with one of everything: rows from before provenance existed, rows
# that declare themselves builtin, rows from two connectors, one connector that
# is healthy, one the user configured that cannot answer, and one we ship that
# they simply never set up.
SCENARIO = {
    "tools": [
        {"name": "search_brain", "description": "Search everything you've saved."},
        {"name": "remember", "description": "Save a fact.", "source": "builtin"},
        {"name": "linear_issues", "description": "List issues assigned to you.",
         "source": "mcp", "connector": "Linear"},
        {"name": "linear_comment", "description": "Comment on an issue.",
         "source": "mcp", "connector": "Linear"},
        {"name": "slack_search", "description": "Search your messages.",
         "source": "mcp", "connector": "Slack"},
    ],
    "connectors": [
        {"name": "gmail", "label": "Gmail", "ready": False,
         "reason": "Sign in with Google to use Gmail.", "custom": False},
        {"name": "mcp:linear", "label": "Linear", "ready": True, "reason": "",
         "custom": False, "mcp": True},
        {"name": "mcp:figma", "label": "Figma", "ready": False, "mcp": True,
         "custom": False,
         "reason": "Figma isn't signed in. Open it in Connectors and sign in "
                   "again — the sign-in happens with Figma, not with Lodestone."},
    ],
}


# ── the harness has to be able to fail ────────────────────────────────────
# A harness that passes against the bug it exists to catch is worse than none,
# because it reads as coverage. Both bugs below are the ones this feature is.
def _mutated(tmp_path: pathlib.Path, old: str, new: str) -> pathlib.Path:
    src = APP_JS.read_text()
    assert src.count(old) == 1, f"anchor moved, cannot reintroduce the bug: {old!r}"
    out = tmp_path / "app.js"
    out.write_text(src.replace(old, new))
    return out


def test_harness_catches_provenance_being_dropped(tmp_path):
    """Reintroduce "every tool is a builtin" and the harness must notice."""
    broken = _mutated(
        tmp_path,
        'if (!t || !t.source || t.source === "builtin" || isCategoryRow(t)) return "";',
        'if (t) return "";')
    names = [g["name"] for g in render(SCENARIO, broken)["groups"]]
    assert "Linear" not in names, (
        "the harness reported a Linear group from a render that cannot "
        "produce one — it is not executing the real path")


def test_harness_catches_an_unreachable_connector_going_silent(tmp_path):
    """Reintroduce "a connector that cannot answer just isn't there"."""
    broken = _mutated(
        tmp_path,
        "if (!userConfigured(c) || c.ready !== false) continue;",
        "if (true) continue;")
    names = [g["name"] for g in render(SCENARIO, broken)["groups"]]
    assert "Figma" not in names, "the harness cannot see a connector vanish"


# ── provenance ────────────────────────────────────────────────────────────
def test_the_render_path_does_not_throw():
    r = render(SCENARIO)
    assert r["ok"], r.get("error")
    assert r["html"], "the panel rendered nothing at all"


def test_a_row_with_no_source_is_a_builtin():
    """Old rows keep `name` and `description` and nothing else. They predate
    provenance; they are ours."""
    assert "search_brain" in group(render(SCENARIO), "Built in")["tools"]


def test_builtins_are_grouped_together_and_come_first():
    r = render(SCENARIO)
    assert r["groups"][0]["name"] == "Built in", (
        f"the panel opens on {r['groups'][0]['name']!r}, not the skills we ship")
    assert group(r, "Built in")["tools"] == ["search_brain", "remember"]


def test_a_connector_tool_is_attributed_to_that_connector():
    g = group(render(SCENARIO), "Linear")
    assert g["tools"] == ["linear_issues", "linear_comment"]
    assert g["count"] == "2 skills"


def test_each_connector_gets_its_own_group():
    names = [g["name"] for g in render(SCENARIO)["groups"]]
    assert names.count("Linear") == 1 and names.count("Slack") == 1


def test_one_skill_is_not_one_skills():
    assert group(render(SCENARIO), "Slack")["count"] == "1 skill"


# ── the acronym never reaches the user ────────────────────────────────────
ACRONYM = re.compile(r"\bmcp\b", re.I)


def test_the_protocol_is_never_named_on_screen():
    """`mcp_source.py`: "To the user this is a connector. The acronym never
    reaches the UI, exactly as 'vendor CLI' never reaches the sign-in card."
    The payload says "mcp"; the screen must not."""
    html = render(SCENARIO)["html"]
    assert not ACRONYM.search(html), (
        f"the protocol's acronym reached the screen:\n"
        f"{html[max(0, ACRONYM.search(html).start() - 120):][:300]}")


def test_a_connector_that_did_not_name_itself_is_still_not_named_after_it():
    """A row can arrive with a source and no label. Vague is survivable; the
    acronym is not."""
    r = render({"tools": [{"name": "do_thing", "description": "", "source": "mcp"}],
                "connectors": []})
    assert not ACRONYM.search(r["html"]), r["html"]
    assert r["groups"][0]["name"] != "Built in", (
        "a connector's tool was passed off as one of ours")
    assert r["groups"][0]["tools"] == ["do_thing"]


# ── a connector that cannot work says so, where the user is looking ───────
def test_a_configured_but_unreachable_connector_is_not_silently_absent():
    g = group(render(SCENARIO), "Figma")
    assert g["down"], "Figma rendered as if it were fine"
    assert g["count"] == "unavailable"


def test_it_says_why_in_the_panel_the_user_is_in():
    why = group(render(SCENARIO), "Figma")["why"]
    assert why and "signed in" in why, f"no reason shown: {why!r}"


def test_the_reason_is_never_an_empty_list():
    """The whole failure mode: zero tools, so without this there is nothing on
    screen to explain where the connector went."""
    g = group(render(SCENARIO), "Figma")
    assert g["tools"] == []
    assert g["why"], "a connector with no tools and no reason is just missing"


def test_an_unreachable_connector_that_does_have_tools_still_says_so():
    scenario = {
        "tools": [{"name": "linear_issues", "description": "List issues.",
                   "source": "mcp", "connector": "Linear"}],
        "connectors": [{"name": "mcp:linear", "label": "Linear", "ready": False,
                        "mcp": True, "custom": False,
                        "reason": "Linear took too long to answer and was stopped."}],
    }
    g = group(render(scenario), "Linear")
    assert g["down"] and g["why"], "tools listed as if they could run"
    assert g["tools"] == ["linear_issues"], "the skills were hidden instead of dimmed"


def test_a_connector_we_ship_that_was_never_set_up_does_not_clutter_this_panel():
    """Gmail is not configured-and-broken, it is simply not set up — and the
    Sources panel already says that, in its own words."""
    assert "Gmail" not in [g["name"] for g in render(SCENARIO)["groups"]]


def test_a_healthy_connector_is_not_accused_of_anything():
    assert not group(render(SCENARIO), "Linear")["down"]


# ── the control has to work, and work without a mouse ─────────────────────
def test_the_way_out_is_a_real_button():
    """Enter and Space work on a <button> because it is a button. A div with an
    onclick is mouse-only, and the rail already paid for that lesson."""
    assert group(render(SCENARIO), "Figma")["fixIsButton"], (
        "the fix affordance is not a <button type='button'>")


def test_every_button_drawn_is_wired_to_something():
    r = render(SCENARIO)
    assert r["drawn"] == 1, f"expected one way out, drew {r['drawn']}"
    assert r["wired"] == r["drawn"], (
        "a button was drawn and left inert — never show a control that cannot work")


def test_pressing_it_takes_the_user_where_the_connector_lives():
    assert render(SCENARIO)["drawers"] == ["sources"], (
        "the button did not open the panel that can actually fix this")


# ── no id chains ──────────────────────────────────────────────────────────
def test_connectors_nobody_hardcoded_behave_identically():
    """Every `providerId === "x"` chain is a latent bug for the provider that is
    not in it. Rename everything to something no branch could know and the
    behaviour must not move."""
    scenario = {
        "tools": [{"name": "zzz_query", "description": "Query it.",
                   "source": "zzz-transport", "connector": "Zylophone"}],
        "connectors": [
            {"name": "zzz:1", "label": "Zylophone", "ready": True, "mcp": True,
             "custom": False, "reason": ""},
            {"name": "zzz:2", "label": "Quagga", "ready": False, "custom": True,
             "reason": "Quagga could not be started — reinstall it from Connectors."},
        ],
    }
    r = render(scenario)
    assert group(r, "Zylophone")["tools"] == ["zzz_query"], (
        "an unknown connector's tools were not attributed to it")
    assert group(r, "Quagga")["down"], "an unknown connector's failure was not reported"
    assert not ACRONYM.search(r["html"])


def test_a_custom_app_the_user_built_counts_as_configured():
    """`custom` rows come from the user's own form, `mcp` rows from a server
    they chose. Both are things they set up, so both can be broken."""
    scenario = {"tools": [], "connectors": [
        {"name": "custom:7", "label": "My API", "ready": False, "custom": True,
         "reason": "My API couldn't reach its service. Check your connection."}]}
    assert group(render(scenario), "My API")["why"]


# ── a connector's own text is not ours ────────────────────────────────────
PAYLOADS = ['<img src=x onerror=alert(1)>', "<script>alert(1)</script>",
            "'><svg/onload=alert(1)>"]
OWN_TAGS = {"div", "span", "p", "button"}
TAG = re.compile(r"<\s*/?\s*([a-zA-Z][\w-]*)")


@pytest.mark.parametrize("payload", PAYLOADS)
def test_a_connectors_own_text_cannot_put_markup_in_the_page(payload):
    """Tool names, descriptions and the connector's label are written by
    whoever wrote the connector — a third party the user added, not us."""
    scenario = {
        "tools": [{"name": payload, "description": payload,
                   "source": "mcp", "connector": payload}],
        "connectors": [{"name": "mcp:x", "label": payload, "ready": False,
                        "mcp": True, "custom": False, "reason": payload}],
    }
    html = render(scenario)["html"]
    for name in TAG.findall(html):
        assert name.lower() in OWN_TAGS, (
            f"a live <{name}> from connector-written text reached innerHTML:\n{html[:400]}")
    assert not re.search(r'"\s+on\w+\s*=', html), f"event handler injected:\n{html[:400]}"


# ── nothing at all ────────────────────────────────────────────────────────
def test_no_tools_and_no_connectors_still_says_something():
    assert render({"tools": [], "connectors": []})["empty"]
