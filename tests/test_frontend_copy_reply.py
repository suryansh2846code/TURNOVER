"""A reply can be copied, and the conversation can be selected.

Two halves of the same complaint. Selecting text worked — nothing in the
stylesheet disabled it in the conversation — but **⌘C did nothing**, because
macOS delivers the clipboard shortcuts through the Edit menu's key
equivalents and pywebview builds no menu bar at all. Selection without a way
to copy it is the worst of both: it looks like it worked.

So: a real Edit menu with the standard AppKit selectors, and a Copy button on
each reply for the common case of wanting the whole thing.

`user-select: text` is asserted on the conversation deliberately. It is the
default, so the rule looks redundant — but this app paints `user-select: none`
on a lot of chrome, and losing it here to a stray rule would be silent.
"""
import json
import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
WEB = ROOT / "chitragupta/web"
CSS = (WEB / "styles.css").read_text()


# ── the button ────────────────────────────────────────────────────────────
@pytest.fixture(scope="module")
def rendered() -> dict:
    """Run addMsg for an assistant turn and report what it built."""
    harness = ROOT / "tests/js/copy_reply.mjs"
    proc = subprocess.run(
        ["node", str(harness), str(WEB / "app.js")],
        input=json.dumps({"text": "Line one.\n\n- a bullet\n- another"}),
        capture_output=True, text=True, timeout=60,
    )
    assert proc.returncode == 0, proc.stderr[-2000:]
    return json.loads(proc.stdout)


def test_every_reply_offers_a_copy_button(rendered):
    assert 'class="msg-copy"' in rendered["html"], rendered["html"][:200]


def test_the_button_has_a_label_a_screen_reader_can_use(rendered):
    assert 'aria-label="Copy reply"' in rendered["html"]


def test_it_copies_the_markdown_not_the_rendered_text(rendered):
    """Pasting a reply into a note should keep its lists and its code.
    innerText would flatten all of it."""
    assert rendered["copied"] == "Line one.\n\n- a bullet\n- another", rendered["copied"]


def test_the_button_confirms_on_itself(rendered):
    """A toast says "something happened"; the button says "this happened"."""
    assert "Copied" in rendered["afterClick"]


def test_a_user_turn_gets_no_copy_button(rendered):
    """You typed it. Offering to copy it back is noise."""
    assert 'class="msg-copy"' not in rendered["userHtml"]


# ── selection ─────────────────────────────────────────────────────────────
def test_the_conversation_is_selectable_on_purpose():
    rule = CSS.split(".messages, .msg, .msg .a-body", 1)
    assert len(rule) > 1, "the explicit user-select rule for the conversation is gone"
    assert "user-select: text" in rule[1].split("}", 1)[0]


def test_nothing_disables_selection_on_the_conversation():
    """`user-select: none` belongs on chrome — pills, chips, badges — never on
    a message."""
    for block in re.findall(r"([^{}]+)\{([^}]*user-select:\s*none[^}]*)\}", CSS):
        selector = block[0].strip().splitlines()[-1]
        assert ".msg" not in selector and ".messages" not in selector, selector


# ── the shortcut that never worked ────────────────────────────────────────
def test_the_app_installs_an_edit_menu():
    """Built with AppKit, not webview.menu.MenuAction: that takes a Python
    callback and no key equivalent, so it cannot bind ⌘C at all."""
    import AppKit

    from chitragupta.desktop import _install_edit_menu_now

    app = AppKit.NSApplication.sharedApplication()
    app.setMainMenu_(AppKit.NSMenu.alloc().initWithTitle_("MainMenu"))
    _install_edit_menu_now()

    main = app.mainMenu()
    edits = [main.itemAtIndex_(i) for i in range(main.numberOfItems())
             if main.itemAtIndex_(i).title() == "Edit"]
    assert len(edits) == 1
    menu = edits[0].submenu()
    found = {}
    for i in range(menu.numberOfItems()):
        it = menu.itemAtIndex_(i)
        if not it.isSeparatorItem():
            found[it.title()] = (str(it.action()), it.keyEquivalent())

    assert found["Copy"] == ("copy:", "c"), found.get("Copy")
    assert found["Paste"] == ("paste:", "v"), found.get("Paste")
    assert found["Select All"] == ("selectAll:", "a"), found.get("Select All")


def test_installing_it_twice_does_not_make_two_menus():
    """It is called once per launch today, but a second Edit menu in the bar
    is the kind of thing nobody notices until a user screenshots it."""
    import AppKit

    from chitragupta.desktop import _install_edit_menu_now

    app = AppKit.NSApplication.sharedApplication()
    app.setMainMenu_(AppKit.NSMenu.alloc().initWithTitle_("MainMenu"))
    _install_edit_menu_now()
    _install_edit_menu_now()
    main = app.mainMenu()
    assert sum(1 for i in range(main.numberOfItems())
               if main.itemAtIndex_(i).title() == "Edit") == 1
