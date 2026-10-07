"""The About window."""
import os
import subprocess
import time

from AppKit import (
    NSApp, NSBackingStoreBuffered, NSButton, NSColor, NSFont, NSImage, NSImageView, NSMakeRect,
    NSTextAlignmentCenter, NSTextField, NSWindow, NSWindowStyleMaskClosable, NSWindowStyleMaskTitled,
)

from custom_buttons import _Action
from version import VERSION

AUTHOR = "Tony Dong"
HOMEPAGE = "https://github.com/TonyD365/Mac-Dynamic-Island"
TAGLINE = "A Dynamic Island for the Mac's notch."
WIDTH, HEIGHT = 340, 392


def version_text():
    return "Development build" if VERSION == "0.0.0" else "Version %s" % VERSION


def app_icon():
    """The app's own icon: from the bundle when packaged, from assets/ when run from source."""
    source = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets", "icon.png")
    if os.path.exists(source):
        return NSImage.alloc().initWithContentsOfFile_(source)
    return NSApp.applicationIconImage()


class About:
    def __init__(self, check_for_updates):
        self.check_for_updates = check_for_updates
        self.window = None
        self._keep = []

    def bind(self, callback):
        t = _Action.alloc().init()
        t.callback = callback
        self._keep.append(t)
        return t

    def show(self):
        if self.window is None:
            self.build()
            self.window.center()
        NSApp.activateIgnoringOtherApps_(True)
        self.window.makeKeyAndOrderFront_(None)

    def build(self):
        self.window = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(0, 0, WIDTH, HEIGHT), NSWindowStyleMaskTitled | NSWindowStyleMaskClosable,
            NSBackingStoreBuffered, False)
        self.window.setTitle_("About Dynamic Island")
        self.window.setReleasedWhenClosed_(False)
        content = self.window.contentView()

        def text(string, y, height, size, color=None, bold=False, wrap=False):
            label = NSTextField.wrappingLabelWithString_(string) if wrap else NSTextField.labelWithString_(string)
            label.setFont_(NSFont.boldSystemFontOfSize_(size) if bold else NSFont.systemFontOfSize_(size))
            label.setTextColor_(color or NSColor.labelColor())
            label.setAlignment_(NSTextAlignmentCenter)
            label.setFrame_(NSMakeRect(24, y, WIDTH - 48, height))
            content.addSubview_(label)
            return label

        def button(title, y, action):
            b = NSButton.buttonWithTitle_target_action_(title, self.bind(action), "fire:")
            b.setFrame_(NSMakeRect((WIDTH - 200) / 2, y, 200, 32))
            content.addSubview_(b)
            return b

        gray = NSColor.secondaryLabelColor()
        icon = NSImageView.alloc().initWithFrame_(NSMakeRect((WIDTH - 112) / 2, 262, 112, 112))
        icon.setImage_(app_icon())
        content.addSubview_(icon)
        text("Dynamic Island", 228, 28, 21, bold=True)
        text(version_text(), 208, 18, 12, gray)
        text(TAGLINE, 180, 18, 12.5)
        text("Clock, now playing, focus modes, a shelf for files and rings of buttons, around the camera.",
             136, 36, 11.5, gray, wrap=True)
        text("Made by %s" % AUTHOR, 106, 18, 12.5, bold=True)
        text("Written in Python with PyObjC", 88, 16, 11, gray)
        button("Check for Updates", 48, self.check_for_updates)
        button("View on GitHub", 16, lambda: subprocess.Popen(["/usr/bin/open", HOMEPAGE]))
        text("© %s %s" % (time.strftime("%Y"), AUTHOR), 2, 14, 10, gray)
