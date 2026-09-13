"""The floating sign-in card must behave like a macOS floating panel.

The card exists for the moments Lodestone is NOT the active app: the user is in
a browser authorising. It went missing there — not behind the browser, but on
another Space. A window with the default collection behaviour belongs to the
Space it was created on, and a full-screen browser gets a Space of its own.

These assert the AppKit calls the raise path makes, and just as importantly the
ones it must not: activating the app would pull keyboard focus out of the
browser mid-sign-in, every time the card updated.
"""
import pytest

AppKit = pytest.importorskip("AppKit", reason="macOS-only window behaviour")

from lodestone import hud


class FakeWindow:
    """Records what was asked of the NSWindow."""

    def __init__(self):
        self.calls = []

    def __getattr__(self, name):
        def record(*args):
            self.calls.append((name, args))
        return record

    def named(self, name):
        return [c for c in self.calls if c[0] == name]


@pytest.fixture
def raised():
    win = FakeWindow()
    hud._raise_now(win, 420, 290)
    return win


def test_it_floats_above_other_applications(raised):
    level = raised.named("setLevel_")
    assert level, "never set a window level"
    assert level[0][1][0] == AppKit.NSFloatingWindowLevel


def test_it_does_not_claim_the_menu_bar(raised):
    """NSStatusWindowLevel — what pywebview's on_top gives us — covers system UI
    too. A sign-in card is a floating panel, not an overlay."""
    assert raised.named("setLevel_")[0][1][0] < AppKit.NSStatusWindowLevel


def test_it_follows_the_user_to_other_spaces(raised):
    """The actual bug: the card stayed on the Space it was created on."""
    behaviour = raised.named("setCollectionBehavior_")
    assert behaviour, "never set a collection behaviour"
    mask = behaviour[0][1][0]
    assert mask & AppKit.NSWindowCollectionBehaviorCanJoinAllSpaces
    assert mask & AppKit.NSWindowCollectionBehaviorFullScreenAuxiliary


def test_it_is_not_pinned_to_the_screen(raised):
    """Stationary is for wallpaper-like overlays and is redundant once the
    window joins every Space — applying every flag that sounds relevant is how
    a floating panel starts behaving like a screen-saver overlay."""
    mask = raised.named("setCollectionBehavior_")[0][1][0]
    assert not mask & AppKit.NSWindowCollectionBehaviorStationary


def test_it_stays_visible_when_lodestone_is_not_active(raised):
    hides = raised.named("setHidesOnDeactivate_")
    assert hides and hides[0][1][0] is False


def test_showing_it_never_steals_focus(raised):
    """makeKeyAndOrderFront_ + activateIgnoringOtherApps_ is what the pywebview
    backend's show() does, and it pulls the user out of the browser they are
    signing in to."""
    assert not raised.named("makeKeyAndOrderFront_"), "made the card the key window"
    assert not raised.named("activateIgnoringOtherApps_"), "activated the whole app"
    assert raised.named("orderFrontRegardless"), "never put the card on screen"


def test_it_is_positioned_inside_the_visible_area():
    """visibleFrame, not frame: the menu bar and Dock are not ours to cover."""
    width, height = 420, 290
    point = hud._visible_corner(width, height)
    screens = [s.visibleFrame() for s in AppKit.NSScreen.screens()]
    assert any(
        area.origin.x <= point.x
        and point.x + width <= area.origin.x + area.size.width
        and area.origin.y <= point.y
        and point.y + height <= area.origin.y + area.size.height
        for area in screens
    ), f"card at {point.x},{point.y} is not inside any screen's visible frame"


def test_there_is_never_a_second_card():
    """The window is built once and reloaded; nothing here creates another."""
    import inspect

    source = inspect.getsource(hud)
    assert source.count("create_window(") == 1, "more than one window is created"


# ── the card's appearance ────────────────────────────────────────────────
import pathlib
from html.parser import HTMLParser

CARD_HTML = pathlib.Path(__file__).resolve().parents[1] / "lodestone/web/signin_hud.html"


def test_the_window_has_no_opaque_backing():
    """An opaque window behind a rounded card reads as a pale border around it,
    which is exactly how it shipped."""
    captured = {}

    def fake_create_window(*args, **kwargs):
        captured.update(kwargs)
        return object()

    previous = hud._hud_window
    try:
        hud.prepare(fake_create_window)
    finally:
        hud._hud_window = previous
    assert captured.get("transparent") is True, "window would paint an opaque rectangle"
    assert captured.get("frameless") is True


def test_the_native_shadow_is_restored(raised):
    """pywebview switches the shadow off for transparent windows; with the card
    supplying the opaque shape, macOS can draw a real one around it."""
    shadow = raised.named("setHasShadow_")
    assert shadow and shadow[0][1][0] is True
    assert raised.named("invalidateShadow"), "a cached shadow keeps the old shape"


class _Children(HTMLParser):
    """Immediate children of the element carrying class `card`."""

    def __init__(self):
        super().__init__()
        self.depth = None
        self.level = 0
        self.children = []

    def handle_starttag(self, tag, attrs):
        classes = dict(attrs).get("class", "")
        self.level += 1
        if self.depth is None and "card" in classes.split():
            self.depth = self.level
        elif self.depth is not None and self.level == self.depth + 1:
            self.children.append((tag, classes, dict(attrs).get("id", "")))

    def handle_endtag(self, tag):
        self.level -= 1


def test_every_block_shares_the_cards_padding():
    """The title used to sit in a column beside the icon, so it started further
    in than the body text under it. Being siblings inside the card is what makes
    them line up — one padding value, one left edge, one right edge."""
    parser = _Children()
    parser.feed(CARD_HTML.read_text())
    tags = [t for t, _, _ in parser.children]
    assert "h1" in tags, "the title is not a direct child of the card"
    ids = [i for _, _, i in parser.children]
    for expected in ("title", "body", "action", "cancel"):
        assert expected in ids, f"#{expected} is nested instead of sharing the padding"


def test_one_padding_value_governs_every_edge():
    css = CARD_HTML.read_text()
    assert "padding: var(--pad)" in css, "the card does not use the shared padding"
    assert "top: var(--pad); right: var(--pad)" in css, (
        "the close button is inset by hand and will drift from the card padding")


# ── the window tracks the card's height ──────────────────────────────────
def test_resizing_keeps_the_top_edge_anchored():
    """The card is pinned to the top-right corner, so it has to grow downward.
    Cocoa's origin is the BOTTOM-left, so resizing naively moves the top edge and
    the card creeps up the screen every time the copy changes."""
    win = FakeWindow()
    win.frame = lambda: AppKit.NSMakeRect(1000, 500, 348, 250)   # bottom-left origin
    hud._resize_now(win, 219)

    call = win.named("setFrame_display_")
    assert call, "never resized"
    rect = call[0][1][0]
    assert round(rect.size.height) == 219
    assert round(rect.size.width) == 348, "width must not change"
    assert round(rect.origin.y + rect.size.height) == 750, "top edge moved"


def test_resizing_refreshes_the_shadow():
    """The shadow is cached from the old shape; a taller card keeps the old one."""
    win = FakeWindow()
    win.frame = lambda: AppKit.NSMakeRect(0, 0, 348, 250)
    hud._resize_now(win, 200)
    assert win.named("invalidateShadow")


def test_an_unchanged_height_is_left_alone():
    """The page re-measures on every state change; resizing to the height it
    already has would churn the window for nothing."""
    win = FakeWindow()
    win.frame = lambda: AppKit.NSMakeRect(0, 0, 348, 219)
    hud._resize_now(win, 219)
    assert not win.named("setFrame_display_")


def test_fit_is_harmless_without_a_window():
    """`lodestone serve` has no Cocoa window; the page still calls fit()."""
    previous = hud._hud_window
    hud._hud_window = None
    try:
        assert hud._Bridge().fit(220) is False
    finally:
        hud._hud_window = previous


def test_the_card_does_not_pad_itself_to_the_window():
    """`margin-top: auto` shoved the button to the bottom of a fixed-height
    window, leaving a hole under the text whenever the copy was short."""
    css = CARD_HTML.read_text()
    assert "margin-top: auto" not in css, "the button is spring-loaded again"
    assert "align-items: flex-start" in css, "the card stretches to the window"
    assert "ResizeObserver" in css, "nothing re-fits the window when the copy changes"
