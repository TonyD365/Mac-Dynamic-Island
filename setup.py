"""Build the universal (arm64 + x86_64) app:  .venv/bin/python setup.py py2app"""
from setuptools import setup

from version import VERSION

setup(
    name="Dynamic Island",
    version=VERSION,
    app=["main.py"],
    options={"py2app": {
        "arch": "universal2",
        "iconfile": "icon.icns",              # drawn by make_icon.py
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
            "NSAppleEventsUsageDescription":
                "Dynamic Island controls music playback, switches Dark Mode, and checks the current "
                "browser page while a focus mode that blocks websites is running.",
        },
    }},
)
