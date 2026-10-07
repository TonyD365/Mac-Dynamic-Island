"""Locate the MacBook's built-in display and the camera notch on it."""
import os

from AppKit import NSScreen, NSStatusBar
import Quartz

# Macs without a notch have nothing to wrap around, so the island becomes a small pill at the top
# centre of the screen (under the camera in the bezel): clock and battery side by side, with only
# this much space between them, and as tall as the menu bar.
GAP_WITHOUT_NOTCH = 24.0
MENU_BAR_FALLBACK = 24.0


def builtin_screen(screens=None, is_builtin=Quartz.CGDisplayIsBuiltin):
    """Return the built-in NSScreen, or None (e.g. lid closed on external display)."""
    if screens is None:
        screens = NSScreen.screens()
    for s in screens:
        display_id = int(s.deviceDescription()["NSScreenNumber"])
        if is_builtin(display_id):
            return s
    return None


def notch_geometry(screen):
    """Return (center_x, top_y, notch_w, notch_h, has_notch) in global screen points.

    The camera sits in the middle of the notch, i.e. the gap between the two
    auxiliary top areas. Without a notch, fall back to the top-centre of the screen.
    """
    f = screen.frame()
    top = f.origin.y + f.size.height
    cx = f.origin.x + f.size.width / 2
    inset = 0
    if not os.environ.get("DI_FAKE_NO_NOTCH"):      # set to try the no-notch layout on a notched Mac
        try:
            inset = screen.safeAreaInsets().top
            left = screen.auxiliaryTopLeftArea()
            right = screen.auxiliaryTopRightArea()
        except AttributeError:  # macOS < 12
            inset = 0
    if inset > 0 and left.size.width > 0 and right.size.width > 0:
        notch_w = f.size.width - left.size.width - right.size.width
        cx = f.origin.x + left.size.width + notch_w / 2
        return cx, top, notch_w, inset, True
    height = MENU_BAR_FALLBACK if os.environ.get("DI_FAKE_NO_NOTCH") else NSStatusBar.systemStatusBar().thickness()
    return cx, top, GAP_WITHOUT_NOTCH, max(22.0, height or MENU_BAR_FALLBACK), False
