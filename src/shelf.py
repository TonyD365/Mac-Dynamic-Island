"""The Shelf: files dragged onto the island are kept here until they are dragged out again.

Only the files' locations are remembered. Nothing is copied or moved until you drag an item out
and drop it somewhere, and then it is the destination that decides what happens, exactly as when
dragging the file itself.
"""
import os
import subprocess

import objc
from AppKit import (
    NSColor, NSDraggingItem, NSFont, NSImageView, NSMakeRect, NSTextField, NSURL, NSView, NSWorkspace,
)

ROW_HEIGHT = 30.0
_ANY_OPERATION = 1 | 2 | 4 | 16         # copy, link, generic, move: the destination picks


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


class ShelfRow(NSView):
    """One file on the shelf: click it to show it in Finder, drag it to take it out."""

    @objc.python_method
    def setup(self, path, owner, width):
        self.path, self.owner, self.dragged = path, owner, False
        self.setFrame_(NSMakeRect(0, 0, width, ROW_HEIGHT))
        icon = NSImageView.alloc().initWithFrame_(NSMakeRect(4, 4, 22, 22))
        icon.setImage_(NSWorkspace.sharedWorkspace().iconForFile_(path))
        name = NSTextField.labelWithString_(os.path.basename(path.rstrip("/")) or path)
        name.setFont_(NSFont.systemFontOfSize_(12.5))
        name.setTextColor_(NSColor.labelColor())
        name.setLineBreakMode_(5)               # truncate in the middle, keeping the extension
        name.setFrame_(NSMakeRect(32, 6, width - 36, 18))
        self.addSubview_(icon)
        self.addSubview_(name)
        self.icon = icon
        return self

    def hitTest_(self, point):                   # the whole row is one target, not its subviews
        f = self.frame()
        inside = (f.origin.x <= point.x <= f.origin.x + f.size.width
                  and f.origin.y <= point.y <= f.origin.y + f.size.height)
        return self if inside else None

    def acceptsFirstMouse_(self, event):
        return True

    def mouseDown_(self, event):
        self.dragged = False

    def mouseDragged_(self, event):
        if self.dragged:
            return
        self.dragged = True
        self.owner.drag_started()
        item = NSDraggingItem.alloc().initWithPasteboardWriter_(NSURL.fileURLWithPath_(self.path))
        item.setDraggingFrame_contents_(NSMakeRect(4, 4, 22, 22), self.icon.image())
        self.beginDraggingSessionWithItems_event_source_([item], event, self)

    def mouseUp_(self, event):
        if not self.dragged:
            reveal(self.path)

    @objc.typedSelector(b"Q@:@q")
    def draggingSession_sourceOperationMaskForDraggingContext_(self, session, context):
        return _ANY_OPERATION

    @objc.typedSelector(b"v@:@{CGPoint=dd}Q")
    def draggingSession_endedAtPoint_operation_(self, session, point, operation):
        self.owner.drag_ended(self.path, operation != 0)
