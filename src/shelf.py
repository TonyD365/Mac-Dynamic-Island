"""The Shelf: files dragged onto the island are kept here until they are dragged out again.

Only the files' locations are remembered. Nothing is copied or moved until you drag an item out
and drop it somewhere, and then it is the destination that decides what happens, exactly as when
dragging the file itself.
"""
import os
import subprocess

from AppKit import NSURL


def add(values, paths):
    """Remember these paths (once each). Returns how many were new."""
    added = 0
    for path in paths:
        path = os.path.abspath(os.path.expanduser(path))
        if os.path.exists(path) and path not in values["shelf"]:
            values["shelf"].append(path)
            added += 1
    return added


def prune(values):
    """Forget files that are no longer where they were. Returns True if any were dropped."""
    kept = [p for p in values["shelf"] if os.path.exists(p)]
    changed = len(kept) != len(values["shelf"])
    values["shelf"][:] = kept
    return changed


def reveal(path):
    subprocess.Popen(["/usr/bin/open", "-R", path])


def paths_from(pasteboard):
    """File paths carried by a drag."""
    urls = pasteboard.readObjectsForClasses_options_([NSURL], {"NSPasteboardURLReadingFileURLsOnly": True}) or []
    return [str(u.path()) for u in urls if u.isFileURL()]
