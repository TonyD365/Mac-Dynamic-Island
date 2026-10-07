"""The island window: a borderless, immovable, click-through panel pinned to the notch."""
import math
import os
import time
from types import SimpleNamespace

from AppKit import (
    NSPasteboard, NSPasteboardNameDrag, NSDraggingItem, NSSound, NSURL, NSWorkspace, NSApp, NSApplicationDidChangeScreenParametersNotification, NSBackingStoreBuffered, NSColor, NSEvent, NSFont,
    NSFontDescriptorSystemDesignRounded, NSFontWeightBold, NSFontWeightMedium, NSFontWeightSemibold, NSImage,
    NSImageSymbolConfiguration, NSMainMenuWindowLevel, NSMakePoint, NSMakeRect, NSNull, NSDistributedNotificationCenter, NSNotificationCenter, NSOpenPanel, NSPanel, NSRunLoop,
    NSRunLoopCommonModes, NSTimer, NSValue, NSView, NSWindowCollectionBehaviorCanJoinAllSpaces,
    NSWindowCollectionBehaviorFullScreenAuxiliary, NSWindowCollectionBehaviorIgnoresCycle,
    NSWindowCollectionBehaviorStationary, NSWindowStyleMaskBorderless, NSWindowStyleMaskNonactivatingPanel,
)
import objc
from Foundation import NSUserName
from Quartz import (
    CABasicAnimation, CAGradientLayer, CAKeyframeAnimation, CAMediaTimingFunction, CALayer, CAShapeLayer, CASpringAnimation, CATextLayer, CATransaction,
    CACurrentMediaTime, CGPathAddArc, CGPathAddLineToPoint, CGPathCloseSubpath, CGPathCreateMutable, CGPathMoveToPoint,
    kCALayerMaxXMinYCorner, kCALayerMinXMinYCorner,
)

import about
import actions
import autostart
import backgrounds
import categories_editor
import custom_buttons
import focus
import focus_editor
import focus_panel
import lockscreen
import menu
import monitors
import ring
import screen as screen_util
import calendar_events
import settings
import shelf
import updater
from ui import (
    BLACK, BLUE, FAINT, GRAY, GREEN, HOVER, ORANGE, PINK, PURPLE, RED, WHITE, YELLOW,
    font as _font, no_anim as _no_anim, spring as _spring,
)
from version import VERSION

# Size limits of the island, in points. Every state is clamped to these.
EAR = 46.0            # width on each side of the notch in the always-visible compact state
MAX_W = 300.0         # expanded width (also capped at 30% of the built-in screen)
MAX_H = 80.0          # expanded height
ROW_SPACE = 44.0      # height added below the notch when expanded
SHOULDER = 6.0        # radius of the concave corners where the island meets the screen edge
GLOW_PAD = 40.0       # transparent margin around the island for the glow
MENU_R = ring.RADIUS  # radius of the round buttons that fan out around the island
MENU_GAP = 10.0       # space between the island and the inner ring of buttons
RING_GAP = 8.0        # space between the inner and the outer ring
SHELF_W = 150.0       # the drawer that slides out on the right while the Shelf holds files
SHELF_EAR = 20.0      # extra width beside the notch for the folder mark, when compact
SHELF_ROWS = 3        # files listed in the drawer at once; scroll for the rest
SHELF_ROW_H = 19.0
INNER_SLOTS = 8       # buttons visible at once in each ring; more are reached by turning it
OUTER_SLOTS = 9



class IslandPanel(NSPanel):
    def canBecomeKeyWindow(self):
        return False

    def canBecomeMainWindow(self):
        return False


class IslandView(NSView):
    def acceptsFirstMouse_(self, event):
        return True

    def mouseDownCanMoveWindow(self):
        return False

    def mouseDown_(self, event):
        self.on_click(event.locationInWindow())

    def mouseDragged_(self, event):
        self.on_drag(event.locationInWindow(), event)

    @objc.python_method
    def start_file_drag(self, path, event, image, frame):
        """Begin dragging a file out of the island; from here on it behaves like dragging the file itself."""
        item = NSDraggingItem.alloc().initWithPasteboardWriter_(NSURL.fileURLWithPath_(path))
        item.setDraggingFrame_contents_(frame, image)
        self.beginDraggingSessionWithItems_event_source_([item], event, self)

    @objc.typedSelector(b"Q@:@q")
    def draggingSession_sourceOperationMaskForDraggingContext_(self, session, context):
        return 1 | 2 | 4 | 16           # copy, link, generic, move: the destination picks

    @objc.typedSelector(b"v@:@{CGPoint=dd}Q")
    def draggingSession_endedAtPoint_operation_(self, session, point, operation):
        self.on_drag_out_ended(operation != 0)

    def mouseUp_(self, event):
        self.on_release(event.locationInWindow())

    def scrollWheel_(self, event):
        self.on_scroll(event.scrollingDeltaY(), event.hasPreciseScrollingDeltas())

    # Files dragged onto the island go to the Shelf.
    def draggingEntered_(self, sender):
        return self.on_file_drag(True)

    def draggingUpdated_(self, sender):
        return self.on_file_drag(True)

    def draggingExited_(self, sender):
        self.on_file_drag(False)

    def performDragOperation_(self, sender):
        return self.on_file_drop(sender.draggingPasteboard())


def _greeting():
    hour = time.localtime().tm_hour
    if hour < 5:
        return "Good night"
    if hour < 12:
        return "Good morning"
    if hour < 18:
        return "Good afternoon"
    return "Good evening"


class Island:
    def __init__(self):
        self.monitors = monitors.Monitors()
        self.actions = actions.Actions()
        self.settings = settings.load()
        self.editor = custom_buttons.Editor()
        self.editor.values = self.settings
        self.editor.on_change = self.buttons_changed
        if menu.normalize(self.settings):
            settings.save(self.settings)
        self.categories_editor = categories_editor.Editor()
        self.categories_editor.values = self.settings
        self.categories_editor.on_change = self.update_menu
        self.guard = focus.Guard()
        self.focus_mode = None        # the mode of the running focus session
        self.focus_editor = focus_editor.Editor()
        self.focus_editor.values = self.settings
        self.focus_dropdown = None    # built once the island's window exists
        self.last_block_toast = 0.0
        self.about_window = about.About(self.check_for_updates)
        self.timer_end = None         # when the countdown timer finishes
        self.stopwatch_start = None   # when the stopwatch was started
        self.drag_over = False        # files are being dragged over the island
        self.ext = 0.0                # how far the island currently reaches out to the right
        self.ring_ext = None          # the drawer width the rings are laid out for
        self.shape_key = None         # (mode, extension) the island is drawn in
        self.shelf_press = None       # (path, point) of a shelf icon being pressed
        self.dragging_out = False     # a shelf file is being dragged out
        self.shelf_hover = None       # index of the listed file, or "clear", under the pointer
        self.shelf_offset = 0         # how far the list in the drawer is scrolled
        # Watching for a file being dragged anywhere on screen (see watch_file_drag).
        self.button_down = False
        self.press_count = 0          # the drag pasteboard's change count when the button went down
        self.drag_count = None        # the change count whose contents are in drag_paths
        self.drag_paths = []          # files in the drag now under way, if any
        self.pending_drop = None      # (paths, time) let go over the island, in case macOS doesn't deliver them
        self._icons = {}              # file icons by path
        self.event_alerts = set()     # (event id, kind) already announced
        self.seeking = None           # fraction 0..1 while the progress bar is being dragged
        self.media_layout = None      # whether the middle column is laid out for media right now
        self.updater = updater.Updater(lambda: self.settings["auto_update"])
        self.update_seen = None       # (state, version) already announced
        self.update_opened = None     # version whose installer has been opened
        self.menu_open = False
        self.menu_page = "main"
        self.menu_seen = 0.0
        self.hover = None         # (ring, slot) under the pointer
        self.open_entry = None    # key of the inner-ring button whose outer ring is showing
        self.last_click = (0.0, 0.0)   # where the last ring button pressed sits, for drop-downs
        self.inner = self.outer = None
        self.levels = None        # last seen (volume, muted, brightness)
        self.hud = None           # ("volume" | "brightness", visible-until time)
        self.prev_bt = None
        self.scroll_acc = 0.0
        self.last_rotate = 0.0
        self.on_island = False    # pointer is over the island itself
        self.pointer = (0.0, 0.0) # where the pointer is, in island coordinates
        self.locked = False       # screen is locked: only the harmless buttons are offered
        self.mode = None
        self.size = (0.0, 0.0)
        self.screen_ok = False
        self.last_inside = 0.0
        self.peek_until = 0.0
        self.toast_text = None
        self.pomo_end = None
        self.ticks = 0
        self.prev = None          # last seen monitor snapshot, for change detection
        self.buttons = []         # (x, y, half_size, callback, enabled_fn) in island coords
        self.scale = 2.0
        self._text_cache = {}
        self._symbol_cache = {}

        style = NSWindowStyleMaskBorderless | NSWindowStyleMaskNonactivatingPanel
        self.panel = IslandPanel.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(0, 0, 100, 100), style, NSBackingStoreBuffered, False)
        p = self.panel
        p.setReleasedWhenClosed_(False)
        p.setOpaque_(False)
        p.setBackgroundColor_(NSColor.clearColor())
        p.setHasShadow_(False)
        p.setMovable_(False)
        p.setMovableByWindowBackground_(False)
        p.setHidesOnDeactivate_(False)
        p.setFloatingPanel_(True)
        p.setIgnoresMouseEvents_(True)
        p.setLevel_(NSMainMenuWindowLevel + 3)      # above the menu bar, so it can cover the notch row
        p.setCollectionBehavior_(
            NSWindowCollectionBehaviorCanJoinAllSpaces | NSWindowCollectionBehaviorStationary
            | NSWindowCollectionBehaviorFullScreenAuxiliary | NSWindowCollectionBehaviorIgnoresCycle)

        self.view = IslandView.alloc().initWithFrame_(NSMakeRect(0, 0, 100, 100))
        self.view.on_click = self.on_click
        self.view.on_scroll = self.on_scroll
        self.view.on_drag = self.on_drag
        self.view.on_release = self.on_release
        self.view.on_file_drag = self.on_file_drag
        self.view.on_file_drop = self.on_file_drop
        self.view.on_drag_out_ended = self.on_drag_out_ended
        self.view.registerForDraggedTypes_(["public.file-url"])
        self.root = CALayer.layer()
        self.view.setLayer_(self.root)
        self.view.setWantsLayer_(True)
        p.setContentView_(self.view)

    # ---- lifecycle -------------------------------------------------------

    def start(self):
        self.relocate()
        self.monitors.start()
        self._observer = NSNotificationCenter.defaultCenter().addObserverForName_object_queue_usingBlock_(
            NSApplicationDidChangeScreenParametersNotification, None, None, lambda note: self.relocate())
        center = NSDistributedNotificationCenter.defaultCenter()
        self._lock_observers = [
            center.addObserverForName_object_queue_usingBlock_(name, None, None, lambda note, v=value: self.set_locked(v))
            for name, value in (("com.apple.screenIsLocked", True), ("com.apple.screenIsUnlocked", False))]
        self.monitors.calendar_on = self.settings["calendar"]
        self.welcome_soon(1.2)          # also greets when the island starts at login
        self.updater.start()
        self._timer = NSTimer.timerWithTimeInterval_repeats_block_(0.05, True, lambda t: self.tick())
        NSRunLoop.mainRunLoop().addTimer_forMode_(self._timer, NSRunLoopCommonModes)

    def set_locked(self, locked):
        was_locked, self.locked = self.locked, locked
        if self.menu_open:      # the set of available buttons changes with the lock state
            self.close_menu()
        if was_locked and not locked:
            self.welcome_soon(0.6)      # let the unlock transition finish first

    def welcome_soon(self, delay):
        self._welcome_timer = NSTimer.scheduledTimerWithTimeInterval_repeats_block_(
            delay, False, lambda t: self.welcome())

    def welcome(self):
        """Greeting shown after logging in: the island springs open, an aurora runs round its edge
        and a band of light sweeps across it."""
        if not self.screen_ok or not self.settings["welcome"]:
            return
        user = NSUserName() or ""          # whoever is logged in on this Mac
        self.toast("Welcome back" + (", " + user if user else ""),
                   time.strftime("%A, %B %-d"), PINK, 3.6)
        start = CACurrentMediaTime() + 0.25
        sweep = CABasicAnimation.animationWithKeyPath_("position.x")
        sweep.setFromValue_(-self.exp_w / 2 - 80)
        sweep.setToValue_(self.exp_w / 2 + 80)
        sweep.setDuration_(1.2)
        sweep.setBeginTime_(start)
        sweep.setFillMode_("backwards")
        self.sweep_band.addAnimation_forKey_(sweep, "sweep")
        if not self.settings["glow"]:
            return
        for key, values, times in (
                ("shadowColor", [c.CGColor() for c in (PINK, PURPLE, BLUE, PURPLE, PINK)], None),
                ("shadowOpacity", [0.0, 1.0, 1.0, 0.9, 0.0], [0.0, 0.12, 0.5, 0.8, 1.0]),
                ("shadowRadius", [8.0, 26.0, 18.0, 26.0, 14.0], None)):
            a = CAKeyframeAnimation.animationWithKeyPath_(key)
            a.setValues_(values)
            if times:
                a.setKeyTimes_(times)
            a.setDuration_(3.4)
            self.glow.addAnimation_forKey_(a, "pulse" if key == "shadowOpacity" else "welcome-" + key)

    def drawer_w(self):
        """Width of the Shelf drawer: out while there are files in it, or files are being dragged in."""
        return SHELF_W if (self.settings["shelf"] or self.drag_over or self.dragging_out) else 0.0

    def layout_rings(self, ext):
        """Place both rings round the expanded island, which reaches `ext` further to the right
        when the Shelf drawer is out."""
        hx, hy = self.exp_w / 2 + ext / 2, self.exp_h
        inner_offset = MENU_GAP + MENU_R
        outer_offset = inner_offset + 2 * MENU_R + RING_GAP
        shift = lambda points: [(x + ext / 2, y) for x, y in points]
        self.inner_pos = shift(ring.positions(hx, hy, inner_offset, INNER_SLOTS))
        self.outer_pos = shift(ring.positions(hx, hy, outer_offset, OUTER_SLOTS))
        self.ring_ext = ext
        # How far each ring reaches from the island's centre line, for deciding what the pointer is over.
        self.inner_reach = (hx + inner_offset + MENU_R + 6, hy + inner_offset + MENU_R + 6)
        self.outer_reach = (hx + outer_offset + MENU_R + 6, hy + outer_offset + MENU_R + 6)
        for which, points in ((self.inner, self.inner_pos), (self.outer, self.outer_pos)):
            if which is not None:
                which.move_to(points)

    def relocate(self):
        """(Re)pin the window to the built-in display's notch; hide if there is no built-in display."""
        scr = screen_util.builtin_screen()
        if scr is None:
            self.screen_ok = False
            self.panel.orderOut_(None)
            return
        self.cx, self.top, self.nw, self.nh, self.has_notch = screen_util.notch_geometry(scr)
        self.scale = scr.backingScaleFactor()
        self.monitors.display_id = int(scr.deviceDescription()["NSScreenNumber"])
        screen_w = scr.frame().size.width
        self.compact_w = self.nw + 2 * EAR
        self.exp_w = min(max(MAX_W, self.compact_w + 16), screen_w * 0.3)
        self.exp_h = min(self.nh + ROW_SPACE, MAX_H)
        # Whole-point window size; a fractional one leaves a hairline gap between island and screen edge.
        # Two rings of buttons hug the expanded island: categories close in, their buttons further out.
        hx, hy = self.exp_w / 2, self.exp_h
        outer_offset = MENU_GAP + 3 * MENU_R + RING_GAP
        self.layout_rings(self.drawer_w())
        # Room for the drawer on the right, and for the buttons' spring overshoot, or the window
        # edge clips them mid-bounce. (The window is transparent and click-through, so extra width is free.)
        self.win_w = 2 * math.ceil(max(hx + GLOW_PAD, (hx + SHELF_W + outer_offset) * 1.04 + MENU_R + 10))
        self.win_h = math.ceil(max(hy + GLOW_PAD, (hy + outer_offset) * 1.06 + MENU_R + 10))
        self.panel.setFrame_display_(
            NSMakeRect(self.cx - self.win_w / 2, self.top - self.win_h, self.win_w, self.win_h), True)
        self.build_layers()
        self.screen_ok = True
        self.mode = None
        self.shape_key = None
        self.panel.orderFrontRegardless()
        if self.settings["lockscreen"]:
            lockscreen.attach(self.panel.windowNumber())

    # ---- layers ----------------------------------------------------------
    # Inside the island, (0, 0) is the top-centre (the camera column); y grows downward as negative.

    def build_layers(self):
        self._text_cache.clear()
        self._symbol_cache.clear()
        self.buttons = []
        self.root.setSublayers_(None)
        self.root.setFrame_(NSMakeRect(0, 0, self.win_w, self.win_h))
        black = NSColor.blackColor().CGColor()

        def body(clip):
            l = CALayer.layer()
            l.setAnchorPoint_((0.5, 1.0))
            l.setPosition_((self.win_w / 2, self.win_h))
            l.setBounds_(NSMakeRect(-self.nw / 2, -self.nh, self.nw, self.nh))
            l.setBackgroundColor_(black)
            l.setMaskedCorners_(kCALayerMinXMinYCorner | kCALayerMaxXMinYCorner)   # bottom corners only
            l.setCornerCurve_("continuous")
            l.setCornerRadius_(10)
            l.setMasksToBounds_(clip)
            self.root.addSublayer_(l)
            return l

        menu_root = CALayer.layer()
        menu_root.setPosition_((self.win_w / 2, self.win_h))
        self.root.addSublayer_(menu_root)
        home = (0.0, -self.nh / 2)
        self.outer = ring.Ring(self, menu_root, self.outer_pos, home)     # drawn first: it sits underneath
        self.inner = ring.Ring(self, menu_root, self.inner_pos, home)
        self.menu_open = False
        self.hover = None
        self.open_entry = None

        self.glow = body(False)
        self.glow.setShadowOffset_((0, 0))
        self.glow.setShadowRadius_(14)
        self.glow.setShadowOpacity_(0)
        self.island = body(True)
        self.size = (self.nw, self.nh)

        # Concave "shoulders" that blend the island's top corners into the screen edge, like the real notch.
        anchor = CALayer.layer()
        anchor.setPosition_((self.win_w / 2, self.win_h))
        self.root.addSublayer_(anchor)
        self.shoulders = []
        for sign in (-1, 1):
            r = SHOULDER
            path = CGPathCreateMutable()
            CGPathMoveToPoint(path, None, 0, 0)
            CGPathAddLineToPoint(path, None, sign * r, 0)
            CGPathAddArc(path, None, sign * r, -r, r, math.pi / 2, math.pi if sign > 0 else 0, sign < 0)
            CGPathCloseSubpath(path)
            s = CAShapeLayer.layer()
            s.setPath_(path)
            s.setFillColor_(black)
            s.setPosition_((sign * self.nw / 2, 0))
            anchor.addSublayer_(s)
            self.shoulders.append((sign, s))

        mid = -self.nh / 2
        lx = -(self.nw / 2 + EAR / 2)
        rx = -lx
        self.lx, self.rx, self.mid = lx, rx, mid

        # ---- Ears: always visible ----
        self.ears = self.group(self.island)
        self.ambient = self.group(self.ears)     # clock + battery
        self.ear_time = self.text_layer(self.ambient, lx - EAR / 2, mid, EAR, 12, WHITE, "center",
                                        NSFontWeightSemibold, rounded=True)
        self.cam_dot = self.dot(self.ears, GREEN)
        self.mic_dot = self.dot(self.ears, ORANGE)
        self.ear_text = self.text_layer(self.ears, rx - EAR / 2, mid, EAR, 12, WHITE, "center",
                                        NSFontWeightSemibold, rounded=True)
        self.bars = self.group(self.ears)
        for i in range(4):
            b = CALayer.layer()
            b.setBackgroundColor_(PINK.CGColor())
            b.setCornerRadius_(1.25)
            b.setFrame_(NSMakeRect(rx - 9.5 + i * 5.5, mid - 6.5, 2.5, 13))
            a = CABasicAnimation.animationWithKeyPath_("transform.scale.y")
            a.setFromValue_(0.25)
            a.setToValue_(1.0)
            a.setDuration_(0.28 + 0.09 * ((i * 3) % 4))
            a.setAutoreverses_(True)
            a.setRepeatCount_(float("inf"))
            a.setRemovedOnCompletion_(False)
            b.addAnimation_forKey_(a, "bounce")
            self.bars.addSublayer_(b)

        # Battery glyph: outlined body, level fill, terminal nub.
        self.batt_glyph = self.group(self.ambient)
        shell = CALayer.layer()
        shell.setFrame_(NSMakeRect(rx - 12.5, mid - 5.5, 23, 11))
        shell.setCornerRadius_(3.2)
        shell.setBorderWidth_(1.0)
        shell.setBorderColor_(NSColor.colorWithWhite_alpha_(1.0, 0.45).CGColor())
        nub = CALayer.layer()
        nub.setFrame_(NSMakeRect(rx + 11.5, mid - 2, 1.5, 4))
        nub.setCornerRadius_(0.75)
        nub.setBackgroundColor_(NSColor.colorWithWhite_alpha_(1.0, 0.45).CGColor())
        self.batt_fill = CALayer.layer()
        self.batt_fill.setCornerRadius_(1.7)
        self.batt_fill.setAnchorPoint_((0, 0.5))
        self.batt_fill.setPosition_((rx - 10.5, mid))
        for l in (shell, nub, self.batt_fill):
            self.batt_glyph.addSublayer_(l)

        # Folder mark, shown beside the notch (left of the battery) while the Shelf holds something.
        self.shelf_mark = self.symbol_layer(self.ambient, self.nw / 2 + 13, mid)
        self.set_symbol(self.shelf_mark, "folder.fill", WHITE, 11.0)
        _no_anim(lambda: self.shelf_mark.setOpacity_(0))
        self.ear_frame = self.ear_text.frame()      # the right ear's contents slide over to make room
        self.ear_shift = 0.0

        # The Shelf drawer: the part of the expanded island that slides out on the right.
        dx = self.exp_w / 2
        self.drawer = self.group(self.island)
        rule = CALayer.layer()
        rule.setFrame_(NSMakeRect(dx + 1, -self.exp_h + 10, 1, self.exp_h - 20))
        rule.setCornerRadius_(0.5)
        rule.setBackgroundColor_(FAINT.CGColor())
        self.drawer.addSublayer_(rule)
        # A thin header (title, count, clear) and below it the list: icon and name on each row.
        head = -8.5
        self.drawer_title = self.text_layer(self.drawer, dx + 12, head, SHELF_W - 40, 8.5, GRAY, "left",
                                            NSFontWeightBold)
        self.clear_pos = (dx + SHELF_W - 14, head)
        self.clear_mark = self.symbol_layer(self.drawer, *self.clear_pos)
        self.set_symbol(self.clear_mark, "xmark", GRAY, 8.5)
        first = -16.0 - SHELF_ROW_H / 2                 # centre of the first row
        self.shelf_pos = [(dx + 18, first - i * SHELF_ROW_H) for i in range(SHELF_ROWS)]    # icon centres
        self.shelf_rows = []
        for x, y in self.shelf_pos:
            back = CALayer.layer()                      # highlight under the pointer
            back.setFrame_(NSMakeRect(dx + 6, y - SHELF_ROW_H / 2 + 1, SHELF_W - 12, SHELF_ROW_H - 2))
            back.setCornerRadius_(5)
            back.setBackgroundColor_(NSColor.colorWithWhite_alpha_(1.0, 0.14).CGColor())
            back.setOpacity_(0)
            self.drawer.addSublayer_(back)
            icon = CALayer.layer()
            icon.setBounds_(NSMakeRect(0, 0, 16, 16))
            icon.setPosition_((x, y))
            icon.setContentsGravity_("resizeAspect")
            icon.setContentsScale_(self.scale)
            self.drawer.addSublayer_(icon)
            name = self.text_layer(self.drawer, x + 12, y, SHELF_W - 40, 10.5, WHITE, "left")
            name.setTruncationMode_("middle")           # keeps the file extension in view
            self.shelf_rows.append((back, icon, name))
        self.drawer_note = self.text_layer(self.drawer, dx + 8, -self.exp_h / 2 - 4, SHELF_W - 14, 10.5, GRAY, "center")
        self.shelf_shown = None
        _no_anim(lambda: self.drawer.setOpacity_(0))

        # ---- Expanded content below the notch: clock | now / controls | battery ring ----
        w = self.exp_w
        left = -w / 2 + 18
        base = -self.nh
        self.detail = self.group(self.island)
        full = NSMakeRect(-w / 2, -self.exp_h, w, self.exp_h)
        self.bg = CALayer.layer()
        self.bg.setFrame_(full)
        self.bg.setContentsGravity_("resizeAspectFill")
        self.bg.setMasksToBounds_(True)
        self.bg_dim = CAGradientLayer.layer()     # solid black at the top so the picture melts into the notch
        self.bg_dim.setFrame_(full)
        self.bg_dim.setStartPoint_((0.5, 1.0))
        self.bg_dim.setEndPoint_((0.5, 0.0))
        self.bg_dim.setLocations_([0.0, 0.5, 1.0])
        self.detail.addSublayer_(self.bg)
        self.detail.addSublayer_(self.bg_dim)
        self.apply_background()
        self.time_text = self.text_layer(self.detail, left, base - 17, 72, 20, WHITE, "left",
                                         NSFontWeightBold, rounded=True)
        self.date_text = self.text_layer(self.detail, left + 1, base - 34, 72, 9, GRAY, "left",
                                         NSFontWeightSemibold)
        divider = CALayer.layer()
        divider.setFrame_(NSMakeRect(left + 66, base - 38, 1, 30))
        divider.setCornerRadius_(0.5)
        divider.setBackgroundColor_(FAINT.CGColor())
        self.detail.addSublayer_(divider)

        mx = left + 74                      # middle column
        ring_x = w / 2 - 30
        m_right = ring_x - 15
        self.title_text = self.text_layer(self.detail, mx, base - 15, m_right - mx, 12, WHITE, "left",
                                          NSFontWeightSemibold)
        self.rows = (base - 15, base - 33)        # title / subtitle centres normally...
        self.media_rows = (base - 12, base - 27)  # ...and moved up to make room for the progress bar
        self.sub_wide = m_right - mx
        self.sub_narrow = m_right - mx - 3 * 22 - 5  # leave room for the music controls
        self.sub_is_narrow = False
        self.sub_text = self.text_layer(self.detail, mx, base - 33, self.sub_wide, 10, GRAY, "left")
        self.bar = self.group(self.detail)
        self.bar_w = self.sub_wide - 4
        track = CALayer.layer()
        track.setFrame_(NSMakeRect(mx, base - 35, self.bar_w, 4))
        track.setCornerRadius_(2)
        track.setBackgroundColor_(NSColor.colorWithWhite_alpha_(1.0, 0.22).CGColor())
        self.bar_fill = CALayer.layer()
        self.bar_fill.setAnchorPoint_((0, 0.5))
        self.bar_fill.setPosition_((mx, base - 33))
        self.bar_fill.setCornerRadius_(2)
        self.bar_fill.setBackgroundColor_(WHITE.CGColor())
        self.bar.addSublayer_(track)
        self.bar.addSublayer_(self.bar_fill)
        _no_anim(lambda: self.bar.setOpacity_(0))

        # Playback progress: a thin bar under the two rows; click or drag it to seek.
        self.progress = self.group(self.detail)
        self.prog_x, self.prog_w, self.prog_y = mx, m_right - mx - 2, base - 38.5
        rail = CALayer.layer()
        rail.setFrame_(NSMakeRect(self.prog_x, self.prog_y - 1.5, self.prog_w, 3))
        rail.setCornerRadius_(1.5)
        rail.setBackgroundColor_(NSColor.colorWithWhite_alpha_(1.0, 0.22).CGColor())
        self.prog_fill = CALayer.layer()
        self.prog_fill.setAnchorPoint_((0, 0.5))
        self.prog_fill.setPosition_((self.prog_x, self.prog_y))
        self.prog_fill.setCornerRadius_(1.5)
        self.prog_fill.setBackgroundColor_(WHITE.CGColor())
        self.prog_knob = CALayer.layer()
        self.prog_knob.setBounds_(NSMakeRect(0, 0, 9, 9))
        self.prog_knob.setCornerRadius_(4.5)
        self.prog_knob.setBackgroundColor_(WHITE.CGColor())
        for l in (rail, self.prog_fill, self.prog_knob):
            self.progress.addSublayer_(l)
        _no_anim(lambda: self.progress.setOpacity_(0))

        self.music_btns = self.group(self.detail)
        bx = m_right - 14
        has_music = lambda: bool(self.monitors.music and self.monitors.music.get("control"))
        self.next_btn = self.button(self.music_btns, bx, base - 27, "forward.fill",
                                    lambda: self.player("next track"), has_music)
        self.play_btn = self.button(self.music_btns, bx - 22, base - 27, "play.fill",
                                    lambda: self.player("playpause"), has_music)
        self.prev_btn = self.button(self.music_btns, bx - 44, base - 27, "backward.fill",
                                    lambda: self.player("previous track"), has_music)

        # Battery ring with the percentage inside
        ring_y = base - 23
        ring_r = 12.0
        circle = CGPathCreateMutable()
        CGPathAddArc(circle, None, 0, 0, ring_r, math.pi / 2, math.pi / 2 - 2 * math.pi, True)
        self.ring = None
        for color in (FAINT, WHITE):
            arc = CAShapeLayer.layer()
            arc.setPath_(circle)
            arc.setFillColor_(None)
            arc.setStrokeColor_(color.CGColor())
            arc.setLineWidth_(2.5)
            arc.setLineCap_("round")
            arc.setPosition_((ring_x, ring_y))
            self.detail.addSublayer_(arc)
            self.ring = arc
        self.ring.setStrokeEnd_(0)
        self.ring_text = self.text_layer(self.detail, ring_x - ring_r, ring_y, 2 * ring_r, 9.5, WHITE, "center",
                                         NSFontWeightBold, rounded=True)

        self.sweep_band = CAGradientLayer.layer()
        self.sweep_band.setBounds_(NSMakeRect(0, 0, 110, self.exp_h))
        self.sweep_band.setStartPoint_((0.0, 0.5))
        self.sweep_band.setEndPoint_((1.0, 0.5))
        clear = NSColor.colorWithWhite_alpha_(1.0, 0.0).CGColor()
        self.sweep_band.setColors_([clear, NSColor.colorWithWhite_alpha_(1.0, 0.26).CGColor(), clear])
        self.sweep_band.setAffineTransform_((1.0, 0.0, -0.35, 1.0, 0.0, 0.0))     # slanted, like a glint
        self.sweep_band.setPosition_((self.exp_w / 2 + 200, -self.exp_h / 2))
        self.island.addSublayer_(self.sweep_band)

        for l in (self.detail, self.bars, self.cam_dot, self.mic_dot, self.music_btns, self.batt_glyph):
            _no_anim(lambda l=l: l.setOpacity_(0))

    def group(self, parent):
        g = CALayer.layer()
        parent.addSublayer_(g)
        return g

    def dot(self, parent, color):
        d = CALayer.layer()
        d.setBounds_(NSMakeRect(0, 0, 8, 8))
        d.setCornerRadius_(4)
        d.setBackgroundColor_(color.CGColor())
        d.setShadowColor_(color.CGColor())
        d.setShadowOffset_((0, 0))
        d.setShadowRadius_(4)
        d.setShadowOpacity_(0.9)
        parent.addSublayer_(d)
        return d

    def text_layer(self, parent, x, y_center, width, size, color, align, weight=NSFontWeightMedium, rounded=False):
        t = CATextLayer.layer()
        t.setFont_(_font(size, weight, rounded))
        t.setFontSize_(size)
        t.setForegroundColor_(color.CGColor())
        t.setAlignmentMode_(align)
        t.setTruncationMode_("end")
        t.setContentsScale_(self.scale)
        t.setActions_({"contents": NSNull.null(), "string": NSNull.null()})   # swap text instantly, no ghosting
        h = round(size * 1.3)
        t.setFrame_(NSMakeRect(x, y_center - h / 2, width, h))
        parent.addSublayer_(t)
        return t

    def symbol_layer(self, parent, x, y):
        l = CALayer.layer()
        l.setBounds_(NSMakeRect(0, 0, 18, 18))
        l.setPosition_((x, y))
        l.setContentsGravity_("resizeAspect")
        l.setContentsScale_(self.scale)
        parent.addSublayer_(l)
        return l

    def button(self, parent, x, y, symbol, callback, enabled=lambda: True):
        l = self.symbol_layer(parent, x, y)
        self.set_symbol(l, symbol, WHITE)
        self.buttons.append((x, y, 11.0, callback, enabled))
        return l

    def set_symbol(self, layer, name, color, size=10.5):
        key = (name, id(color))
        if self._symbol_cache.get(id(layer)) == key:
            return
        self._symbol_cache[id(layer)] = key
        img = NSImage.imageWithSystemSymbolName_accessibilityDescription_(name, None)
        if img is None:
            return
        cfg = NSImageSymbolConfiguration.configurationWithPointSize_weight_(size, NSFontWeightSemibold)
        cfg = cfg.configurationByApplyingConfiguration_(
            NSImageSymbolConfiguration.configurationWithPaletteColors_([color]))
        img = img.imageWithSymbolConfiguration_(cfg)
        s = img.size()

        def apply():
            layer.setBounds_(NSMakeRect(0, 0, s.width, s.height))
            layer.setContents_(img.layerContentsForContentsScale_(self.scale))
        _no_anim(apply)

    def set_text(self, layer, s):
        if self._text_cache.get(id(layer)) != s:
            self._text_cache[id(layer)] = s
            _no_anim(lambda: layer.setString_(s))

    # ---- shape & effects -------------------------------------------------

    def set_shape(self, w, h, radius, bounce=True, ext=0.0):
        """Resize the island: `w` wide about the camera, plus `ext` more on the right."""
        # Bounce only when growing. When shrinking, a critically damped spring settles without
        # undershooting, so the island never gets smaller than the notch it sits on.
        damping = 19.0 if bounce else 34.0
        self.size, self.ext = (w, h), ext
        new = NSMakeRect(-w / 2, -h, w + ext, h)
        centre = NSMakePoint(self.win_w / 2 + ext / 2, self.win_h)     # keeps x = 0 on the camera
        for layer in (self.glow, self.island):
            shown = layer.presentationLayer() or layer
            old, old_centre = shown.bounds(), shown.position()

            def apply(layer=layer):
                layer.setBounds_(new)
                layer.setPosition_(centre)
            _no_anim(apply)
            layer.setCornerRadius_(radius)
            layer.addAnimation_forKey_(
                _spring("bounds", NSValue.valueWithRect_(old), NSValue.valueWithRect_(new), damping), "shape")
            layer.addAnimation_forKey_(
                _spring("position", NSValue.valueWithPoint_(old_centre), NSValue.valueWithPoint_(centre), damping),
                "place")
        for sign, s in self.shoulders:
            old_x = (s.presentationLayer() or s).position().x
            new_x = sign * w / 2 + (ext if sign > 0 else 0.0)
            _no_anim(lambda s=s, new_x=new_x: s.setPosition_((new_x, 0)))
            s.addAnimation_forKey_(_spring("position.x", old_x, new_x, damping), "shape")

    def pulse(self, color):
        if not self.settings["glow"]:
            return
        self.glow.setShadowColor_(color.CGColor())
        a = CAKeyframeAnimation.animationWithKeyPath_("shadowOpacity")
        a.setValues_([0.0, 0.95, 0.5, 0.0])
        a.setKeyTimes_([0.0, 0.2, 0.6, 1.0])
        a.setDuration_(1.8)
        self.glow.addAnimation_forKey_(a, "pulse")

    def toast(self, title, subtitle, color, seconds=3.0):
        self.toast_text = (title, subtitle)
        self.peek_until = time.time() + seconds
        self.pulse(color)

    # ---- actions ---------------------------------------------------------

    def on_click(self, point):
        if self.mode != "expanded":
            return
        x = point.x - self.win_w / 2
        y = point.y - self.win_h
        if self.can_seek() and self.prog_x - 6 <= x <= self.prog_x + self.prog_w + 6 and abs(y - self.prog_y) <= 8:
            self.seeking = self.seek_fraction(x)      # dragging continues in on_drag
            self.refresh(time.time())
            return
        hit = self.shelf_at(x, y)
        if hit == "clear":
            self.settings["shelf"][:] = []
            settings.save(self.settings)
            self.refresh(time.time())
            return
        if hit is not None:
            self.shelf_press = (self.settings["shelf"][hit], hit, (x, y))     # a click reveals; a drag takes it out
            return
        if self.menu_open:
            for which in (self.outer, self.inner):
                slot = which.slot_at(x, y)
                if slot is not None:
                    self.press(which, slot)
                    return
        for bx, by, half, callback, enabled in self.buttons:
            if abs(x - bx) <= half and abs(y - by) <= half and enabled():
                callback()
                return
        if self.menu_open:
            self.close_menu()
        else:
            self.open_menu()

    # ---- action menu -----------------------------------------------------

    def inner_entries(self):
        """What the inner ring holds right now: categories, or the settings groups."""
        return menu.settings_entries(self) if self.menu_page == "settings" else menu.main_entries(self)

    def press(self, which, slot):
        """A ring button was clicked: open its outer ring, or do what it does."""
        item = which.shown()[slot]
        self.last_click = which.pos[slot]
        if item.children is not None:
            if self.open_entry == item.key:
                self.close_outer()
            else:
                self.open_outer(item, which.pos[slot])
        else:
            item.action()
        self.update_menu()
        self.refresh(time.time())

    def open_outer(self, item, origin):
        self.open_entry = item.key
        self.inner.selected = item.key
        self.outer.set_items(item.children)
        self.outer.show(origin)             # the buttons fan out from the category that was clicked

    def close_outer(self):
        self.open_entry = None
        self.inner.selected = None
        self.outer.hide()

    def update_menu(self):
        """Re-read what the rings hold (lists and on/off states change) and redraw them."""
        if not self.menu_open or self.inner is None:
            return
        entries = self.inner_entries()
        self.inner.set_items(entries, keep_offset=True)
        opened = next((e for e in entries if e.key == self.open_entry), None)
        if self.open_entry is not None and (opened is None or not opened.children):
            self.close_outer()              # the open category disappeared (emptied, or the screen locked)
        elif opened is not None:
            self.outer.set_items(opened.children, keep_offset=True)
            self.outer.update()
        self.inner.selected = self.open_entry
        self.inner.update()

    def buttons_changed(self):
        """Custom buttons or categories were edited: tidy the categories and redraw."""
        menu.normalize(self.settings)
        settings.save(self.settings)
        self.update_menu()

    def hovered_item(self):
        if self.hover is None:
            return None
        which, slot = self.hover
        shown = which.shown()
        return shown[slot] if slot < len(shown) else None

    def set_page(self, page):
        self.menu_page = page
        self.close_outer()
        self.inner.set_items(self.inner_entries())
        self.inner.pop()

    def open_menu(self):
        self.menu_open = True
        self.menu_page = "main"
        self.scroll_acc = 0.0
        self.menu_seen = time.time()
        self.open_entry = None
        self.inner.selected = None
        self.inner.set_items(self.inner_entries())
        self.inner.show()

    def close_menu(self):
        self.menu_open = False
        if self.focus_dropdown is not None and self.focus_dropdown.visible:
            self.focus_dropdown.close()
        self.hover = None
        self.open_entry = None
        self.outer.hide()
        self.inner.hide()

    def ring_under(self, x, y):
        """Which ring the pointer is over, for scrolling: the nearer one of those that are out."""
        if self.outer.visible and self.outer.distance(x, y) < self.inner.distance(x, y):
            return self.outer
        return self.inner

    def show_about(self):
        self.close_menu()
        self.about_window.show()

    def edit_categories(self):
        self.close_menu()
        self.categories_editor.show()

    def run_custom(self, button):
        self.close_menu()
        custom_buttons.run(button)

    def edit_custom_buttons(self):
        self.close_menu()
        self.editor.show()

    def screenshot(self):
        self.close_menu()
        self.actions.screenshot()

    def pick_color(self):
        self.close_menu()
        self.actions.pick_color(lambda text: self.toast(text, "Copied to clipboard", WHITE))

    def open_folder(self, path):
        self.close_menu()
        self.actions.open_path(path)

    # ---- timer and stopwatch ----

    @staticmethod
    def clock_text(seconds):
        seconds = max(0, int(seconds))
        if seconds >= 3600:
            return "%d:%02d:%02d" % (seconds // 3600, seconds % 3600 // 60, seconds % 60)
        return "%d:%02d" % (seconds // 60, seconds % 60)

    def countdown(self, end):
        return self.clock_text(end - time.time() + 0.99) if end else ""      # 0:01 until it really is over

    def elapsed(self, start):
        return self.clock_text(time.time() - start) if start else ""

    def start_timer(self, minutes):
        self.timer_end = time.time() + minutes * 60
        self.toast("Timer", "%d minute%s" % (minutes, "" if minutes == 1 else "s"), ORANGE, 2.5)
        self.update_menu()

    def cancel_timer(self):
        self.timer_end = None
        self.pulse(GRAY)
        self.update_menu()

    def toggle_stopwatch(self):
        if self.stopwatch_start:
            self.toast("Stopwatch", self.elapsed(self.stopwatch_start), BLUE, 5.0)
            self.stopwatch_start = None
        else:
            self.stopwatch_start = time.time()
            self.pulse(BLUE)

    # ---- the shelf ----

    def on_file_drag(self, over):
        """macOS asks whether files dragged over the island may be dropped. Returns the operation offered."""
        if self.locked or self.dragging_out:        # not on the lock screen, and not our own file coming back
            return 0
        return 4 if over else 0             # NSDragOperationGeneric: nothing is copied or moved

    def on_file_drop(self, pasteboard):
        """macOS delivered a drop."""
        self.pending_drop = None            # delivered properly: the fallback has nothing left to do
        return self.take_files(shelf.paths_from(pasteboard))

    def take_files(self, paths):
        self.drag_over = False
        added = shelf.add(self.settings, paths)
        if added:
            settings.save(self.settings)
        count = len(self.settings["shelf"])
        self.toast("Added to the Shelf" if added else "Already on the Shelf",
                   "%d item%s kept" % (count, "" if count == 1 else "s"), BLUE)
        return bool(added)

    def watch_file_drag(self, now, x, y):
        """Notice a file being dragged anywhere on screen, without relying on macOS telling this window.

        The island is click-through until the pointer is on it, and it lives in its own window-server
        space above everything else; in practice macOS does not reliably offer such a window a drag
        that started elsewhere. So the drag is detected directly: the mouse button is down and the
        system's drag pasteboard has changed since it went down and holds files. While that is true
        the island opens as the pointer comes near, and if the files are let go over it they are
        taken from the drag pasteboard.
        """
        down = bool(NSEvent.pressedMouseButtons() & 1)
        board = NSPasteboard.pasteboardWithName_(NSPasteboardNameDrag)
        count = board.changeCount()
        if down and not self.button_down:
            self.press_count = count
        dragging = down and count != self.press_count and not self.dragging_out and not self.locked
        if dragging and count != self.drag_count:           # read the pasteboard once per drag
            self.drag_count = count
            self.drag_paths = shelf.paths_from(board)
        dragging = dragging and bool(self.drag_paths)

        # A generous target: the whole expanded island and its drawer, with some margin.
        near = (-self.exp_w / 2 - 20 <= x <= self.exp_w / 2 + SHELF_W + 20) and y >= -self.exp_h - 16
        over = dragging and near
        if over:
            self.peek_until = max(self.peek_until, now + 0.25)      # stay open while the files hover
        if over != self.drag_over:
            self.drag_over = over
            self.refresh(now)
        if self.button_down and not down and self.drag_paths:      # the button has just come up
            if near and not self.dragging_out and not self.locked and count != self.press_count:
                self.pending_drop = (list(self.drag_paths), now)
            self.drag_paths = []
        self.button_down = down
        # Give macOS a moment to deliver the drop itself; if it has not, take the files anyway.
        if self.pending_drop is not None and now - self.pending_drop[1] > 0.2:
            paths, self.pending_drop = self.pending_drop[0], None
            self.take_files(paths)
        return dragging

    def on_drag_out_ended(self, dropped):
        """A shelf file was let go: once it has landed somewhere it leaves the Shelf."""
        path = self.shelf_press[0] if self.shelf_press else None
        self.dragging_out = False
        self.shelf_press = None
        if dropped and path in self.settings["shelf"]:
            self.settings["shelf"].remove(path)
            settings.save(self.settings)
        self.refresh(time.time())

    def over_drawer(self, x, y):
        return (self.mode == "expanded" and self.ext >= SHELF_W
                and self.exp_w / 2 <= x <= self.exp_w / 2 + self.ext and -self.exp_h <= y <= 0)

    def shelf_at(self, x, y):
        """What part of the drawer is at this point: a file's index, "clear", or None."""
        paths = self.settings["shelf"]
        if not paths or not self.over_drawer(x, y):
            return None
        cx, cy = self.clear_pos
        if abs(x - cx) <= 10 and abs(y - cy) <= 8:
            return "clear"
        for row, (_, ty) in enumerate(self.shelf_pos):
            index = self.shelf_offset + row
            if index < len(paths) and abs(y - ty) <= SHELF_ROW_H / 2:
                return index
        return None

    def scroll_shelf(self, step):
        """Scroll the list in the drawer by one file. Returns False if there is nowhere to go."""
        last = max(0, len(self.settings["shelf"]) - SHELF_ROWS)
        target = max(0, min(last, self.shelf_offset + step))
        if target == self.shelf_offset:
            return False
        self.shelf_offset = target
        return True

    def file_icon(self, path):
        if path not in self._icons:
            self._icons[path] = NSWorkspace.sharedWorkspace().iconForFile_(path)
        return self._icons[path]

    def draw_shelf(self):
        """Bring the drawer and the folder mark up to date with what is on the Shelf."""
        paths = self.settings["shelf"]
        self.shelf_offset = max(0, min(self.shelf_offset, len(paths) - SHELF_ROWS))    # files may have left
        key = (tuple(paths), self.drag_over, self.shelf_offset, self.shelf_hover)
        if key == self.shelf_shown:
            return
        self.shelf_shown = key
        hovered = self.shelf_hover if isinstance(self.shelf_hover, int) else None

        def apply():
            for row, (back, icon, _) in enumerate(self.shelf_rows):
                index = self.shelf_offset + row
                icon.setContents_(self.file_icon(paths[index]) if index < len(paths) else None)
                back.setOpacity_(1 if index == hovered else 0)
            self.clear_mark.setOpacity_(1 if paths else 0)
            self.shelf_mark.setOpacity_(1 if paths else 0)
            # Clock-side stays put; battery, music bars and countdown slide right to clear the folder mark.
            shift = SHELF_EAR if paths else 0.0
            self.batt_glyph.setPosition_((shift, 0))
            self.bars.setPosition_((shift, 0))
            f = self.ear_frame
            self.ear_text.setFrame_(NSMakeRect(f.origin.x + shift, f.origin.y, f.size.width, f.size.height))
        _no_anim(apply)
        for row, (_, _, name) in enumerate(self.shelf_rows):
            index = self.shelf_offset + row
            shown = (os.path.basename(paths[index].rstrip("/")) or paths[index]) if index < len(paths) else ""
            self.set_text(name, shown)
        if len(paths) > SHELF_ROWS:         # say where in the list we are, since not all of it shows
            last = self.shelf_offset + SHELF_ROWS
            self.set_text(self.drawer_title, "SHELF  ·  %d–%d OF %d" % (self.shelf_offset + 1, last, len(paths)))
        else:
            self.set_text(self.drawer_title, "SHELF")
        self.set_text(self.drawer_note, "" if paths else "Drop files here")

    # ---- calendar ----

    def calendar_status(self):
        calendar = self.monitors.calendar
        if not calendar.available():
            return "Not available in this build"
        if not self.settings["calendar"]:
            return "Off"
        if calendar.authorized():
            return "On"
        return "No access  ·  allow it in System Settings" if calendar.denied() else "Waiting for permission"

    def toggle_calendar(self):
        calendar = self.monitors.calendar
        self.settings["calendar"] = not self.settings["calendar"] and calendar.available()
        settings.save(self.settings)
        self.monitors.calendar_on = self.settings["calendar"]
        if self.settings["calendar"] and not calendar.authorized():
            calendar.request_access()

    def launch(self, app_name):
        self.close_menu()
        self.actions.open_app(app_name)

    def lock_screen(self):
        self.close_menu()
        self.actions.lock_screen()

    def choose_image(self):
        self.close_menu()
        NSApp.activateIgnoringOtherApps_(True)
        panel = NSOpenPanel.openPanel()
        panel.setMessage_("Choose a background picture for the island")
        panel.setAllowedFileTypes_(["png", "jpg", "jpeg", "heic", "tiff", "gif", "bmp", "webp"])
        if panel.runModal() == 1 and panel.URL() is not None:
            self.settings["background_custom"] = panel.URL().path()
            self.settings["background"] = "custom"
            settings.save(self.settings)
            self.apply_background()

    def apply_background(self):
        image = backgrounds.load(backgrounds.path_for(self.settings))
        dim = self.settings["background_dim"]
        shade = lambda alpha: NSColor.colorWithWhite_alpha_(0.0, alpha).CGColor()

        def apply():
            self.bg.setContents_(image)
            self.bg.setHidden_(image is None)
            self.bg_dim.setHidden_(image is None)
            self.bg_dim.setColors_([shade(1.0), shade(dim), shade(min(1.0, dim + 0.12))])
        _no_anim(apply)

    def on_scroll(self, delta, precise):
        """Scrolling on the island itself changes the volume; around it, it turns the open button ring."""
        if not delta:
            return
        if self.over_drawer(*self.pointer):     # the list in the Shelf drawer
            notch = 12.0 if precise else 1.0
            self.scroll_acc = max(-notch, min(notch, self.scroll_acc + delta))
            now = time.time()
            if abs(self.scroll_acc) >= notch and now - self.last_rotate >= 0.08:
                self.last_rotate = now
                if self.scroll_shelf(1 if self.scroll_acc < 0 else -1):
                    self.refresh(now)
                self.scroll_acc = 0.0
            return
        if self.menu_open and not self.on_island:
            notch = 12.0 if precise else 1.0
            self.scroll_acc = max(-notch, min(notch, self.scroll_acc + delta))
            now = time.time()
            # At most one step every 80 ms: a fast flick turns the ring steadily instead of
            # firing dozens of overlapping steps.
            if abs(self.scroll_acc) >= notch and now - self.last_rotate >= 0.08:
                self.last_rotate = now
                if self.ring_under(*self.pointer).rotate(1 if self.scroll_acc < 0 else -1):
                    self.refresh(now)
                self.scroll_acc = 0.0
            return
        raw = self.monitors
        if not self.settings["scroll_volume"] or raw.volume is None:
            return
        delta = max(-20.0, min(20.0, delta)) if precise else max(-2.0, min(2.0, delta))   # tame fast flicks
        raw.volume = max(0.0, min(1.0, raw.volume + delta * (0.003 if precise else 0.03)))
        monitors.set_volume(raw.volume)

    def check_levels(self, now):
        """Show the bar when the volume, mute state or brightness changes."""
        raw = self.monitors
        new, old = (raw.volume, raw.muted, raw.brightness), self.levels
        self.levels = new
        if old is None or not self.settings["hud"]:
            return
        changed = lambda a, b, step: a is not None and b is not None and abs(a - b) > step
        kind = None
        if changed(new[0], old[0], 0.004) or (None not in (new[1], old[1]) and new[1] != old[1]):
            kind = "volume"
        elif changed(new[2], old[2], 0.03):     # ignores the slow drift of auto-brightness
            kind = "brightness"
        if kind:
            self.hud = (kind, now + 1.6)
            self.peek_until = max(self.peek_until, now + 1.6)
            self.refresh(now)

    def sleep_display(self):
        self.close_menu()
        self.actions.sleep_display()

    def clock(self):
        return time.strftime("%H:%M" if self.settings["clock24"] else "%-I:%M")

    def player(self, command):
        m = self.monitors.music
        if not (m and m.get("control")):
            return
        monitors.media_command(m, command)
        self.monitors.music_hold = time.time() + 1.2
        if command == "playpause":          # show the new state at once; the next reading confirms it
            m["position"], m["at"] = monitors.position_now(m), time.time()
            m["playing"] = not m["playing"]
        self.refresh(time.time())

    # ---- seeking ----

    def can_seek(self):
        m = self.monitors.music if self.settings["music"] else None
        return bool(m and m.get("control") == monitors.SYSTEM and m.get("duration", 0) > 0 and not self.locked)

    def seek_fraction(self, x):
        return max(0.0, min(1.0, (x - self.prog_x) / self.prog_w))

    def on_drag(self, point, event=None):
        if self.seeking is not None:
            self.seeking = self.seek_fraction(point.x - self.win_w / 2)
            self.refresh(time.time())
        elif self.shelf_press is not None and not self.dragging_out and event is not None:
            path, index, (px, py) = self.shelf_press
            x, y = point.x - self.win_w / 2, point.y - self.win_h
            if math.hypot(x - px, y - py) > 4:              # moved far enough to mean a drag
                self.dragging_out = True
                row = max(0, min(SHELF_ROWS - 1, index - self.shelf_offset))
                tx, ty = self.shelf_pos[row]
                frame = NSMakeRect(self.win_w / 2 + tx - 12, self.win_h + ty - 12, 24, 24)
                self.view.start_file_drag(path, event, self.file_icon(path), frame)

    def on_release(self, point):
        if self.shelf_press is not None and not self.dragging_out:
            shelf.reveal(self.shelf_press[0])               # a plain click shows the file in Finder
            self.shelf_press = None
            return
        if self.seeking is None:
            return
        fraction, self.seeking = self.seek_fraction(point.x - self.win_w / 2), None
        m = self.monitors.music
        if m and m.get("duration"):
            m["position"], m["at"] = fraction * m["duration"], time.time()
            self.monitors.music_hold = time.time() + 1.2
            monitors.media_seek(m["position"])
        self.refresh(time.time())

    # ---- updates ----

    def update_status(self):
        up = self.updater
        if not updater.can_update():
            return "Development build  ·  updates off"
        return {
            "checking": "Version %s  ·  checking…" % VERSION,
            "available": "Version %s is available  ·  click to install" % up.latest,
            "downloading": "Downloading version %s…" % up.latest,
            "ready": "Version %s is ready  ·  click to install" % up.latest,
            "failed": "Could not check  ·  click to retry",
        }.get(up.state, "Version %s  ·  up to date" % VERSION)

    def check_for_updates(self):
        up = self.updater
        if not updater.can_update():
            self.toast("Development build", "Only released versions update themselves", GRAY)
        elif up.state == "ready":
            self.open_update()
        elif up.state not in ("checking", "downloading"):
            self.update_seen = None
            up.check_now()

    def open_update(self):
        if self.updater.install():
            self.update_opened = self.updater.latest
            self.close_menu()
            self.toast("Installing version %s" % self.updater.latest, "Follow the installer to finish", BLUE, 5.0)

    def watch_updates(self):
        """Announce what the updater found, and open a finished download when the moment is right."""
        up = self.updater
        key = (up.state, up.latest)
        if key != self.update_seen:
            self.update_seen = key
            if up.state == "downloading" or (up.state == "available" and not up.manual):
                self.toast("Update available", "Version %s  ·  %s" % (
                    up.latest, "downloading" if up.state == "downloading" else "install it from Settings"), BLUE, 4.0)
            elif up.state == "current" and up.manual:
                self.toast("You're up to date", "Version %s" % VERSION, GREEN)
            elif up.state == "failed" and up.manual:
                self.toast("Update check failed", (up.error or "Try again later")[:60], ORANGE, 4.0)
        # Never interrupt a focus session or pop an installer up on the lock screen.
        if (up.state == "ready" and self.update_opened != up.latest and not self.locked and not self.pomo_end
                and (up.manual or self.settings["auto_update"])):
            self.open_update()

    # ---- focus sessions ----

    def show_focus_dropdown(self):
        """Open the drop-down just under the Focus button (and clear of the island itself)."""
        self.dropdown_panel()
        self.place_dropdown(self.focus_dropdown.show_modes)

    def show_timer_dropdown(self):
        self.dropdown_panel()
        self.place_dropdown(self.focus_dropdown.show_timer)

    def dropdown_panel(self):
        if self.focus_dropdown is None:
            self.focus_dropdown = focus_panel.FocusPanel(self)
        return self.focus_dropdown

    def place_dropdown(self, view):
        """Hang the drop-down under the ring button that was just pressed, clear of the island."""
        panel = self.dropdown_panel()
        bx, by = self.last_click
        top = min(by - MENU_R - 8, -self.exp_h - 10)
        half = focus_panel.WIDTH / 2
        # Ring buttons the panel would sit on are tucked away while it is open.
        area = (bx - half, top - 400.0, bx + half, top)
        for which in (self.inner, self.outer):
            which.hide_under(area, except_slot=None)
        panel.show(self.cx + bx, self.top + top, view)

    def focus_panel_closed(self):
        for which in (self.inner, self.outer):
            which.unhide()
        self.menu_seen = time.time()

    def edit_focus_modes(self):
        if self.focus_locked():
            self.toast("Focus is locked", "Modes can be edited when it ends", ORANGE)
            return
        self.close_menu()
        self.focus_editor.show()

    def focus_locked(self):
        return bool(self.pomo_end and self.focus_mode and not self.focus_mode.get("allow_stop", True))

    def start_focus(self, mode, minutes):
        self.focus_mode = mode
        self.pomo_end = time.time() + minutes * 60
        self.guard.start(mode)
        self.toast(mode.get("name", "Focus"), "%d min  ·  %s" % (minutes, focus.describe(mode).split("·", 1)[-1].strip()),
                   RED)
        self.update_menu()

    def stop_focus(self):
        """End the session by hand. Refused while a mode that forbids early stopping is running."""
        if self.focus_locked():
            self.toast("Focus is locked", "It ends when the timer runs out", ORANGE)
            return False
        self.end_focus()
        self.pulse(GRAY)
        return True

    def end_focus(self):
        self.guard.stop()
        self.pomo_end = None
        self.focus_mode = None
        self.update_menu() if self.menu_open else None

    def request_quit(self):
        if self.focus_locked():
            self.toast("Focus is locked", "Quit is available when it ends", ORANGE)
            return
        NSApp.terminate_(None)

    # ---- main loop -------------------------------------------------------

    def tick(self):
        if not self.screen_ok:
            return
        now = time.time()
        m = NSEvent.mouseLocation()
        x, y = m.x - self.cx, m.y - self.top
        w, h = self.size
        on_island = self.on_island = -w / 2 - 3 <= x <= w / 2 + self.ext + 3 and -h - 4 <= y <= 2
        self.pointer = (x, y)
        file_drag = self.watch_file_drag(now, x, y)
        hovered = None
        if self.menu_open:
            for which in (self.outer, self.inner):
                slot = which.slot_at(x, y)
                if slot is not None:
                    hovered = (which, slot)
                    break
            reach_x, reach_y = self.outer_reach if self.outer.visible else self.inner_reach
            in_ring = abs(x - self.ring_ext / 2) <= reach_x and -reach_y <= y <= 2
            if on_island or in_ring:
                self.menu_seen = now
            elif self.focus_dropdown is not None and self.focus_dropdown.visible:
                self.menu_seen = now               # the drop-down belongs to the ring
            elif now - self.menu_seen > 0.6:      # pointer wandered off: fold the buttons away
                self.close_menu()
        else:
            in_ring = False
        if hovered != self.hover:
            for which in (self.inner, self.outer):
                which.hover = hovered[1] if (hovered and hovered[0] is which) else None
                if which.visible:
                    which.update()
            self.hover = hovered
            self.refresh(now)
        # While the rings are open their whole area takes the mouse, so scrolling anywhere in it turns them.
        over_file = self.shelf_at(x, y)
        if over_file != self.shelf_hover:
            self.shelf_hover = over_file
            self.refresh(now)
        inside = (on_island or hovered is not None or in_ring or self.seeking is not None or self.drag_over
                  or self.dragging_out)
        if self.focus_dropdown is not None and self.focus_dropdown.visible:
            f = self.focus_dropdown.frame()         # the drop-down sits under this window: let clicks reach it
            if f.origin.x <= m.x <= f.origin.x + f.size.width and f.origin.y <= m.y <= f.origin.y + f.size.height:
                inside = False
        if inside:
            self.last_inside = now
        # Click-through everywhere except on the island and its buttons. While files are in the air the
        # window takes the mouse throughout, so macOS can hand it the drop if it is going to.
        self.panel.setIgnoresMouseEvents_(not (inside or file_drag))
        hover = now - self.last_inside < 0.3

        self.check_levels(now)
        self.ticks += 1
        if self.ticks % 20 == 0:
            self.watch_updates()
        if self.pomo_end and self.ticks % 6 == 0:
            self.guard.check_apps()
            blocked = self.guard.blocked
            if blocked and now - self.last_block_toast > 2.5:
                self.last_block_toast = now
                self.guard.blocked = None
                self.toast(blocked[0], "%s focus is on" % (self.focus_mode or {}).get("name", "Focus"), RED, 2.2)
        if self.ticks % 5 == 0 or self.mode is None:
            self.refresh(now)

        mode = "expanded" if (hover or self.menu_open or now < self.peek_until) else "compact"
        drawer = self.drawer_w()
        if drawer != self.ring_ext:
            self.layout_rings(drawer)               # the rings step aside for the drawer
        ext = drawer if mode == "expanded" else (SHELF_EAR if self.settings["shelf"] else 0.0)
        if (mode, ext) != self.shape_key:
            self.shape_key = (mode, ext)
            if mode == "expanded":
                self.set_shape(self.exp_w, self.exp_h, 20, bounce=mode != self.mode, ext=ext)
            else:
                self.set_shape(self.compact_w, self.nh, 11, bounce=False, ext=ext)
            self.mode = mode
            self.detail.setOpacity_(1 if mode == "expanded" else 0)
            self.drawer.setOpacity_(1 if mode == "expanded" else 0)
            self.ambient.setOpacity_(0 if mode == "expanded" else 1)   # shown larger below instead

    def refresh(self, now):
        """Pull monitor state into the layers and raise toasts on changes."""
        raw, S = self.monitors, self.settings
        mon = SimpleNamespace(cam=raw.cam and S["privacy"], mic=raw.mic and S["privacy"], ac=raw.ac,
                              batt=raw.batt, music=raw.music if S["music"] else None)
        music = mon.music
        playing = bool(music and music["playing"])
        track = (music["title"], music["artist"]) if playing else None
        snap = (mon.cam, mon.mic, mon.ac, track)
        if self.prev is not None and mon.batt is not None:
            p_cam, p_mic, p_ac, p_track = self.prev
            if mon.cam != p_cam:
                self.toast("Camera in use" if mon.cam else "Camera off",
                           "An app started the camera" if mon.cam else "No app is using it",
                           GREEN if mon.cam else GRAY, 2.5)
            elif mon.mic != p_mic:
                self.toast("Microphone in use" if mon.mic else "Microphone off",
                           "An app is listening" if mon.mic else "No app is using it",
                           ORANGE if mon.mic else GRAY, 2.5)
            elif p_ac is not None and mon.ac != p_ac and S["power"]:
                self.toast("Charging" if mon.ac else "On battery", "%d%% charged" % mon.batt, YELLOW)
            elif track and track != p_track:
                self.toast(track[0], track[1] or music["app"], PINK)
        self.prev = snap

        bt = raw.bt
        if bt is not None:
            if self.prev_bt is not None and S["bluetooth"]:
                for name in bt.keys() - self.prev_bt.keys():
                    self.toast(name, "Connected" + ("  ·  %s" % bt[name] if bt[name] else ""), BLUE)
                for name in self.prev_bt.keys() - bt.keys():
                    self.toast(name, "Disconnected", GRAY)
            self.prev_bt = bt

        pomo_left = None
        if self.pomo_end:
            pomo_left = self.pomo_end - now
            if pomo_left <= 0:
                name = (self.focus_mode or {}).get("name", "Focus")
                self.end_focus()
                pomo_left = None
                self.toast(name + " complete", "Time for a break", RED, 5.0)
        pomo_str = "%d:%02d" % divmod(int(pomo_left), 60) if pomo_left else None

        if self.timer_end and now >= self.timer_end:
            self.timer_end = None
            self.toast("Time's up", "The timer has finished", ORANGE, 6.0)
            sound = NSSound.soundNamed_("Glass")
            if sound is not None:
                sound.play()
            self.update_menu()
        timer_str = self.countdown(self.timer_end) if self.timer_end else None
        watch_str = self.elapsed(self.stopwatch_start) if self.stopwatch_start else None
        ear_str = pomo_str or timer_str or watch_str      # what the right ear counts

        # Next calendar event: announce it ten minutes ahead and when it starts.
        event = raw.event if S["calendar"] else None
        if event is not None:
            minutes = (event["start"] - now) / 60.0
            for kind, due, text in (("soon", 0 < minutes <= 10, "Starts in %d min" % max(1, round(minutes))),
                                    ("now", -1 < minutes <= 0, "Starting now")):
                if due and (event["id"], kind) not in self.event_alerts:
                    self.event_alerts.add((event["id"], kind))
                    self.toast(event["title"], text, BLUE, 6.0)

        if now >= self.peek_until:
            self.toast_text = None

        # Left ear: clock, replaced by privacy dots while camera / microphone are live.
        live = mon.cam or mon.mic
        both = mon.cam and mon.mic
        self.set_text(self.ear_time, self.clock())
        self.ear_time.setOpacity_(0 if live else 1)
        self.cam_dot.setPosition_((self.lx - (7 if both else 0), self.mid))
        self.mic_dot.setPosition_((self.lx + (7 if both else 0), self.mid))
        self.cam_dot.setOpacity_(1 if mon.cam else 0)
        self.mic_dot.setOpacity_(1 if mon.mic else 0)

        # Right ear: countdown > music bars > battery glyph.
        self.set_text(self.ear_text, ear_str or "")
        show_bars = playing and not ear_str
        self.bars.setOpacity_(1 if show_bars else 0)
        self.batt_glyph.setOpacity_(0 if (ear_str or show_bars or mon.batt is None) else 1)
        level = (mon.batt or 0) / 100.0
        batt_color = GREEN if mon.ac else (RED if level <= 0.2 else WHITE)
        self.batt_fill.setBounds_(NSMakeRect(0, 0, max(2.0, 19 * level), 7))
        self.batt_fill.setBackgroundColor_(batt_color.CGColor())

        # Expanded: clock block.
        self.set_text(self.time_text, self.clock())
        self.set_text(self.date_text, time.strftime("%a, %b %-d").upper())

        # Expanded: middle column.
        pointed = self.hovered_item() if self.menu_open else None
        hud_on = bool(self.hud and now < self.hud[1]) and pointed is None and not self.drag_over
        hud_level = 0.0
        self.draw_shelf()
        if self.drag_over:
            count = len(S["shelf"])
            title, sub = "Drop to keep on the Shelf", "%d item%s there now" % (count, "" if count == 1 else "s")
        elif self.shelf_hover == "clear":
            title, sub = "Clear the Shelf", "Forgets all %d  ·  the files stay where they are" % len(S["shelf"])
        elif self.shelf_hover is not None and self.shelf_hover < len(S["shelf"]):
            path = S["shelf"][self.shelf_hover]
            title, sub = os.path.basename(path.rstrip("/")) or path, "Drag out  ·  click to reveal"
        elif pointed is not None:               # the island doubles as the buttons' tooltip
            title, sub = pointed.label, pointed.status()
        elif hud_on:
            if self.hud[0] == "brightness":
                hud_level = raw.brightness or 0.0
                title = "Brightness  %d%%" % round(hud_level * 100)
            else:
                hud_level = 0.0 if raw.muted else (raw.volume or 0.0)
                title = "Muted" if raw.muted else "Volume  %d%%" % round(hud_level * 100)
            sub = ""
        elif self.menu_open:
            opened = next((e for e in self.inner.items if e.key == self.open_entry), None)
            title = opened.label if opened else ("Settings" if self.menu_page == "settings" else "Dynamic Island")
            scrolling = self.outer if opened else self.inner
            sub = "Scroll for more  ·  %d buttons" % len(scrolling.items) if scrolling.scrolls() \
                else ("Point at a button" if opened else "Choose a category")
        elif self.toast_text:
            title, sub = self.toast_text
        elif live:
            title = " + ".join(n for n, on in (("Camera", mon.cam), ("Microphone", mon.mic)) if on) + " in use"
            sub = "Live now"
        elif music:
            title, sub = music["title"], music["artist"] or music["app"]
            if self.seeking is not None:        # while dragging, the subtitle shows where you'd land
                clock = lambda t: "%d:%02d:%02d" % (t // 3600, t % 3600 // 60, t % 60) if t >= 3600 \
                    else "%d:%02d" % (t // 60, t % 60)
                sub = "%s / %s" % (clock(self.seeking * music["duration"]), clock(music["duration"]))
        elif pomo_str:
            title, sub = (self.focus_mode or {}).get("name", "Focus"), "%s remaining" % pomo_str
        elif timer_str:
            title, sub = "Timer", "%s remaining" % timer_str
        elif watch_str:
            title, sub = "Stopwatch", watch_str
        elif event is not None and event["start"] - now <= 3600:        # an event within the hour
            title = event["title"]
            sub = calendar_events.describe(event, now, lambda t: time.strftime(
                "%H:%M" if S["clock24"] else "%-I:%M %p", time.localtime(t)))
        else:
            title = _greeting()
            if S["stats"] and raw.cpu is not None and raw.mem is not None:
                stats = [("CPU", raw.cpu), ("GPU", raw.gpu), ("RAM", raw.mem)]
                # Thin spaces round the dots keep all three on one line.
                sub = "\u2009·\u2009".join("%s %d%%" % (name, round(v * 100)) for name, v in stats if v is not None)
            else:
                sub = "All quiet"
        controls = bool(music and music.get("control"))
        media = bool(music)                 # media layout: both rows move up, progress bar underneath
        if media != self.media_layout:
            self.media_layout = media
            for layer, y in zip((self.title_text, self.sub_text), self.media_rows if media else self.rows):
                f = layer.frame()
                _no_anim(lambda layer=layer, f=f, y=y: layer.setFrame_(
                    NSMakeRect(f.origin.x, y - f.size.height / 2, f.size.width, f.size.height)))
        duration = music.get("duration", 0) if music else 0
        show_progress = bool(duration) and not hud_on
        self.progress.setOpacity_(1 if show_progress else 0)
        if show_progress:
            fraction = self.seeking if self.seeking is not None else monitors.position_now(music) / duration
            width = self.prog_w * fraction

            def place():
                self.prog_fill.setBounds_(NSMakeRect(0, 0, max(3.0, width), 3))
                self.prog_knob.setPosition_((self.prog_x + width, self.prog_y))
                self.prog_knob.setOpacity_(1 if self.can_seek() else 0)
            _no_anim(place)
        if controls != self.sub_is_narrow:
            self.sub_is_narrow = controls
            f = self.sub_text.frame()
            width = self.sub_narrow if controls else self.sub_wide
            _no_anim(lambda: self.sub_text.setFrame_(NSMakeRect(f.origin.x, f.origin.y, width, f.size.height)))
        self.set_text(self.title_text, title)
        self.set_text(self.sub_text, sub)
        self.music_btns.setOpacity_(1 if (controls and not hud_on) else 0)
        self.bar.setOpacity_(1 if hud_on else 0)
        _no_anim(lambda: self.bar_fill.setBounds_(NSMakeRect(0, 0, max(4.0, self.bar_w * hud_level), 4)))
        self.set_symbol(self.play_btn, "pause.fill" if playing else "play.fill", WHITE)

        # Expanded: battery ring.
        self.ring.setStrokeEnd_(level)
        self.ring.setStrokeColor_(batt_color.CGColor())
        self.set_text(self.ring_text, "" if mon.batt is None else str(mon.batt))
