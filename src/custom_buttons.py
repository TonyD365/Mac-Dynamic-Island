"""User-defined action buttons, and the small window for editing them."""
import os
import subprocess
import uuid

from AppKit import (
    NSApp, NSBackingStoreBuffered, NSBeep, NSBezelBorder, NSBitmapImageRep, NSButton, NSCalibratedRGBColorSpace,
    NSColor, NSCompositingOperationSourceOver, NSFont, NSGraphicsContext, NSImage, NSImageCell, NSMakeRect,
    NSMenuItem, NSObject, NSOpenPanel, NSPopUpButton, NSScrollView, NSTableColumn, NSTableView,
    NSTextAlignmentRight, NSTextField, NSURL, NSWindow, NSWindowStyleMaskClosable, NSWindowStyleMaskTitled,
    NSWorkspace,
)

import settings

# (kind, menu title, hint shown under the target field, can use the file chooser)
KINDS = (
    ("app", "Open App", "An application, e.g. Safari — or press Choose…", True),
    ("file", "Open File or Folder", "Any file or folder — press Choose…", True),
    ("url", "Open Website", "A web address, e.g. github.com", False),
    ("shell", "Run Shell Command", "A command line, run with your shell", False),
)
ICONS = (
    ("star.fill", "Star"), ("app.fill", "App"), ("folder.fill", "Folder"), ("doc.fill", "Document"),
    ("globe", "Globe"), ("terminal.fill", "Terminal"), ("bolt.fill", "Bolt"), ("heart.fill", "Heart"),
    ("paperplane.fill", "Paper Plane"), ("envelope.fill", "Mail"), ("message.fill", "Message"),
    ("music.note", "Music"), ("gamecontroller.fill", "Game"), ("book.fill", "Book"), ("cart.fill", "Cart"),
    ("hammer.fill", "Tools"),
)


# A button can show a picture instead of a symbol: an app's icon or any image file. The picture is
# copied (as a small PNG) into this folder, so the button keeps it even if the original goes away.
PICTURES = os.path.expanduser("~/Library/Application Support/DynamicIsland/Icons")
PICTURE_SIZE = 128
IMAGE_TYPES = ["png", "jpg", "jpeg", "heic", "tiff", "tif", "gif", "bmp", "webp", "icns", "pdf", "svg"]


def load_picture(source):
    """The picture a file stands for: an app's icon, or the image itself. None if it can't be read."""
    if not source or not os.path.exists(source):
        return None
    if source.rstrip("/").endswith(".app"):
        # The real bundle, not a link to it: a link's icon carries an alias arrow.
        return NSWorkspace.sharedWorkspace().iconForFile_(os.path.realpath(source))
    image = NSImage.alloc().initWithContentsOfFile_(source)
    return image if (image is not None and image.isValid()) else None


def save_picture(source):
    """Copy the picture for `source` into the Icons folder as a square PNG. Returns its path, or None."""
    image = load_picture(source)
    if image is None:
        return None
    size = image.size()
    if size.width <= 0 or size.height <= 0:
        return None
    side = PICTURE_SIZE
    rep = NSBitmapImageRep.alloc().initWithBitmapDataPlanes_pixelsWide_pixelsHigh_bitsPerSample_samplesPerPixel_hasAlpha_isPlanar_colorSpaceName_bytesPerRow_bitsPerPixel_(
        None, side, side, 8, 4, True, False, NSCalibratedRGBColorSpace, 0, 0)
    # Fill the square: scale so the shorter side fits, and centre the rest out of view.
    scale = max(side / size.width, side / size.height)
    width, height = size.width * scale, size.height * scale
    NSGraphicsContext.saveGraphicsState()
    NSGraphicsContext.setCurrentContext_(NSGraphicsContext.graphicsContextWithBitmapImageRep_(rep))
    image.drawInRect_fromRect_operation_fraction_(
        NSMakeRect((side - width) / 2, (side - height) / 2, width, height), NSMakeRect(0, 0, 0, 0),
        NSCompositingOperationSourceOver, 1.0)
    NSGraphicsContext.restoreGraphicsState()
    data = rep.representationUsingType_properties_(4, None)        # 4 = PNG
    if data is None:
        return None
    os.makedirs(PICTURES, exist_ok=True)
    path = os.path.join(PICTURES, uuid.uuid4().hex[:12] + ".png")
    return path if data.writeToFile_atomically_(path, True) else None


def picture_of(button):
    """Path of the button's picture if it has one that still exists, else None."""
    path = button.get("image")
    return path if (path and os.path.exists(path)) else None


def button_image(button):
    """What to show for a button in lists: its picture, or its symbol."""
    path = picture_of(button)
    if path:
        return NSImage.alloc().initWithContentsOfFile_(path)
    return NSImage.imageWithSystemSymbolName_accessibilityDescription_(button.get("icon", "star.fill"), None)


def tidy_pictures(buttons, keep=()):
    """Remove pictures in the Icons folder that no button uses any more."""
    used = {b.get("image") for b in buttons} | set(keep)
    try:
        names = os.listdir(PICTURES)
    except OSError:
        return
    for name in names:
        path = os.path.join(PICTURES, name)
        if name.endswith(".png") and path not in used:
            try:
                os.remove(path)
            except OSError:
                pass


def run(button):
    """Carry out a custom button's action."""
    kind, target = button.get("kind"), button.get("target", "")
    if kind == "app":
        subprocess.Popen(["open", "-a", target])
    elif kind == "file":
        subprocess.Popen(["open", os.path.expanduser(target)])
    elif kind == "url":
        subprocess.Popen(["open", target if "://" in target else "https://" + target])
    elif kind == "shell":
        subprocess.Popen(target, shell=True, cwd=os.path.expanduser("~"))


def describe(button):
    title = {k: t for k, t, _, _ in KINDS}.get(button.get("kind"), "Custom")
    target = button.get("target", "")
    if button.get("kind") in ("app", "file"):
        target = os.path.splitext(os.path.basename(target.rstrip("/")))[0] or target
    return "%s  ·  %s" % (title, target)


class _Action(NSObject):
    """Target object that forwards a control's action to a Python callable."""

    def fire_(self, sender):
        self.callback()


class _Table(NSObject):
    """Data source and delegate for the list of custom buttons."""

    def numberOfRowsInTableView_(self, table):
        return len(self.editor.values["custom_buttons"])

    def tableView_objectValueForTableColumn_row_(self, table, column, row):
        button = self.editor.values["custom_buttons"][row]
        key = column.identifier()
        if key == "icon":
            return button_image(button)
        if key == "name":
            return button.get("name", "Untitled")
        return describe(button)

    def tableViewSelectionDidChange_(self, notification):
        self.editor.selection_changed()


class Editor:
    """A window listing every custom button, with + / − / Edit; adding or editing opens a form sheet."""

    def __init__(self):
        self.values = None          # the shared settings dict
        self.on_change = None       # called after every change
        self.window = None
        self.editing = None         # index being edited in the sheet, or None for a new button
        self.form_picture = None    # picture chosen in the sheet (a path in the Icons folder), or None
        self.form_symbol = 0        # the symbol selected before a picture was chosen
        self._targets = []          # controls don't retain their targets

    def bind(self, callback):
        t = _Action.alloc().init()
        t.callback = callback
        self._targets.append(t)
        return t

    def show(self):
        if self.window is None:
            self.build_list()
            self.build_form()
            self.window.center()
        self.table.reloadData()
        self.selection_changed()
        NSApp.activateIgnoringOtherApps_(True)
        self.window.makeKeyAndOrderFront_(None)

    def button(self, parent, title, frame, action):
        b = NSButton.buttonWithTitle_target_action_(title, self.bind(action), "fire:")
        b.setFrame_(NSMakeRect(*frame))
        parent.addSubview_(b)
        return b

    # ---- list window ----

    def build_list(self):
        self.window = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(0, 0, 440, 330), NSWindowStyleMaskTitled | NSWindowStyleMaskClosable,
            NSBackingStoreBuffered, False)
        self.window.setTitle_("Custom Buttons")
        self.window.setReleasedWhenClosed_(False)
        content = self.window.contentView()

        self.table = NSTableView.alloc().initWithFrame_(NSMakeRect(0, 0, 400, 250))
        for key, title, width in (("icon", "", 28), ("name", "Name", 130), ("action", "Action", 220)):
            column = NSTableColumn.alloc().initWithIdentifier_(key)
            column.headerCell().setStringValue_(title)
            column.setWidth_(width)
            column.setEditable_(False)
            if key == "icon":
                column.setDataCell_(NSImageCell.alloc().init())
            self.table.addTableColumn_(column)
        self.table.setRowHeight_(24)
        self.table.setUsesAlternatingRowBackgroundColors_(True)
        self.source = _Table.alloc().init()
        self.source.editor = self
        self.table.setDataSource_(self.source)
        self.table.setDelegate_(self.source)
        self.table.setTarget_(self.bind(self.edit_selected))
        self.table.setDoubleAction_("fire:")

        scroll = NSScrollView.alloc().initWithFrame_(NSMakeRect(20, 60, 400, 250))
        scroll.setDocumentView_(self.table)
        scroll.setHasVerticalScroller_(True)
        scroll.setBorderType_(NSBezelBorder)
        content.addSubview_(scroll)

        self.button(content, "+", (14, 14, 44, 32), self.add)
        self.remove_btn = self.button(content, "−", (56, 14, 44, 32), self.remove_selected)
        self.edit_btn = self.button(content, "Edit…", (104, 14, 80, 32), self.edit_selected)
        done = self.button(content, "Done", (336, 14, 90, 32), self.window.close)
        done.setKeyEquivalent_("\r")

    def selection_changed(self):
        selected = self.table.selectedRow() >= 0
        self.remove_btn.setEnabled_(selected)
        self.edit_btn.setEnabled_(selected)

    def add(self):
        self.open_form(None)

    def edit_selected(self):
        row = self.table.selectedRow()
        if 0 <= row < len(self.values["custom_buttons"]):
            self.open_form(row)

    def remove_selected(self):
        row = self.table.selectedRow()
        if 0 <= row < len(self.values["custom_buttons"]):
            del self.values["custom_buttons"][row]
            self.changed()

    def changed(self):
        tidy_pictures(self.values["custom_buttons"])
        settings.save(self.values)
        self.table.reloadData()
        self.selection_changed()
        if self.on_change:
            self.on_change()

    # ---- form sheet ----

    def build_form(self):
        self.sheet = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(0, 0, 460, 240), NSWindowStyleMaskTitled, NSBackingStoreBuffered, False)
        self.sheet.setReleasedWhenClosed_(False)
        content = self.sheet.contentView()

        def label(text, y):
            l = NSTextField.labelWithString_(text)
            l.setFrame_(NSMakeRect(20, y, 70, 20))
            l.setAlignment_(NSTextAlignmentRight)
            content.addSubview_(l)

        def popup(y, action=None):
            p = NSPopUpButton.alloc().initWithFrame_pullsDown_(NSMakeRect(98, y - 3, 342, 26), False)
            if action:
                p.setTarget_(self.bind(action))
                p.setAction_("fire:")
            content.addSubview_(p)
            return p

        def field(y, width):
            f = NSTextField.alloc().initWithFrame_(NSMakeRect(100, y - 1, width, 22))
            content.addSubview_(f)
            return f

        label("Name", 196)
        self.name = field(196, 338)
        label("Icon", 158)
        # The symbols, then: the chosen picture (hidden until there is one) and the two ways to choose one.
        self.icon = popup(158, self.icon_changed)
        for symbol, title in ICONS:
            self.icon.menu().addItemWithTitle_action_keyEquivalent_(title, None, "")
            self.icon.lastItem().setImage_(NSImage.imageWithSystemSymbolName_accessibilityDescription_(symbol, None))
        self.icon.menu().addItem_(NSMenuItem.separatorItem())
        self.icon.menu().addItemWithTitle_action_keyEquivalent_("Picture", None, "")
        self.picture_item = self.icon.lastItem()
        self.icon.menu().addItemWithTitle_action_keyEquivalent_("Use an App's Icon…", None, "")
        self.icon.menu().addItemWithTitle_action_keyEquivalent_("Use an Image File…", None, "")
        self.picture_index = len(ICONS) + 1         # after the separator
        label("Action", 120)
        self.kind = popup(120, self.kind_changed)
        for _, title, _, _ in KINDS:
            self.kind.menu().addItemWithTitle_action_keyEquivalent_(title, None, "")
        label("Target", 82)
        self.target = field(82, 250)
        self.choose = self.button(content, "Choose…", (354, 76, 90, 32), self.choose_path)
        self.hint = NSTextField.labelWithString_("")
        self.hint.setFrame_(NSMakeRect(100, 56, 340, 16))
        self.hint.setFont_(NSFont.systemFontOfSize_(11))
        self.hint.setTextColor_(NSColor.secondaryLabelColor())
        content.addSubview_(self.hint)

        cancel = self.button(content, "Cancel", (262, 12, 90, 32), self.close_form)
        cancel.setKeyEquivalent_("\x1b")
        save = self.button(content, "Save", (356, 12, 90, 32), self.save)
        save.setKeyEquivalent_("\r")

    def open_form(self, index):
        self.editing = index
        buttons = self.values["custom_buttons"]
        b = buttons[index] if index is not None else {"name": "", "icon": ICONS[0][0], "kind": "app", "target": ""}
        self.name.setStringValue_(b.get("name", ""))
        symbols = [s for s, _ in ICONS]
        self.form_symbol = symbols.index(b["icon"]) if b.get("icon") in symbols else 0
        self.show_picture(picture_of(b))
        kinds = [k for k, _, _, _ in KINDS]
        self.kind.selectItemAtIndex_(kinds.index(b["kind"]) if b.get("kind") in kinds else 0)
        self.target.setStringValue_(b.get("target", ""))
        self.kind_changed()
        self.sheet.makeFirstResponder_(self.name)
        self.window.beginSheet_completionHandler_(self.sheet, None)

    def close_form(self):
        self.window.endSheet_(self.sheet)
        tidy_pictures(self.values["custom_buttons"])        # a picture picked and then not saved

    def show_picture(self, path):
        """Put the icon pop-up in step with the form: the chosen picture if there is one, else the symbol."""
        self.form_picture = path
        self.picture_item.setHidden_(path is None)
        if path is None:
            self.icon.selectItemAtIndex_(self.form_symbol)
            return
        thumb = NSImage.alloc().initWithContentsOfFile_(path)
        if thumb is not None:
            thumb.setSize_((16, 16))
        self.picture_item.setImage_(thumb)
        self.icon.selectItemAtIndex_(self.picture_index)

    def icon_changed(self):
        index = self.icon.indexOfSelectedItem()
        if index < len(ICONS):                      # a symbol
            self.form_symbol = index
            self.show_picture(None)
        elif index == self.picture_index:           # the picture already chosen
            return
        else:
            self.choose_picture(apps=index == self.picture_index + 1)

    def choose_picture(self, apps):
        panel = NSOpenPanel.openPanel()
        if apps:
            panel.setDirectoryURL_(NSURL.fileURLWithPath_("/Applications"))
            panel.setAllowedFileTypes_(["app"])
            panel.setMessage_("Choose the app whose icon the button should show")
        else:
            panel.setAllowedFileTypes_(IMAGE_TYPES)
            panel.setMessage_("Choose a picture for the button")
        stored = None
        if panel.runModal() == 1 and panel.URL() is not None:
            stored = save_picture(panel.URL().path())
            if stored is None:
                NSBeep()                            # not something that can be shown as a picture
        self.show_picture(stored or self.form_picture)      # cancelled or unreadable: leave things as they were

    def kind_changed(self):
        _, _, hint, can_choose = KINDS[self.kind.indexOfSelectedItem()]
        self.hint.setStringValue_(hint)
        self.choose.setEnabled_(can_choose)

    def choose_path(self):
        kind = KINDS[self.kind.indexOfSelectedItem()][0]
        panel = NSOpenPanel.openPanel()
        if kind == "app":
            panel.setDirectoryURL_(NSURL.fileURLWithPath_("/Applications"))
            panel.setAllowedFileTypes_(["app"])
        else:
            panel.setCanChooseDirectories_(True)
        if panel.runModal() != 1 or panel.URL() is None:
            return
        path = panel.URL().path()
        self.target.setStringValue_(path)
        if not self.name.stringValue().strip():
            self.name.setStringValue_(os.path.splitext(os.path.basename(path.rstrip("/")))[0])

    def save(self):
        name = self.name.stringValue().strip()
        target = self.target.stringValue().strip()
        if not name or not target:
            NSBeep()
            return
        entry = {"name": name, "icon": ICONS[self.form_symbol][0],
                 "kind": KINDS[self.kind.indexOfSelectedItem()][0], "target": target}
        if self.form_picture:
            entry["image"] = self.form_picture
        buttons = self.values["custom_buttons"]
        if self.editing is None:
            buttons.append(entry)
        else:
            if buttons[self.editing].get("id"):         # the same button, so it keeps its place in the ring
                entry["id"] = buttons[self.editing]["id"]
            buttons[self.editing] = entry
        self.close_form()
        self.changed()
