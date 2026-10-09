"""The Shelf: files dragged onto the island are moved here and kept until they are taken out again.

A file put on the Shelf really leaves the place it was in: it is moved into the Shelf's own folder
(inside the app's Application Support folder), each item in a folder of its own so names never
clash. Where it came from is remembered, so it can be put back. Nothing is ever deleted or
overwritten here: taking a file out means dragging it somewhere, or putting it back.
"""
import errno
import os
import shutil
import subprocess
import time
import uuid

from AppKit import NSURL, NSBitmapImageFileTypePNG, NSBitmapImageRep

FOLDER = os.path.expanduser("~/Library/Application Support/DynamicIsland/Shelf")


def _inside(path, folder):
    path, folder = os.path.realpath(path), os.path.realpath(folder)
    return path == folder or path.startswith(folder + os.sep)


def _move(source, target):
    """Move without ever copying something we then fail to remove.

    Within one disk this is a rename: instant, and it either happens or it doesn't. Only when the
    target is on another disk is the item copied and the original removed.
    """
    try:
        os.rename(source, target)
    except OSError as e:
        if e.errno != errno.EXDEV:
            raise
        shutil.move(source, target)


def _free_name(folder, name):
    """A name that is not taken in `folder`: 'report.pdf', then 'report 2.pdf', 'report 3.pdf'..."""
    stem, ext = os.path.splitext(name)
    candidate, n = name, 1
    while os.path.lexists(os.path.join(folder, candidate)):
        n += 1
        candidate = "%s %d%s" % (stem, n, ext)
    return os.path.join(folder, candidate)


def _drop_entry(values, stored):
    if stored in values["shelf"]:
        values["shelf"].remove(stored)
    values["shelf_origins"].pop(stored, None)
    holder = os.path.dirname(stored)
    if _inside(holder, FOLDER) and os.path.realpath(holder) != os.path.realpath(FOLDER):
        try:
            os.rmdir(holder)            # the item's own folder; only goes if it is empty
        except OSError:
            pass


def store(values, paths):
    """Move these files onto the Shelf. Returns (number stored, [(name, reason) for each that was not])."""
    stored, failed = 0, []
    for path in paths:
        path = os.path.abspath(os.path.expanduser(path))
        name = os.path.basename(path.rstrip("/")) or path
        if not os.path.lexists(path):
            failed.append((name, "It is no longer there"))
            continue
        if _inside(path, FOLDER) or _inside(FOLDER, path):
            continue                    # already on the Shelf, or a folder the Shelf itself lives in
        holder = os.path.join(FOLDER, uuid.uuid4().hex[:8])
        target = os.path.join(holder, name)
        try:
            os.makedirs(holder)
            _move(path, target)
        except OSError as e:
            try:
                os.rmdir(holder)
            except OSError:
                pass
            protected = e.errno in (errno.EACCES, errno.EPERM, errno.EROFS)
            failed.append((name, "macOS does not allow moving it" if protected
                           else (e.strerror or "It could not be moved")))
            continue
        values["shelf"].append(target)
        values["shelf_origins"][target] = os.path.dirname(path.rstrip("/"))
        stored += 1
    return stored, failed


def loose_from(pasteboard):
    """What a drag carries when it has no files: ("image", PNG bytes), ("text", str) or None."""
    for kind in ("public.png", "public.tiff"):
        data = pasteboard.dataForType_(kind)
        if data is None or not data.length():
            continue
        if kind != "public.png":
            picture = NSBitmapImageRep.imageRepWithData_(data)
            data = picture.representationUsingType_properties_(NSBitmapImageFileTypePNG, {}) if picture else None
        if data is not None:
            return ("image", bytes(data))
    text = pasteboard.stringForType_("public.utf8-plain-text")
    return ("text", str(text)) if text and str(text).strip() else None


def store_loose(values, item, now=None):
    """Keep dragged text or a dragged picture on the Shelf as a file of its own. Returns what store does."""
    kind, content = item
    stamp = time.strftime("%Y-%m-%d %H.%M.%S", time.localtime(now))
    name = ("Text %s.txt" if kind == "text" else "Image %s.png") % stamp
    holder = os.path.join(FOLDER, uuid.uuid4().hex[:8])
    target = os.path.join(holder, name)
    try:
        os.makedirs(holder)
        with open(target, "wb") as f:
            f.write(content.encode("utf-8") if kind == "text" else content)
    except OSError as e:
        return 0, [(name, e.strerror or "It could not be saved")]
    values["shelf"].append(target)
    values["shelf_origins"][target] = os.path.expanduser("~/Desktop")     # where Put Back sends it
    return 1, []


def put_back(values, stored):
    """Return one item to the folder it came from (the Desktop if that is gone). Returns its new path.

    An item that was only ever a reference (from a version that did not move files) is simply forgotten.
    """
    origin = values["shelf_origins"].get(stored)
    if origin is None or not _inside(stored, FOLDER):
        _drop_entry(values, stored)
        return stored
    if not os.path.lexists(stored):
        _drop_entry(values, stored)
        return None
    if not os.path.isdir(origin):
        origin = os.path.expanduser("~/Desktop")
    target = _free_name(origin, os.path.basename(stored))
    _move(stored, target)
    _drop_entry(values, stored)
    return target


def put_back_all(values, only=None):
    """Put everything back, or just the items in `only`. Returns (number returned, number that could
    not be moved and stay on the Shelf)."""
    done = stuck = 0
    for stored in list(values["shelf"] if only is None else only):
        try:
            if put_back(values, stored) is not None:
                done += 1
        except OSError:
            stuck += 1
    return done, stuck


def prune(values):
    """Forget items that are no longer in the Shelf (dragged out, or removed by hand). True if any went."""
    gone = [p for p in values["shelf"] if not os.path.lexists(p)]
    for stored in gone:
        _drop_entry(values, stored)
    return bool(gone)


def reveal(path):
    subprocess.Popen(["/usr/bin/open", "-R", path])


def paths_from(pasteboard):
    """File paths carried by a drag."""
    urls = pasteboard.readObjectsForClasses_options_([NSURL], {"NSPasteboardURLReadingFileURLsOnly": True}) or []
    return [str(u.path()) for u in urls if u.isFileURL()]
