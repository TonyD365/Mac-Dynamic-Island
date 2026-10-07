"""The drop-down under the Focus button: pick a mode, then confirm how long to focus for."""
import objc
from AppKit import (
    NSAppearance, NSAttributedString, NSBackingStoreBuffered, NSBox, NSBoxSeparator, NSButton, NSColor, NSFont,
    NSFontAttributeName, NSForegroundColorAttributeName, NSMakeRect, NSMutableAttributedString, NSPanel,
    NSTextAlignmentCenter, NSTextField, NSView, NSWindowStyleMaskBorderless, NSWindowStyleMaskNonactivatingPanel,
)

import focus
from custom_buttons import _Action

WIDTH = 264.0
PAD = 10.0
MAX_MINUTES = 600


class _KeyPanel(NSPanel):
    """Borderless panel that can take the keyboard (for the duration field) without activating the app."""

    def canBecomeKeyWindow(self):
        return True

    def cancelOperation_(self, sender):         # Esc
        self.owner.close()

    def resignKeyWindow(self):                  # clicked somewhere else
        objc.super(_KeyPanel, self).resignKeyWindow()
        self.owner.close()


class FocusPanel:
    def __init__(self, island):
        self.island = island
        self.visible = False
        self.anchor = (0.0, 0.0)        # screen point of the panel's top-centre
        self._keep = []
        self.field = None
        style = NSWindowStyleMaskBorderless | NSWindowStyleMaskNonactivatingPanel
        self.panel = _KeyPanel.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(0, 0, WIDTH, 100), style, NSBackingStoreBuffered, False)
        self.panel.owner = self
        self.panel.setReleasedWhenClosed_(False)
        self.panel.setOpaque_(False)
        self.panel.setBackgroundColor_(NSColor.clearColor())
        self.panel.setHasShadow_(True)
        self.panel.setMovable_(False)
        self.panel.setLevel_(island.panel.level())
        self.panel.setAppearance_(NSAppearance.appearanceNamed_("NSAppearanceNameDarkAqua"))
        self.content = NSView.alloc().initWithFrame_(NSMakeRect(0, 0, WIDTH, 100))
        self.content.setWantsLayer_(True)
        layer = self.content.layer()
        layer.setBackgroundColor_(NSColor.colorWithWhite_alpha_(0.09, 0.97).CGColor())
        layer.setCornerRadius_(14)
        layer.setCornerCurve_("continuous")
        layer.setBorderWidth_(1)
        layer.setBorderColor_(NSColor.colorWithWhite_alpha_(1.0, 0.14).CGColor())
        self.panel.setContentView_(self.content)

    # ---- showing / hiding ----

    def frame(self):
        return self.panel.frame()

    def show(self, x, top):
        self.anchor = (x, top)
        self.show_modes()
        self.visible = True
        self.panel.makeKeyAndOrderFront_(None)

    def close(self):
        if not self.visible:
            return
        self.visible = False
        self.panel.orderOut_(None)
        self.island.focus_panel_closed()

    # ---- building blocks ----

    def bind(self, callback):
        t = _Action.alloc().init()
        t.callback = callback
        self._keep.append(t)
        return t

    def label(self, text, size=12.0, color=None, bold=False, height=18.0, center=False):
        l = NSTextField.labelWithString_(text)
        l.setFont_(NSFont.boldSystemFontOfSize_(size) if bold else NSFont.systemFontOfSize_(size))
        l.setTextColor_(color or NSColor.labelColor())
        if center:
            l.setAlignment_(NSTextAlignmentCenter)
        return l, height

    def row_button(self, title, detail, action, enabled=True):
        text = NSMutableAttributedString.alloc().initWithString_attributes_(title, {
            NSFontAttributeName: NSFont.systemFontOfSize_weight_(13, 0.3),
            NSForegroundColorAttributeName: NSColor.labelColor() if enabled else NSColor.tertiaryLabelColor()})
        if detail:
            text.appendAttributedString_(NSAttributedString.alloc().initWithString_attributes_("    " + detail, {
                NSFontAttributeName: NSFont.systemFontOfSize_(11),
                NSForegroundColorAttributeName: NSColor.secondaryLabelColor()}))
        b = NSButton.buttonWithTitle_target_action_("", self.bind(action), "fire:")
        b.setBezelStyle_(13)                        # recessed: flat, highlights under the pointer
        b.setShowsBorderOnlyWhileMouseInside_(True)
        b.setAlignment_(0)
        b.setAttributedTitle_(text)
        b.setEnabled_(enabled)
        return b, 28.0

    def separator(self):
        box = NSBox.alloc().initWithFrame_(NSMakeRect(0, 0, WIDTH, 1))
        box.setBoxType_(NSBoxSeparator)
        return box, 9.0

    def layout(self, rows):
        """Stack (view, height) rows top to bottom and size the panel to fit, hanging from the anchor."""
        for view in list(self.content.subviews()):
            view.removeFromSuperview()
        height = sum(h for _, h in rows) + 2 * PAD
        y = height - PAD
        for view, h in rows:
            y -= h
            if view is None:
                continue                # spacer
            if isinstance(view, NSBox):
                view.setFrame_(NSMakeRect(PAD, y + h / 2, WIDTH - 2 * PAD, 1))
            else:
                view.setFrame_(NSMakeRect(PAD, y, WIDTH - 2 * PAD, h))
            self.content.addSubview_(view)
        x, top = self.anchor
        self.panel.setFrame_display_(NSMakeRect(round(x - WIDTH / 2), round(top - height), WIDTH, height), True)
        self.content.setFrame_(NSMakeRect(0, 0, WIDTH, height))

    # ---- step 1: the list of modes (or the running session) ----

    def show_modes(self):
        island = self.island
        self._keep = []
        self.field = None
        gray = NSColor.secondaryLabelColor()
        rows = [self.label("FOCUS", 10.5, gray, bold=True, height=18)]
        if island.pomo_end:
            mode = island.focus_mode or {}
            rows.append(self.label(mode.get("name", "Focus") + " is running", 13, bold=True, height=22))
            if island.focus_locked():
                rows.append(self.label("Locked until the timer runs out", 11, NSColor.systemOrangeColor()))
            else:
                rows.append(self.row_button("Stop Focus", "", lambda: (island.stop_focus(), self.close())))
        else:
            for mode in island.settings["focus_modes"]:
                rows.append(self.row_button(mode.get("name", "Untitled"), focus.describe(mode),
                                            lambda mode=mode: self.show_duration(mode)))
        rows.append(self.separator())
        rows.append(self.row_button("Edit Focus Modes…", "", lambda: (self.close(), island.edit_focus_modes()),
                                    enabled=not island.focus_locked()))
        self.layout(rows)

    # ---- step 2: how long? ----

    def show_duration(self, mode):
        self._keep = []
        gray = NSColor.secondaryLabelColor()
        rows = [self.row_button("‹  " + mode.get("name", "Focus"), "", self.show_modes),
                self.label("How long do you want to focus?", 11.5, gray, height=20)]

        line = NSView.alloc().initWithFrame_(NSMakeRect(PAD, 0, WIDTH - 2 * PAD, 30))
        minus = NSButton.buttonWithTitle_target_action_("−", self.bind(lambda: self.nudge(-5)), "fire:")
        minus.setFrame_(NSMakeRect(34, 0, 40, 30))
        self.field = NSTextField.alloc().initWithFrame_(NSMakeRect(80, 4, 56, 22))
        self.field.setAlignment_(NSTextAlignmentCenter)
        self.field.setStringValue_(str(mode.get("minutes", 25)))
        self.field.setTarget_(self.bind(lambda: self.start(mode)))      # Return starts
        self.field.setAction_("fire:")
        plus = NSButton.buttonWithTitle_target_action_("+", self.bind(lambda: self.nudge(5)), "fire:")
        plus.setFrame_(NSMakeRect(142, 0, 40, 30))
        unit = NSTextField.labelWithString_("minutes")
        unit.setFrame_(NSMakeRect(186, 6, 60, 18))
        unit.setTextColor_(gray)
        for v in (minus, self.field, plus, unit):
            line.addSubview_(v)
        rows.append((line, 34.0))

        count = len(mode.get("apps", [])) + len(mode.get("sites", []))
        if mode.get("block") == focus.WHITELIST:
            rule = "Blocks everything except %d apps and websites" % count
        else:
            rule = "Blocks %d apps and websites" % count if count else "Nothing is blocked"
        rows.append(self.label(rule, 11, gray, center=True))
        if not mode.get("allow_stop", True):
            rows.append(self.label("Can't be stopped before the time is up", 11, NSColor.systemOrangeColor(),
                                   center=True))
        rows.append((None, 6.0))
        start = NSButton.buttonWithTitle_target_action_("Start Focus", self.bind(lambda: self.start(mode)), "fire:")
        start.setKeyEquivalent_("\r")
        rows.append((start, 32.0))
        self.layout(rows)
        self.panel.makeFirstResponder_(self.field)
        self.field.selectText_(None)

    def minutes(self):
        try:
            value = int(float(self.field.stringValue().strip()))
        except (ValueError, AttributeError):
            return None
        return value if 1 <= value <= MAX_MINUTES else None

    def nudge(self, step):
        current = self.minutes() or 25
        self.field.setStringValue_(str(max(1, min(MAX_MINUTES, current + step))))

    def start(self, mode):
        minutes = self.minutes()
        if minutes is None:             # not a number between 1 and 600: stay here
            self.field.selectText_(None)
            return
        self.island.start_focus(mode, minutes)
        self.close()
