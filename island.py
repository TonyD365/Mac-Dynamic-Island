"""The island window: a borderless, immovable, click-through panel pinned to the notch."""
import math
import time
from types import SimpleNamespace

from AppKit import (
    NSApp, NSApplicationDidChangeScreenParametersNotification, NSBackingStoreBuffered, NSColor, NSEvent, NSFont,
    NSFontDescriptorSystemDesignRounded, NSFontWeightBold, NSFontWeightMedium, NSFontWeightSemibold, NSImage,
    NSImageSymbolConfiguration, NSMainMenuWindowLevel, NSMakePoint, NSMakeRect, NSNull, NSDistributedNotificationCenter, NSNotificationCenter, NSOpenPanel, NSPanel, NSRunLoop,
    NSRunLoopCommonModes, NSTimer, NSValue, NSView, NSWindowCollectionBehaviorCanJoinAllSpaces,
    NSWindowCollectionBehaviorFullScreenAuxiliary, NSWindowCollectionBehaviorIgnoresCycle,
    NSWindowCollectionBehaviorStationary, NSWindowStyleMaskBorderless, NSWindowStyleMaskNonactivatingPanel,
)
from Foundation import NSUserName
from Quartz import (
    CABasicAnimation, CAGradientLayer, CAKeyframeAnimation, CAMediaTimingFunction, CALayer, CAShapeLayer, CASpringAnimation, CATextLayer, CATransaction,
    CACurrentMediaTime, CGPathAddArc, CGPathAddLineToPoint, CGPathCloseSubpath, CGPathCreateMutable, CGPathMoveToPoint,
    kCALayerMaxXMinYCorner, kCALayerMinXMinYCorner,
)

import actions
import autostart
import backgrounds
import custom_buttons
import focus
import focus_editor
import focus_panel
import lockscreen
import monitors
import screen as screen_util
import settings

# Size limits of the island, in points. Every state is clamped to these.
EAR = 46.0            # width on each side of the notch in the always-visible compact state
MAX_W = 300.0         # expanded width (also capped at 30% of the built-in screen)
MAX_H = 80.0          # expanded height
ROW_SPACE = 44.0      # height added below the notch when expanded
SHOULDER = 6.0        # radius of the concave corners where the island meets the screen edge
GLOW_PAD = 40.0       # transparent margin around the island for the glow
MENU_R = 18.0         # radius of the round action buttons that fan out around the island
MENU_SLOTS = 7        # buttons visible at once; more are reached by scrolling the ring
MENU_GAP = 10.0       # space between the island and the action buttons

WHITE = NSColor.whiteColor()
GRAY = NSColor.colorWithWhite_alpha_(0.60, 1.0)
FAINT = NSColor.colorWithWhite_alpha_(1.0, 0.14)
GREEN = NSColor.systemGreenColor()
ORANGE = NSColor.systemOrangeColor()
PINK = NSColor.systemPinkColor()
YELLOW = NSColor.systemYellowColor()
RED = NSColor.systemRedColor()
BLUE = NSColor.systemBlueColor()
PURPLE = NSColor.systemPurpleColor()
BLACK = NSColor.blackColor()
HOVER = NSColor.colorWithWhite_alpha_(0.24, 1.0)


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

    def scrollWheel_(self, event):
        self.on_scroll(event.scrollingDeltaY(), event.hasPreciseScrollingDeltas())


def _no_anim(fn):
    CATransaction.begin()
    CATransaction.setDisableActions_(True)
    fn()
    CATransaction.commit()


def _font(size, weight=NSFontWeightMedium, rounded=False):
    font = NSFont.monospacedDigitSystemFontOfSize_weight_(size, weight)
    if rounded:
        desc = font.fontDescriptor().fontDescriptorWithDesign_(NSFontDescriptorSystemDesignRounded)
        font = (desc and NSFont.fontWithDescriptor_size_(desc, size)) or font
    return font


def _spring(key_path, old, new, damping):
    a = CASpringAnimation.animationWithKeyPath_(key_path)
    a.setFromValue_(old)
    a.setToValue_(new)
    a.setMass_(1.0)
    a.setStiffness_(260.0)
    a.setDamping_(damping)
    a.setDuration_(a.settlingDuration())
    return a


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
        self.editor.on_change = self.update_menu
        self.guard = focus.Guard()
        self.focus_mode = None        # the mode of the running focus session
        self.focus_editor = focus_editor.Editor()
        self.focus_editor.values = self.settings
        self.focus_dropdown = None    # built once the island's window exists
        self.hidden_slots = ()        # ring buttons tucked away while the focus drop-down covers them
        self.last_block_toast = 0.0
        self.menu_open = False
        self.menu_page = "main"
        self.menu_seen = 0.0
        self.hover_btn = None
        self.levels = None        # last seen (volume, muted, brightness)
        self.hud = None           # ("volume" | "brightness", visible-until time)
        self.prev_bt = None
        self.menu_offset = 0      # how far the button ring has been rotated
        self.scroll_acc = 0.0
        self.last_rotate = 0.0
        self.on_island = False    # pointer is over the island itself
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
        self.welcome_soon(1.2)          # also greets when the island starts at login
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
        # Action buttons hug the expanded island: one beside each end, one under each corner, three below.
        hx, hy, d = self.exp_w / 2, self.exp_h, MENU_GAP + MENU_R
        self.menu_pos = [(-hx - d, -24.0), (-hx - 12, -hy - 12), (-hx * 0.56, -hy - d), (0.0, -hy - d),
                         (hx * 0.56, -hy - d), (hx + 12, -hy - 12), (hx + d, -24.0)]
        # Leave room for the buttons' spring overshoot, or the window edge clips them mid-bounce.
        self.menu_half_w = (hx + d) * 1.1 + MENU_R + 10
        self.ring_half_w = hx + d + MENU_R + 6      # the area the open ring occupies
        self.ring_depth = hy + d + MENU_R + 6
        self.menu_depth = (hy + d) * 1.1 + MENU_R + 10
        self.win_w = 2 * math.ceil(max(hx + GLOW_PAD, self.menu_half_w))
        self.win_h = math.ceil(max(hy + GLOW_PAD, self.menu_depth))
        self.panel.setFrame_display_(
            NSMakeRect(self.cx - self.win_w / 2, self.top - self.win_h, self.win_w, self.win_h), True)
        self.build_layers()
        self.screen_ok = True
        self.mode = None
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
        self.menu_home = (0.0, -self.nh / 2)
        self.menu_layers = []
        self.menu_open = False
        self.hover_btn = None
        for _ in self.menu_pos:
            b = CALayer.layer()
            b.setBounds_(NSMakeRect(0, 0, 2 * MENU_R, 2 * MENU_R))
            b.setCornerRadius_(MENU_R)
            b.setBackgroundColor_(black)
            b.setBorderWidth_(1.0)
            b.setBorderColor_(FAINT.CGColor())
            b.setPosition_(self.menu_home)
            b.setOpacity_(0)
            menu_root.addSublayer_(b)
            self.menu_layers.append((b, self.symbol_layer(b, MENU_R, MENU_R)))

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
        divider.setFrame_(NSMakeRect(left + 74, base - 38, 1, 30))
        divider.setCornerRadius_(0.5)
        divider.setBackgroundColor_(FAINT.CGColor())
        self.detail.addSublayer_(divider)

        mx = left + 84                      # middle column
        ring_x = w / 2 - 30
        m_right = ring_x - 22
        self.title_text = self.text_layer(self.detail, mx, base - 15, m_right - mx, 12, WHITE, "left",
                                          NSFontWeightSemibold)
        self.sub_wide = m_right - mx
        self.sub_narrow = m_right - mx - 3 * 22  # leave room for the music controls
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

        self.music_btns = self.group(self.detail)
        bx = m_right - 9
        has_music = lambda: self.monitors.music is not None
        self.next_btn = self.button(self.music_btns, bx, base - 33, "forward.fill",
                                    lambda: self.player("next track"), has_music)
        self.play_btn = self.button(self.music_btns, bx - 22, base - 33, "play.fill",
                                    lambda: self.player("playpause"), has_music)
        self.prev_btn = self.button(self.music_btns, bx - 44, base - 33, "backward.fill",
                                    lambda: self.player("previous track"), has_music)

        # Battery ring with the percentage inside
        ring_y = base - 23
        ring_r = 12.0
        circle = CGPathCreateMutable()
        CGPathAddArc(circle, None, 0, 0, ring_r, math.pi / 2, math.pi / 2 - 2 * math.pi, True)
        self.ring = None
        for color in (FAINT, WHITE):
            ring = CAShapeLayer.layer()
            ring.setPath_(circle)
            ring.setFillColor_(None)
            ring.setStrokeColor_(color.CGColor())
            ring.setLineWidth_(2.5)
            ring.setLineCap_("round")
            ring.setPosition_((ring_x, ring_y))
            self.detail.addSublayer_(ring)
            self.ring = ring
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

    def set_shape(self, w, h, radius, bounce=True):
        # Bounce only when growing. When shrinking, a critically damped spring settles without
        # undershooting, so the island never gets smaller than the notch it sits on.
        damping = 19.0 if bounce else 34.0
        self.size = (w, h)
        new = NSMakeRect(-w / 2, -h, w, h)
        for layer in (self.glow, self.island):
            old = (layer.presentationLayer() or layer).bounds()
            _no_anim(lambda layer=layer: layer.setBounds_(new))
            layer.setCornerRadius_(radius)
            layer.addAnimation_forKey_(
                _spring("bounds", NSValue.valueWithRect_(old), NSValue.valueWithRect_(new), damping), "shape")
        for sign, s in self.shoulders:
            old_x = (s.presentationLayer() or s).position().x
            new_x = sign * w / 2
            _no_anim(lambda s=s: s.setPosition_((new_x, 0)))
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
        if self.menu_open:
            for i, (bx, by) in enumerate(self.menu_pos):
                if (x - bx) ** 2 + (y - by) ** 2 <= (MENU_R + 2) ** 2:
                    item = self.menu_items()[i]
                    if item is not None:
                        item.action()
                        self.update_menu()
                        self.refresh(time.time())
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

    def menu_items(self):
        """What each of the visible slots shows right now, left to right (None = empty slot)."""
        items = self.all_items()
        if len(items) <= MENU_SLOTS:
            return items + [None] * (MENU_SLOTS - len(items))
        return [items[(self.menu_offset + i) % len(items)] for i in range(MENU_SLOTS)]

    def rotate_menu(self, step):
        """Turn the ring one button: every button glides to its neighbour's slot.

        Each button starts from wherever its neighbour is *on screen right now*, so a new step
        taken while the previous one is still moving carries on smoothly instead of snapping back.
        """
        count = len(self.all_items())
        if count <= MENU_SLOTS:
            return
        shown = [(b.presentationLayer() or b).position() for b, _ in self.menu_layers]
        self.menu_offset = (self.menu_offset + step) % count
        self.update_menu()
        ease = CAMediaTimingFunction.functionWithName_("easeOut")
        for i, (b, _) in enumerate(self.menu_layers):
            source = i + step
            entering = not 0 <= source < MENU_SLOTS
            if entering:        # slides in from just past the end of the ring, fading up
                (x, y), (nx, ny) = self.menu_pos[i], self.menu_pos[i - step]
                start = NSMakePoint(x + (x - nx) * 0.6, y + (y - ny) * 0.6)
            else:
                start = shown[source]
            move = CABasicAnimation.animationWithKeyPath_("position")
            move.setFromValue_(NSValue.valueWithPoint_(start))
            move.setToValue_(NSValue.valueWithPoint_(NSMakePoint(*self.menu_pos[i])))
            move.setDuration_(0.2)
            move.setTimingFunction_(ease)
            b.addAnimation_forKey_(move, "move")
            if entering:
                fade = CABasicAnimation.animationWithKeyPath_("opacity")
                fade.setFromValue_(0.0)
                fade.setToValue_(1.0)
                fade.setDuration_(0.2)
                b.addAnimation_forKey_(fade, "fade")
            else:
                b.removeAnimationForKey_("fade")
        self.refresh(time.time())

    def all_items(self):
        """Every button of the current page, in ring order. On the lock screen only harmless ones remain:
        nothing that opens apps or files, runs commands or changes settings."""
        items = self.page_items()
        return [i for i in items if i.safe] if self.locked else items

    def page_items(self):
        S, A, raw = self.settings, self.actions, self.monitors
        item = lambda symbol, label, status, action, on=None, safe=False: SimpleNamespace(
            symbol=symbol, label=label, status=status, action=action, on=on, safe=safe)

        def toggle(symbol, label, key):
            def flip():
                S[key] = not S[key]
                settings.save(S)
            return item(symbol, label, lambda: "On" if S[key] else "Off", flip, lambda: S[key])

        if self.menu_page == "settings":
            def cycle_background():
                S["background"] = backgrounds.next_choice(S)
                settings.save(S)
                self.apply_background()

            def cycle_dim():
                S["background_dim"] = backgrounds.next_dim(S["background_dim"])
                settings.save(S)
                self.apply_background()

            lock = toggle("lock.display", "Show on Lock Screen", "lockscreen")
            lock.status = lambda: ("On" if S["lockscreen"] else "Off") + "  ·  applies after restart"
            return [
                item("chevron.left", "Back", lambda: "Return to actions", lambda: self.set_page("main")),
                item("plus", "Custom Buttons",
                     lambda: "%d added  ·  click to edit" % len(S["custom_buttons"]), self.edit_custom_buttons),
                toggle("video.fill", "Camera & Mic Alerts", "privacy"),
                toggle("music.note", "Now Playing", "music"),
                toggle("bolt.fill", "Power Alerts", "power"),
                toggle("headphones", "Bluetooth Alerts", "bluetooth"),
                toggle("slider.horizontal.3", "Volume & Brightness Bar", "hud"),
                toggle("speaker.wave.2.fill", "Scroll to Change Volume", "scroll_volume"),
                toggle("cpu", "System Stats", "stats"),
                toggle("clock.fill", "24-Hour Clock", "clock24"),
                item("hourglass", "Focus Modes",
                     lambda: "%d modes  ·  click to edit" % len(S["focus_modes"]), self.edit_focus_modes),
                toggle("sparkles", "Glow Effects", "glow"),
                toggle("hand.wave.fill", "Welcome Animation", "welcome"),
                item("photo.fill", "Background", lambda: "%s  ·  click for next" % backgrounds.label(S),
                     cycle_background, lambda: bool(S["background"])),
                item("folder.fill", "Choose Image…", lambda: "Use your own picture", self.choose_image),
                item("circle.righthalf.filled", "Dimming",
                     lambda: "%s  ·  click to change" % backgrounds.dim_label(S["background_dim"]), cycle_dim),
                lock,
                item("power", "Launch at Login",
                     lambda: "On" if autostart.is_enabled() else "Off",
                     lambda: autostart.set_enabled(not autostart.is_enabled()), autostart.is_enabled),
                item("xmark", "Quit Dynamic Island", lambda: "Close the island completely", self.request_quit),
            ]

        def toggle_mute():
            raw.muted = not raw.muted          # shown at once; the next poll confirms it
            monitors.set_mute(raw.muted)

        return [
            item("timer", "Focus",
                 lambda: ("%s  ·  running" % (self.focus_mode or {}).get("name", "Focus")) if self.pomo_end
                 else "Choose a focus mode",
                 self.show_focus_dropdown, lambda: bool(self.pomo_end)),
            item("speaker.slash.fill", "Mute", lambda: "Muted" if raw.muted else "Sound on",
                 toggle_mute, lambda: bool(raw.muted), safe=True),
            item("circle.lefthalf.filled", "Dark Mode", lambda: "On" if A.is_dark() else "Off",
                 A.toggle_dark, A.is_dark),
            item("cup.and.saucer.fill", "Keep Awake", lambda: "On" if A.is_awake() else "Off",
                 A.toggle_awake, A.is_awake, safe=True),
            item("lock.fill", "Lock Screen", lambda: "Lock this Mac now", self.lock_screen),
            item("moon.zzz.fill", "Sleep Display", lambda: "Turn the screen off now", self.sleep_display, safe=True),
            item("gearshape.fill", "Settings", lambda: "Customize the island", lambda: self.set_page("settings")),
            # Past the seventh slot: scroll the ring to reach these.
            item("camera.viewfinder", "Screenshot", lambda: "Drag an area  ·  copied to clipboard", self.screenshot),
            item("eyedropper", "Color Picker", lambda: "Pick a colour  ·  copies its hex code", self.pick_color),
            item("arrow.down.to.line", "Downloads", lambda: "Open the Downloads folder", self.open_downloads),
            item("gauge.medium", "Activity Monitor", lambda: "See what is using the Mac",
                 lambda: self.launch("Activity Monitor")),
            item("plus.forwardslash.minus", "Calculator", lambda: "Open Calculator", lambda: self.launch("Calculator")),
        ] + [
            item(b.get("icon", "star.fill"), b.get("name", "Custom"), lambda b=b: custom_buttons.describe(b),
                 lambda b=b: self.run_custom(b))
            for b in S["custom_buttons"]
        ]

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

    def open_downloads(self):
        self.close_menu()
        self.actions.open_downloads()

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
        if self.menu_open and not self.on_island:
            notch = 12.0 if precise else 1.0
            self.scroll_acc = max(-notch, min(notch, self.scroll_acc + delta))
            now = time.time()
            # At most one step every 80 ms: a fast flick turns the ring steadily instead of
            # firing dozens of overlapping steps.
            if abs(self.scroll_acc) >= notch and now - self.last_rotate >= 0.08:
                self.last_rotate = now
                self.rotate_menu(1 if self.scroll_acc < 0 else -1)
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

    def set_page(self, page):
        self.menu_page = page
        self.menu_offset = 0
        for b, _ in self.menu_layers:      # little pop so the swap reads as a new set of buttons
            a = CAKeyframeAnimation.animationWithKeyPath_("transform.scale")
            a.setValues_([1.0, 0.72, 1.06, 1.0])
            a.setDuration_(0.32)
            b.addAnimation_forKey_(a, "pop")

    def update_menu(self):
        for i, item in enumerate(self.menu_items()):
            b, icon = self.menu_layers[i]
            b.setHidden_(item is None)
            if item is None:
                continue
            active = bool(item.on and item.on())
            hovered = i == self.hover_btn
            fill = (WHITE if active else (HOVER if hovered else BLACK))
            b.setBackgroundColor_(fill.CGColor())
            b.setBorderColor_((WHITE if hovered else FAINT).CGColor())
            self.set_symbol(icon, item.symbol, BLACK if active else WHITE, 14.0)

    def open_menu(self):
        self.menu_open = True
        self.menu_page = "main"
        self.menu_offset = 0
        self.scroll_acc = 0.0
        self.menu_seen = time.time()
        self.update_menu()
        self.move_menu(True)

    def close_menu(self):
        self.menu_open = False
        if self.focus_dropdown is not None and self.focus_dropdown.visible:
            self.focus_dropdown.close()
        self.hover_btn = None
        self.move_menu(False)

    def move_menu(self, opening):
        start = CACurrentMediaTime()
        for i, (b, _) in enumerate(self.menu_layers):
            target = self.menu_pos[i] if opening else self.menu_home
            pres = b.presentationLayer() or b
            old_pos, old_opacity = pres.position(), pres.opacity()
            new_opacity = 1.0 if opening else 0.0

            def apply(b=b, target=target):
                b.setPosition_(target)
                b.setOpacity_(new_opacity)
            _no_anim(apply)
            begin = start + (i * 0.028 if opening else 0.0)   # staggered fan-out, left to right
            move = _spring("position", NSValue.valueWithPoint_(old_pos),
                           NSValue.valueWithPoint_(NSMakePoint(*target)), 22.0 if opening else 34.0)
            fade = CABasicAnimation.animationWithKeyPath_("opacity")
            fade.setFromValue_(old_opacity)
            fade.setToValue_(new_opacity)
            fade.setDuration_(0.16)
            scale = CABasicAnimation.animationWithKeyPath_("transform.scale")
            scale.setFromValue_(0.4 if opening else 1.0)
            scale.setToValue_(1.0 if opening else 0.4)
            scale.setDuration_(0.22)
            for key, a in (("move", move), ("fade", fade), ("scale", scale)):
                a.setBeginTime_(begin)
                a.setFillMode_("backwards")
                b.addAnimation_forKey_(a, key)

    def clock(self):
        return time.strftime("%H:%M" if self.settings["clock24"] else "%-I:%M")

    def player(self, command):
        m = self.monitors.music
        if m:
            monitors.player_command(m["app"], command)

    # ---- focus sessions ----

    def show_focus_dropdown(self):
        """Open the drop-down just under the Focus button (and clear of the island itself)."""
        if self.focus_dropdown is None:
            self.focus_dropdown = focus_panel.FocusPanel(self)
        slot = next((i for i, it in enumerate(self.menu_items()) if it is not None and it.symbol == "timer"), 0)
        bx, by = self.menu_pos[slot]
        top = min(by - MENU_R - 8, -self.exp_h - 10)
        half = focus_panel.WIDTH / 2
        # Ring buttons the drop-down would sit under are hidden while it is open.
        self.hidden_slots = tuple(i for i, (x, y) in enumerate(self.menu_pos)
                                  if i != slot and abs(x - bx) < half + MENU_R and y - MENU_R < top)
        for i in self.hidden_slots:
            self.menu_layers[i][0].setOpacity_(0)
        self.focus_dropdown.show(self.cx + bx, self.top + top)

    def focus_panel_closed(self):
        for i in self.hidden_slots:
            self.menu_layers[i][0].setOpacity_(1 if self.menu_open else 0)
        self.hidden_slots = ()
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
        on_island = self.on_island = abs(x) <= w / 2 + 3 and -h - 4 <= y <= 2
        hovered = None
        if self.menu_open:
            items = self.menu_items()
            for i, (bx, by) in enumerate(self.menu_pos):
                if items[i] is not None and (x - bx) ** 2 + (y - by) ** 2 <= (MENU_R + 2) ** 2:
                    hovered = i
            if on_island or (abs(x) <= self.menu_half_w and -self.menu_depth <= y <= 2):
                self.menu_seen = now
            elif self.focus_dropdown is not None and self.focus_dropdown.visible:
                self.menu_seen = now               # the drop-down belongs to the ring
            elif now - self.menu_seen > 0.6:      # pointer wandered off: fold the buttons away
                self.close_menu()
        if hovered != self.hover_btn:
            self.hover_btn = hovered
            self.update_menu()
            self.refresh(now)
        # While the ring is open its whole area takes the mouse, so scrolling anywhere in it turns the ring.
        in_ring = self.menu_open and abs(x) <= self.ring_half_w and -self.ring_depth <= y <= 2
        inside = on_island or hovered is not None or in_ring
        if self.focus_dropdown is not None and self.focus_dropdown.visible:
            f = self.focus_dropdown.frame()         # the drop-down sits under this window: let clicks reach it
            if f.origin.x <= m.x <= f.origin.x + f.size.width and f.origin.y <= m.y <= f.origin.y + f.size.height:
                inside = False
        if inside:
            self.last_inside = now
        # Click-through everywhere except on the island and its buttons.
        self.panel.setIgnoresMouseEvents_(not inside)
        hover = now - self.last_inside < 0.3

        self.check_levels(now)
        self.ticks += 1
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
        if mode != self.mode:
            self.mode = mode
            if mode == "expanded":
                self.set_shape(self.exp_w, self.exp_h, 20)
            else:
                self.set_shape(self.compact_w, self.nh, 11, bounce=False)
            self.detail.setOpacity_(1 if mode == "expanded" else 0)
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
                self.toast(track[0], track[1], PINK)
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
        self.set_text(self.ear_text, pomo_str or "")
        show_bars = playing and not pomo_str
        self.bars.setOpacity_(1 if show_bars else 0)
        self.batt_glyph.setOpacity_(0 if (pomo_str or show_bars or mon.batt is None) else 1)
        level = (mon.batt or 0) / 100.0
        batt_color = GREEN if mon.ac else (RED if level <= 0.2 else WHITE)
        self.batt_fill.setBounds_(NSMakeRect(0, 0, max(2.0, 19 * level), 7))
        self.batt_fill.setBackgroundColor_(batt_color.CGColor())

        # Expanded: clock block.
        self.set_text(self.time_text, self.clock())
        self.set_text(self.date_text, time.strftime("%a, %b %-d").upper())

        # Expanded: middle column.
        hud_on = bool(self.hud and now < self.hud[1]) and not (self.menu_open and self.hover_btn is not None)
        hud_level = 0.0
        if self.menu_open and self.hover_btn is not None:      # the island doubles as the buttons' tooltip
            item = self.menu_items()[self.hover_btn]
            title, sub = item.label, item.status()
        elif hud_on:
            if self.hud[0] == "brightness":
                hud_level = raw.brightness or 0.0
                title = "Brightness  %d%%" % round(hud_level * 100)
            else:
                hud_level = 0.0 if raw.muted else (raw.volume or 0.0)
                title = "Muted" if raw.muted else "Volume  %d%%" % round(hud_level * 100)
            sub = ""
        elif self.menu_open:
            count = len(self.all_items())
            title = "Settings" if self.menu_page == "settings" else "Actions"
            sub = "Scroll for more  ·  %d buttons" % count if count > MENU_SLOTS else "Point at a button"
        elif self.toast_text:
            title, sub = self.toast_text
        elif live:
            title = " + ".join(n for n, on in (("Camera", mon.cam), ("Microphone", mon.mic)) if on) + " in use"
            sub = "Live now"
        elif music:
            title, sub = music["title"], music["artist"]
        elif pomo_str:
            title, sub = (self.focus_mode or {}).get("name", "Focus"), "%s remaining" % pomo_str
        else:
            title = _greeting()
            if S["stats"] and raw.cpu is not None and raw.mem is not None:
                sub = "CPU %d%%  ·  Memory %d%%" % (round(raw.cpu * 100), round(raw.mem * 100))
            else:
                sub = "All quiet"
        if bool(music) != self.sub_is_narrow:
            self.sub_is_narrow = bool(music)
            f = self.sub_text.frame()
            width = self.sub_narrow if music else self.sub_wide
            _no_anim(lambda: self.sub_text.setFrame_(NSMakeRect(f.origin.x, f.origin.y, width, f.size.height)))
        self.set_text(self.title_text, title)
        self.set_text(self.sub_text, sub)
        self.music_btns.setOpacity_(1 if (music and not hud_on) else 0)
        self.bar.setOpacity_(1 if hud_on else 0)
        _no_anim(lambda: self.bar_fill.setBounds_(NSMakeRect(0, 0, max(4.0, self.bar_w * hud_level), 4)))
        self.set_symbol(self.play_btn, "pause.fill" if playing else "play.fill", WHITE)

        # Expanded: battery ring.
        self.ring.setStrokeEnd_(level)
        self.ring.setStrokeColor_(batt_color.CGColor())
        self.set_text(self.ring_text, "" if mon.batt is None else str(mon.batt))
