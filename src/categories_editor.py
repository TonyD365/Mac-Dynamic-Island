"""The Categories window: which buttons go in which category of the ring.

Left: the categories (plus a "Not shown" shelf for buttons that are in none). Right: the buttons of
the selected one. Drag a button up or down to reorder it, or onto a category to move it there.
Drag a category to reorder the ring. Double-click a category's name to rename it.
"""
import copy

from AppKit import (
    NSApp, NSBackingStoreBuffered, NSBezelBorder, NSButton, NSColor, NSFont, NSImage, NSImageCell, NSMakeRect,
    NSObject, NSPopUpButton, NSScrollView, NSTableColumn, NSTableView, NSTableViewDropAbove, NSTableViewDropOn,
    NSTextField, NSWindow, NSWindowStyleMaskClosable, NSWindowStyleMaskTitled,
)
from Foundation import NSIndexSet

import menu
import settings
from custom_buttons import _Action

ITEM_TYPE = "com.dynamicisland.item"            # dragging a button
CATEGORY_TYPE = "com.dynamicisland.category"    # dragging a category
MOVE = 16                                        # NSDragOperationMove
NONE = 0


def _symbol(name):
    return NSImage.imageWithSystemSymbolName_accessibilityDescription_(name, None)


class _Source(NSObject):
    """Data source and delegate for both tables; `kind` says which one this instance serves."""

    def numberOfRowsInTableView_(self, table):
        return self.editor.row_count(self.kind)

    def tableView_objectValueForTableColumn_row_(self, table, column, row):
        return self.editor.cell(self.kind, column.identifier(), row)

    def tableView_setObjectValue_forTableColumn_row_(self, table, value, column, row):
        if self.kind == "categories":
            self.editor.rename(row, str(value))

    def tableView_shouldEditTableColumn_row_(self, table, column, row):
        return self.kind == "categories" and column.identifier() == "name" and self.editor.is_real(row)

    def tableViewSelectionDidChange_(self, notification):
        self.editor.selection_changed(self.kind)

    # ---- drag and drop ----

    def tableView_writeRowsWithIndexes_toPasteboard_(self, table, rows, pasteboard):
        row = rows.firstIndex()
        if self.kind == "categories":
            if not self.editor.is_real(row):
                return False                    # the "Not shown" shelf stays where it is
            kind = CATEGORY_TYPE
        else:
            kind = ITEM_TYPE
        pasteboard.declareTypes_owner_([kind], self)
        pasteboard.setString_forType_(str(row), kind)
        return True

    def tableView_validateDrop_proposedRow_proposedDropOperation_(self, table, info, row, operation):
        board = info.draggingPasteboard()
        types = board.types() or []
        if self.kind == "categories":
            if ITEM_TYPE in types:              # a button dropped on a category
                if not 0 <= row < self.editor.row_count("categories"):
                    return NONE
                table.setDropRow_dropOperation_(row, NSTableViewDropOn)
                return MOVE
            if CATEGORY_TYPE in types:          # a category moved between categories
                table.setDropRow_dropOperation_(min(row, len(self.editor.categories())), NSTableViewDropAbove)
                return MOVE
            return NONE
        if ITEM_TYPE in types:                  # a button moved within the list
            table.setDropRow_dropOperation_(row, NSTableViewDropAbove)
            return MOVE
        return NONE

    def tableView_acceptDrop_row_dropOperation_(self, table, info, row, operation):
        board = info.draggingPasteboard()
        types = board.types() or []
        if ITEM_TYPE in types:
            source = int(board.stringForType_(ITEM_TYPE))
            if self.kind == "categories":
                return self.editor.move_item_to_category(source, row)
            return self.editor.reorder_item(source, row)
        if CATEGORY_TYPE in types and self.kind == "categories":
            return self.editor.reorder_category(int(board.stringForType_(CATEGORY_TYPE)), row)
        return False


class Editor:
    def __init__(self):
        self.values = None          # the shared settings dict
        self.on_change = None
        self.window = None
        self.selected = 0           # row selected on the left
        self._keep = []

    def bind(self, callback):
        t = _Action.alloc().init()
        t.callback = callback
        self._keep.append(t)
        return t

    def show(self):
        if self.window is None:
            self.build()
            self.window.center()
        self.selected = 0
        self.reload()
        NSApp.activateIgnoringOtherApps_(True)
        self.window.makeKeyAndOrderFront_(None)

    # ---- the model, as the two tables see it ----

    def categories(self):
        return self.values["categories"]

    def is_real(self, row):
        """False for the "Not shown" row, which is not a category of its own."""
        return 0 <= row < len(self.categories())

    def items_of(self, row):
        """The button ids listed on the right when `row` is selected on the left."""
        return self.categories()[row]["items"] if self.is_real(row) else menu.unused(self.values)

    def row_count(self, kind):
        return len(self.categories()) + 1 if kind == "categories" else len(self.items_of(self.selected))

    def cell(self, kind, column, row):
        if kind == "categories":
            if self.is_real(row):
                category = self.categories()[row]
                look = {"icon": _symbol(category.get("icon", "star.fill")), "name": category.get("name", ""),
                        "count": str(len(category["items"]))}
            else:
                look = {"icon": _symbol("eye.slash"), "name": "Not shown", "count": str(len(menu.unused(self.values)))}
            return look[column]
        symbol, label = menu.describe_id(self.values, self.items_of(self.selected)[row])
        return _symbol(symbol) if column == "icon" else label

    # ---- changes ----

    def changed(self, select=None):
        if select is not None:
            self.selected = select
        settings.save(self.values)
        self.reload()
        if self.on_change:
            self.on_change()

    def reload(self):
        self.selected = max(0, min(self.selected, len(self.categories())))
        self.left.reloadData()
        self.left.selectRowIndexes_byExtendingSelection_(NSIndexSet.indexSetWithIndex_(self.selected), False)
        self.right.reloadData()
        real = self.is_real(self.selected)
        self.remove_btn.setEnabled_(real)
        self.icon.setEnabled_(real)
        if real:
            symbols = [s for s, _ in menu.CATEGORY_ICONS]
            current = self.categories()[self.selected].get("icon")
            self.icon.selectItemAtIndex_(symbols.index(current) if current in symbols else 0)
        title = self.categories()[self.selected]["name"] if real else "Not shown"
        self.right_title.setStringValue_("Buttons in “%s”" % title if real else "Buttons that are not in the ring")

    def selection_changed(self, kind):
        if kind == "categories" and self.left.selectedRow() >= 0 and self.left.selectedRow() != self.selected:
            self.selected = self.left.selectedRow()
            self.reload()

    def add_category(self):
        self.categories().append({"name": "New Category", "icon": "folder.fill", "items": []})
        self.changed(len(self.categories()) - 1)

    def remove_category(self):
        if self.is_real(self.selected):
            del self.categories()[self.selected]        # its buttons fall back to "Not shown"
            self.changed(max(0, self.selected - 1))

    def rename(self, row, name):
        name = name.strip()
        if self.is_real(row) and name:
            self.categories()[row]["name"] = name
            self.changed()

    def set_icon(self):
        if self.is_real(self.selected):
            self.categories()[self.selected]["icon"] = menu.CATEGORY_ICONS[self.icon.indexOfSelectedItem()][0]
            self.changed()

    def reset(self):
        self.values["categories"] = copy.deepcopy(menu.DEFAULT_CATEGORIES)
        self.values["known_items"] = []     # so every button is dealt out to its home category again
        menu.normalize(self.values)
        self.changed(0)

    def reorder_item(self, source, before):
        items = self.items_of(self.selected)
        if not self.is_real(self.selected) or not 0 <= source < len(items):
            return False                    # "Not shown" has no order of its own
        item = items.pop(source)
        items.insert(before - 1 if before > source else before, item)
        self.changed()
        return True

    def move_item_to_category(self, source, category_row):
        items = self.items_of(self.selected)
        if not 0 <= source < len(items) or category_row == self.selected:
            return False
        item = items[source]
        for category in self.categories():          # a button lives in at most one category
            if item in category["items"]:
                category["items"].remove(item)
        if self.is_real(category_row):
            self.categories()[category_row]["items"].append(item)
        self.changed()
        return True

    def reorder_category(self, source, before):
        if not self.is_real(source):
            return False
        chosen = self.categories()[self.selected] if self.is_real(self.selected) else None
        category = self.categories().pop(source)
        self.categories().insert(before - 1 if before > source else before, category)
        self.changed(self.categories().index(chosen) if chosen is not None else len(self.categories()))
        return True

    # ---- construction ----

    def table(self, parent, frame, kind, columns):
        table = NSTableView.alloc().initWithFrame_(NSMakeRect(0, 0, frame[2], frame[3]))
        for key, width, editable in columns:
            column = NSTableColumn.alloc().initWithIdentifier_(key)
            column.setWidth_(width)
            column.setEditable_(editable)
            if key == "icon":
                column.setDataCell_(NSImageCell.alloc().init())
            table.addTableColumn_(column)
        table.setHeaderView_(None)
        table.setRowHeight_(24)
        source = _Source.alloc().init()
        source.editor, source.kind = self, kind
        self._keep.append(source)
        table.setDataSource_(source)
        table.setDelegate_(source)
        table.registerForDraggedTypes_([ITEM_TYPE, CATEGORY_TYPE])
        scroll = NSScrollView.alloc().initWithFrame_(NSMakeRect(*frame))
        scroll.setDocumentView_(table)
        scroll.setHasVerticalScroller_(True)
        scroll.setBorderType_(NSBezelBorder)
        parent.addSubview_(scroll)
        return table

    def build(self):
        self.window = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(0, 0, 580, 400), NSWindowStyleMaskTitled | NSWindowStyleMaskClosable,
            NSBackingStoreBuffered, False)
        self.window.setTitle_("Categories")
        self.window.setReleasedWhenClosed_(False)
        content = self.window.contentView()

        def heading(text, x, width):
            l = NSTextField.labelWithString_(text)
            l.setFont_(NSFont.boldSystemFontOfSize_(12))
            l.setFrame_(NSMakeRect(x, 368, width, 18))
            content.addSubview_(l)
            return l

        def button(title, frame, action):
            b = NSButton.buttonWithTitle_target_action_(title, self.bind(action), "fire:")
            b.setFrame_(NSMakeRect(*frame))
            content.addSubview_(b)
            return b

        heading("Categories", 20, 220)
        self.right_title = heading("", 264, 296)
        self.left = self.table(content, (20, 124, 228, 238), "categories",
                               (("icon", 24, False), ("name", 118, True), ("count", 30, False)))
        self.right = self.table(content, (264, 92, 296, 270), "items", (("icon", 26, False), ("name", 240, False)))

        button("+", (14, 86, 44, 32), self.add_category)
        self.remove_btn = button("−", (56, 86, 44, 32), self.remove_category)
        self.icon = NSPopUpButton.alloc().initWithFrame_pullsDown_(NSMakeRect(104, 88, 146, 26), False)
        for symbol, title in menu.CATEGORY_ICONS:
            self.icon.menu().addItemWithTitle_action_keyEquivalent_(title, None, "")
            self.icon.lastItem().setImage_(_symbol(symbol))
        self.icon.setTarget_(self.bind(self.set_icon))
        self.icon.setAction_("fire:")
        content.addSubview_(self.icon)

        hint = NSTextField.wrappingLabelWithString_(
            "Drag a button up or down to reorder it, or onto a category to move it. Drag a category to "
            "reorder the ring. Double-click a category to rename it. Removing a category sends its buttons "
            "to “Not shown”. Settings is always the last button of the ring.")
        hint.setFont_(NSFont.systemFontOfSize_(11))
        hint.setTextColor_(NSColor.secondaryLabelColor())
        hint.setFrame_(NSMakeRect(20, 46, 540, 42))
        content.addSubview_(hint)

        button("Reset to Defaults", (14, 10, 150, 32), self.reset)
        done = button("Done", (476, 10, 90, 32), self.window.close)
        done.setKeyEquivalent_("\r")
