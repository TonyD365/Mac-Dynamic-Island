"""The Focus Modes window: a list of modes with + / − / Edit, and a sheet for editing one."""
import os

from AppKit import (
    NSApp, NSBackingStoreBuffered, NSBeep, NSBezelBorder, NSBundle, NSButton, NSColor, NSFont, NSMakeRect,
    NSObject, NSOpenPanel, NSPopUpButton, NSScrollView, NSTableColumn, NSTableView, NSTextAlignmentRight,
    NSTextField, NSURL, NSWindow, NSWindowStyleMaskClosable, NSWindowStyleMaskTitled,
)

import focus
import settings
from custom_buttons import _Action

DURATIONS = (5, 10, 15, 20, 25, 30, 45, 60, 90, 120, 180)
RULES = ((focus.BLACKLIST, "Blacklist — block the apps and websites below"),
         (focus.WHITELIST, "Whitelist — block everything except the ones below"))


class _Rows(NSObject):
    """Table data source backed by a Python callable returning rows of column values."""

    def numberOfRowsInTableView_(self, table):
        return len(self.rows())

    def tableView_objectValueForTableColumn_row_(self, table, column, row):
        return self.rows()[row][int(column.identifier())]

    def tableViewSelectionDidChange_(self, notification):
        self.changed()


class Editor:
    def __init__(self):
        self.values = None          # the shared settings dict
        self.on_change = None
        self.window = None
        self.editing = None         # index being edited, or None for a new mode
        self.form_apps = []         # apps of the mode in the sheet
        self._keep = []

    def bind(self, callback):
        t = _Action.alloc().init()
        t.callback = callback
        self._keep.append(t)
        return t

    def modes(self):
        return self.values["focus_modes"]

    def show(self):
        if self.window is None:
            self.build_list()
            self.build_form()
            self.window.center()
        self.table.reloadData()
        self.selection_changed()
        NSApp.activateIgnoringOtherApps_(True)
        self.window.makeKeyAndOrderFront_(None)

    # ---- helpers ----

    def button(self, parent, title, frame, action):
        b = NSButton.buttonWithTitle_target_action_(title, self.bind(action), "fire:")
        b.setFrame_(NSMakeRect(*frame))
        parent.addSubview_(b)
        return b

    def table_in(self, parent, frame, columns, rows, changed, double=None):
        table = NSTableView.alloc().initWithFrame_(NSMakeRect(0, 0, frame[2], frame[3]))
        for i, (title, width) in enumerate(columns):
            column = NSTableColumn.alloc().initWithIdentifier_(str(i))
            column.headerCell().setStringValue_(title)
            column.setWidth_(width)
            column.setEditable_(False)
            table.addTableColumn_(column)
        if not any(title for title, _ in columns):
            table.setHeaderView_(None)
        table.setRowHeight_(22)
        table.setUsesAlternatingRowBackgroundColors_(True)
        source = _Rows.alloc().init()
        source.rows, source.changed = rows, changed
        self._keep.append(source)
        table.setDataSource_(source)
        table.setDelegate_(source)
        if double:
            table.setTarget_(self.bind(double))
            table.setDoubleAction_("fire:")
        scroll = NSScrollView.alloc().initWithFrame_(NSMakeRect(*frame))
        scroll.setDocumentView_(table)
        scroll.setHasVerticalScroller_(True)
        scroll.setBorderType_(NSBezelBorder)
        parent.addSubview_(scroll)
        return table

    # ---- list window ----

    def build_list(self):
        self.window = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(0, 0, 480, 330), NSWindowStyleMaskTitled | NSWindowStyleMaskClosable,
            NSBackingStoreBuffered, False)
        self.window.setTitle_("Focus Modes")
        self.window.setReleasedWhenClosed_(False)
        content = self.window.contentView()
        self.table = self.table_in(
            content, (20, 60, 440, 250), (("Name", 120), ("Length", 60), ("Blocking", 240)),
            lambda: [(m.get("name", "Untitled"), "%d min" % m.get("minutes", 25), self.rule_text(m))
                     for m in self.modes()],
            self.selection_changed, self.edit_selected)
        self.button(content, "+", (14, 14, 44, 32), lambda: self.open_form(None))
        self.remove_btn = self.button(content, "−", (56, 14, 44, 32), self.remove_selected)
        self.edit_btn = self.button(content, "Edit…", (104, 14, 80, 32), self.edit_selected)
        done = self.button(content, "Done", (376, 14, 90, 32), self.window.close)
        done.setKeyEquivalent_("\r")

    @staticmethod
    def rule_text(mode):
        apps, sites = len(mode.get("apps", [])), len(mode.get("sites", []))
        if mode.get("block") == focus.WHITELIST:
            text = "Whitelist  ·  %d apps, %d sites" % (apps, sites)
        elif not apps and not sites:
            text = "Nothing blocked"
        else:
            text = "Blacklist  ·  %d apps, %d sites" % (apps, sites)
        return text if mode.get("allow_stop", True) else text + "  ·  locked"

    def selection_changed(self):
        selected = self.table.selectedRow() >= 0
        self.remove_btn.setEnabled_(selected and len(self.modes()) > 1)     # always keep one mode
        self.edit_btn.setEnabled_(selected)

    def edit_selected(self):
        row = self.table.selectedRow()
        if 0 <= row < len(self.modes()):
            self.open_form(row)

    def remove_selected(self):
        row = self.table.selectedRow()
        if 0 <= row < len(self.modes()) and len(self.modes()) > 1:
            del self.modes()[row]
            self.changed()

    def changed(self):
        settings.save(self.values)
        self.table.reloadData()
        self.selection_changed()
        if self.on_change:
            self.on_change()

    # ---- form sheet ----

    def build_form(self):
        self.sheet = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(0, 0, 500, 550), NSWindowStyleMaskTitled, NSBackingStoreBuffered, False)
        self.sheet.setReleasedWhenClosed_(False)
        content = self.sheet.contentView()

        def label(text, y):
            l = NSTextField.labelWithString_(text)
            l.setFrame_(NSMakeRect(16, y, 76, 20))
            l.setAlignment_(NSTextAlignmentRight)
            content.addSubview_(l)

        def popup(y, titles):
            p = NSPopUpButton.alloc().initWithFrame_pullsDown_(NSMakeRect(98, y - 3, 384, 26), False)
            for title in titles:
                p.menu().addItemWithTitle_action_keyEquivalent_(title, None, "")
            content.addSubview_(p)
            return p

        def note(text, y):
            n = NSTextField.labelWithString_(text)
            n.setFrame_(NSMakeRect(100, y, 384, 16))
            n.setFont_(NSFont.systemFontOfSize_(11))
            n.setTextColor_(NSColor.secondaryLabelColor())
            content.addSubview_(n)

        label("Name", 444)
        self.name = NSTextField.alloc().initWithFrame_(NSMakeRect(100, 443, 380, 22))
        content.addSubview_(self.name)
        label("Default", 408)
        self.length = popup(408, ["%d minutes" % m for m in DURATIONS])
        label("Blocking", 372)
        self.rule = popup(372, [title for _, title in RULES])

        self.allow_stop = NSButton.checkboxWithTitle_target_action_(
            "Allow stopping this focus before the time is up", None, None)
        self.allow_stop.setFrame_(NSMakeRect(98, 336, 384, 20))
        content.addSubview_(self.allow_stop)

        label("Apps", 300)
        self.apps_table = self.table_in(content, (100, 178, 300, 142), (("", 280),),
                                        lambda: [(a.get("name", a.get("id", "?")),) for a in self.form_apps],
                                        self.app_selection_changed)
        self.button(content, "Add…", (404, 290, 82, 32), self.add_apps)
        self.app_remove = self.button(content, "Remove", (404, 258, 82, 32), self.remove_app)

        label("Websites", 146)
        self.sites = NSTextField.alloc().initWithFrame_(NSMakeRect(100, 104, 380, 62))
        self.sites.cell().setWraps_(True)
        self.sites.cell().setScrollable_(False)
        content.addSubview_(self.sites)
        note("Separate with commas, e.g. youtube.com, bilibili.com", 84)
        note("Safari, Chrome, Edge, Brave and Arc. The island itself is never blocked.", 62)

        # Everything above moves up to make room for the "start by itself" rows.
        for view in list(content.subviews()):
            origin = view.frame().origin
            view.setFrameOrigin_((origin.x, origin.y + 64))

        def hint(text, x, y):
            n = NSTextField.labelWithString_(text)
            n.setFrame_(NSMakeRect(x, y, 484 - x, 16))
            n.setFont_(NSFont.systemFontOfSize_(11))
            n.setTextColor_(NSColor.secondaryLabelColor())
            content.addSubview_(n)

        label("Start at", 92)
        self.auto_at = NSTextField.alloc().initWithFrame_(NSMakeRect(100, 91, 64, 22))
        self.auto_at.setPlaceholderString_("09:00")
        content.addSubview_(self.auto_at)
        hint("Every day at this time (24-hour). Empty: never.", 172, 94)
        label("With app", 60)
        self.auto_app = NSTextField.alloc().initWithFrame_(NSMakeRect(100, 59, 150, 22))
        self.auto_app.setPlaceholderString_("Xcode")
        content.addSubview_(self.auto_app)
        hint("Starts when this app opens. Empty: never.", 258, 62)

        cancel = self.button(content, "Cancel", (300, 12, 90, 32), self.close_form)
        cancel.setKeyEquivalent_("\x1b")
        save = self.button(content, "Save", (394, 12, 90, 32), self.save)
        save.setKeyEquivalent_("\r")

    def open_form(self, index):
        self.editing = index
        mode = self.modes()[index] if index is not None else {
            "name": "", "minutes": 25, "block": focus.BLACKLIST, "apps": [], "sites": [], "allow_stop": True}
        self.name.setStringValue_(mode.get("name", ""))
        minutes = mode.get("minutes", 25)
        self.length.selectItemAtIndex_(DURATIONS.index(min(DURATIONS, key=lambda d: abs(d - minutes))))
        self.rule.selectItemAtIndex_(1 if mode.get("block") == focus.WHITELIST else 0)
        self.allow_stop.setState_(1 if mode.get("allow_stop", True) else 0)
        self.form_apps = [dict(a) for a in mode.get("apps", [])]
        self.apps_table.reloadData()
        self.app_selection_changed()
        self.sites.setStringValue_(", ".join(mode.get("sites", [])))
        self.auto_at.setStringValue_(mode.get("auto_at", ""))
        self.auto_app.setStringValue_(mode.get("auto_app", ""))
        self.sheet.makeFirstResponder_(self.name)
        self.window.beginSheet_completionHandler_(self.sheet, None)

    def close_form(self):
        self.window.endSheet_(self.sheet)

    def app_selection_changed(self):
        self.app_remove.setEnabled_(self.apps_table.selectedRow() >= 0)

    def add_apps(self):
        panel = NSOpenPanel.openPanel()
        panel.setDirectoryURL_(NSURL.fileURLWithPath_("/Applications"))
        panel.setAllowedFileTypes_(["app"])
        panel.setAllowsMultipleSelection_(True)
        if panel.runModal() != 1:
            return
        own = NSBundle.mainBundle().bundleIdentifier()
        known = {a.get("id") for a in self.form_apps}
        for url in panel.URLs():
            bundle = NSBundle.bundleWithURL_(url)
            bundle_id = bundle.bundleIdentifier() if bundle else None
            if not bundle_id or bundle_id in known or bundle_id in (own, "com.dynamicisland.app"):
                continue        # the island never goes on a list
            known.add(bundle_id)
            self.form_apps.append({"name": os.path.splitext(os.path.basename(url.path()))[0], "id": bundle_id})
        self.apps_table.reloadData()
        self.app_selection_changed()

    def remove_app(self):
        row = self.apps_table.selectedRow()
        if 0 <= row < len(self.form_apps):
            del self.form_apps[row]
            self.apps_table.reloadData()
            self.app_selection_changed()

    def save(self):
        name = self.name.stringValue().strip()
        if not name:
            NSBeep()
            return
        sites = []
        for part in self.sites.stringValue().replace("\n", ",").replace(" ", ",").split(","):
            site = focus.clean_site(part)
            if site and site not in sites:
                sites.append(site)
        mode = {"name": name, "minutes": DURATIONS[self.length.indexOfSelectedItem()],
                "block": RULES[self.rule.indexOfSelectedItem()][0], "apps": self.form_apps, "sites": sites,
                "allow_stop": bool(self.allow_stop.state()),
                "auto_at": focus.clean_time(self.auto_at.stringValue()),
                "auto_app": self.auto_app.stringValue().strip()}
        if self.editing is None:
            self.modes().append(mode)
        else:
            self.modes()[self.editing] = mode
        self.close_form()
        self.changed()
