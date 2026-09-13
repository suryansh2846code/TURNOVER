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
