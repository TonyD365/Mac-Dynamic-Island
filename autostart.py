"""Launch at login, via a per-user LaunchAgent (the layer macOS starts GUI programs from)."""
import os
import plistlib
import sys

from Foundation import NSBundle

LABEL = "com.dynamicisland.app"
PATH = os.path.expanduser("~/Library/LaunchAgents/%s.plist" % LABEL)


def _program():
    bundle = NSBundle.mainBundle()
    if (bundle.bundlePath() or "").endswith(".app") and bundle.bundleIdentifier() != "org.python.python":
        return [bundle.executablePath()]                     # packaged app
    main = os.path.join(os.path.dirname(os.path.abspath(__file__)), "main.py")
    return [sys.executable, main]                            # running from source


def is_enabled():
    return os.path.exists(PATH)


def set_enabled(on):
    if not on:
        try:
            os.remove(PATH)
        except OSError:
            pass
        return
    os.makedirs(os.path.dirname(PATH), exist_ok=True)
    with open(PATH, "wb") as f:
        plistlib.dump({
            "Label": LABEL,
            "ProgramArguments": _program(),
            "RunAtLoad": True,
            "LimitLoadToSessionType": "Aqua",    # only inside a logged-in desktop session
            "ProcessType": "Interactive",
        }, f)
