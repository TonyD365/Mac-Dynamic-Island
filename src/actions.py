"""Quick actions behind the island's action buttons."""
import ctypes
import os
import subprocess
import threading

from AppKit import NSColorSampler, NSColorSpace, NSPasteboard, NSPasteboardTypeString, NSUserDefaults


def _osascript(script, on_result=None):
    def run():
        try:
            out = subprocess.run(["osascript", "-e", script], capture_output=True, encoding="utf-8", errors="replace", timeout=20).stdout
        except Exception:
            return
        if on_result:
            on_result(out.strip())
    threading.Thread(target=run, daemon=True).start()


class Actions:
    def __init__(self):
        self._caffeinate = None

    def is_dark(self):
        return NSUserDefaults.standardUserDefaults().stringForKey_("AppleInterfaceStyle") == "Dark"

    def toggle_dark(self):
        _osascript('tell application "System Events" to tell appearance preferences '
                   'to set dark mode to not dark mode')

    def is_awake(self):
        return self._caffeinate is not None and self._caffeinate.poll() is None

    def toggle_awake(self):
        if self.is_awake():
            self._caffeinate.terminate()
            self._caffeinate = None
        else:   # -w: caffeinate exits by itself when the island quits
            self._caffeinate = subprocess.Popen(["caffeinate", "-di", "-w", str(os.getpid())])

    def sleep_display(self):
        subprocess.Popen(["pmset", "displaysleepnow"])

    def lock_screen(self):
        try:
            login = ctypes.CDLL("/System/Library/PrivateFrameworks/login.framework/Versions/Current/login")
            login.SACLockScreenImmediate()
        except (OSError, AttributeError):
            self.sleep_display()

    def screenshot(self):
        """Drag out an area; the picture goes to the clipboard."""
        subprocess.Popen(["screencapture", "-i", "-c"])

    def open_app(self, name):
        subprocess.Popen(["open", "-a", name])

    def open_downloads(self):
        subprocess.Popen(["open", os.path.expanduser("~/Downloads")])

    def pick_color(self, done):
        """Show the system eyedropper; copies the picked colour as #RRGGBB and calls done(hex)."""
        def picked(color):
            rgb = color.colorUsingColorSpace_(NSColorSpace.sRGBColorSpace()) if color is not None else None
            if rgb is None:
                return
            text = "#%02X%02X%02X" % tuple(round(c * 255) for c in (
                rgb.redComponent(), rgb.greenComponent(), rgb.blueComponent()))
            board = NSPasteboard.generalPasteboard()
            board.clearContents()
            board.setString_forType_(text, NSPasteboardTypeString)
            done(text)
        self._sampler = NSColorSampler.alloc().init()     # kept alive until the handler runs
        self._sampler.showSamplerWithSelectionHandler_(picked)
