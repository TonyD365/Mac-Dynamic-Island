"""Build the universal (arm64 + x86_64) app. Run ./build.sh rather than this file directly."""
import sys

from setuptools import setup

sys.path.insert(0, "src")           # the app's modules live in src/
from version import VERSION         # noqa: E402

setup(
    name="Dynamic Island",
    version=VERSION,
    app=["src/main.py"],
    options={"py2app": {
        "arch": "universal2",
        "iconfile": "assets/icon.icns",       # drawn by packaging/make_icon.py
        "excludes": ["tkinter"],              # the island is pure AppKit
        "plist": {
            "CFBundleName": "Dynamic Island",
            "CFBundleDisplayName": "Dynamic Island",
            "CFBundleIdentifier": "com.dynamicisland.app",
            "CFBundleShortVersionString": VERSION,
            "CFBundleVersion": VERSION,
            "LSUIElement": True,                 # no Dock icon
            "LSMinimumSystemVersion": "12.0",
            "NSHighResolutionCapable": True,
            "NSCalendarsUsageDescription":
                "Dynamic Island shows your next calendar event when Calendar Events is switched on.",
            "NSCalendarsFullAccessUsageDescription":
                "Dynamic Island shows your next calendar event when Calendar Events is switched on.",
            "NSAppleEventsUsageDescription":
                "Dynamic Island controls music playback, switches Dark Mode, and checks the current "
                "browser page while a focus mode that blocks websites is running.",
        },
    }},
)
