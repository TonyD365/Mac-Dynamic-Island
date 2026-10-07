"""Dynamic Island for the MacBook notch. Run: .venv/bin/python main.py"""
import os
import signal
import sys

from AppKit import (
    NSApplication, NSApplicationActivationPolicyAccessory, NSImage, NSMenu, NSMenuItem, NSStatusBar,
    NSVariableStatusItemLength,
)
from PyObjCTools import AppHelper

from custom_buttons import _Action
from island import Island


def dump_diagnostics(island):
    """`kill -USR1 <pid>` writes what the monitors currently see, for troubleshooting."""
    mon = island.monitors
    lines = ["%s = %r" % (k, getattr(mon, k)) for k in
             ("cam", "mic", "batt", "ac", "music", "volume", "muted", "brightness", "bt", "cpu", "mem", "errors")]
    lines += ["locked = %r" % island.locked, "settings = %r" % island.settings,
              "executable = %s" % sys.executable, "PATH = %s" % os.environ.get("PATH")]
    path = os.path.expanduser("~/Library/Application Support/DynamicIsland/diagnostics.txt")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write("\n".join(lines) + "\n")


def main():
    app = NSApplication.sharedApplication()
    app.setActivationPolicy_(NSApplicationActivationPolicyAccessory)   # no Dock icon

    island = Island()
    island.start()

    item = NSStatusBar.systemStatusBar().statusItemWithLength_(NSVariableStatusItemLength)
    icon = NSImage.imageWithSystemSymbolName_accessibilityDescription_("capsule.fill", "Dynamic Island")
    if icon is not None:
        icon.setTemplate_(True)
        item.button().setImage_(icon)
    else:
        item.button().setTitle_("DI")
    menu = NSMenu.alloc().init()
    quit_target = _Action.alloc().init()          # goes through the island so a locked focus can refuse
    quit_target.callback = island.request_quit
    quit_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_("Quit Dynamic Island", "fire:", "q")
    quit_item.setTarget_(quit_target)
    menu.addItem_(quit_item)
    item.setMenu_(menu)

    # No visible menu bar for an accessory app, but text fields still need these for Cmd-X/C/V/A.
    main_menu = NSMenu.alloc().init()
    edit_item = main_menu.addItemWithTitle_action_keyEquivalent_("Edit", None, "")
    edit = NSMenu.alloc().initWithTitle_("Edit")
    for title, action, key in (("Cut", "cut:", "x"), ("Copy", "copy:", "c"), ("Paste", "paste:", "v"),
                               ("Select All", "selectAll:", "a")):
        edit.addItemWithTitle_action_keyEquivalent_(title, action, key)
    edit_item.setSubmenu_(edit)
    app.setMainMenu_(main_menu)

    # Ctrl-C in a terminal: the handler runs on the next timer tick and quits cleanly.
    signal.signal(signal.SIGINT, lambda *_: app.terminate_(None))
    signal.signal(signal.SIGUSR1, lambda *_: dump_diagnostics(island))
    AppHelper.runEventLoop()


if __name__ == "__main__":
    main()
