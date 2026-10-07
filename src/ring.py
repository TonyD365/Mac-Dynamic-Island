"""A ring of round buttons that hugs the island: where the buttons sit, how they move, what was hit.

The island uses two of these. The inner ring holds the categories; choosing one opens the outer
ring, further out, with that category's buttons.
"""
import math

from AppKit import NSMakePoint, NSMakeRect, NSValue
from Quartz import CABasicAnimation, CACurrentMediaTime, CAKeyframeAnimation, CALayer, CAMediaTimingFunction

from ui import BLACK, FAINT, HOVER, WHITE, no_anim, spring

RADIUS = 18.0           # of one button
SIDE_Y = -24.0          # the first and last button sit beside the island, level with the menu bar


def positions(half_w, depth, offset, count):
    """`count` points spread evenly along the path that runs `offset` outside the expanded island:
    down its left side, round the corner, along the bottom, round the other corner and up again.
    (0, 0) is the island's top-centre and y is negative downward."""
    side = max(0.0, depth + SIDE_Y)             # straight run beside the island
    arc = math.pi / 2 * offset
    bottom = 2 * half_w
    total = 2 * side + 2 * arc + bottom

    def at(s):
        if s <= side:
            return -half_w - offset, SIDE_Y - s
        s -= side
        if s <= arc:
            a = s / offset
            return -half_w - offset * math.cos(a), -depth - offset * math.sin(a)
        s -= arc
        if s <= bottom:
            return -half_w + s, -depth - offset
        s -= bottom
        if s <= arc:
            a = s / offset
            return half_w + offset * math.sin(a), -depth - offset * math.cos(a)
        s -= arc
        return half_w + offset, -depth + s

    if count == 1:
        return [at(total / 2)]
    return [at(total * i / (count - 1)) for i in range(count)]


class Ring:
    def __init__(self, island, parent, slot_positions, home):
        self.island = island
        self.pos = slot_positions
        self.slots = len(slot_positions)
        self.home = home                # where the buttons hide when the ring is closed
        self.items = []                 # every item, in ring order; more than `slots` means it scrolls
        self.offset = 0
        self.hover = None               # slot under the pointer
        self.selected = None            # key of the item shown as "open" (a category whose ring is out)
        self.visible = False
        self.hidden = ()                # slots tucked away while a drop-down covers them
        self.layers = []
        for _ in slot_positions:
            b = CALayer.layer()
            b.setBounds_(NSMakeRect(0, 0, 2 * RADIUS, 2 * RADIUS))
            b.setCornerRadius_(RADIUS)
            b.setBackgroundColor_(BLACK.CGColor())
            b.setBorderWidth_(1.0)
            b.setBorderColor_(FAINT.CGColor())
            b.setPosition_(home)
            b.setOpacity_(0)
            parent.addSublayer_(b)
            self.layers.append((b, island.symbol_layer(b, RADIUS, RADIUS)))

    # ---- contents ----

    def track(self):
        """The buttons laid out round the whole ring. A ring with few buttons has gaps, so it can
        still be turned: the buttons travel round the island and come back in at the other end."""
        return list(self.items) + [None] * max(0, self.slots - len(self.items))

    def shown(self):
        """What each slot shows right now, left to right; None is an empty slot."""
        track = self.track()
        return [track[(self.offset + i) % len(track)] for i in range(self.slots)]

    def set_items(self, items, keep_offset=False):
        self.items = list(items)
        size = len(self.track())
        if keep_offset:
            self.offset %= size
        else:                                       # few buttons start out together in the middle
            self.offset = -((self.slots - len(self.items)) // 2) % size if len(self.items) < self.slots else 0

    def scrolls(self):
        """True when some buttons are out of sight until the ring is turned."""
        return len(self.items) > self.slots

    def update(self):
        """Redraw every slot: icon, on / hover / selected state."""
        for i, item in enumerate(self.shown()):
            b, icon = self.layers[i]
            b.setHidden_(item is None)
            if item is None:
                continue
            active = bool(item.on and item.on())
            hovered = i == self.hover
            selected = self.selected is not None and item.key == self.selected
            fill = WHITE if active else (HOVER if (hovered or selected) else BLACK)
            b.setBackgroundColor_(fill.CGColor())
            b.setBorderColor_((WHITE if (hovered or selected) else FAINT).CGColor())
            b.setBorderWidth_(1.5 if selected else 1.0)
            self.island.set_symbol(icon, item.symbol, BLACK if active else WHITE, 14.0)

    # ---- hit-testing ----

    def slot_at(self, x, y):
        if not self.visible:
            return None
        shown = self.shown()
        for i, (bx, by) in enumerate(self.pos):
            if shown[i] is not None and i not in self.hidden and (x - bx) ** 2 + (y - by) ** 2 <= (RADIUS + 2) ** 2:
                return i
        return None

    def distance(self, x, y):
        """How far the point is from the nearest slot of this ring."""
        return min(math.hypot(x - bx, y - by) for bx, by in self.pos)

    # ---- animation ----

    def show(self, origin=None):
        """Fan the buttons out from `origin` (default: from behind the island)."""
        self.visible = True
        self.hover = None
        self.update()
        self._move(True, origin or self.home)

    def hide(self, origin=None):
        if not self.visible:
            return
        self.visible = False
        self.hover = None
        self.selected = None
        self._move(False, origin or self.home)

    def _move(self, opening, origin):
        start = CACurrentMediaTime()
        for i, (b, _) in enumerate(self.layers):
            target = self.pos[i] if opening else origin
            pres = b.presentationLayer() or b
            old_pos = pres.position() if (not opening or pres.opacity() > 0.01) else NSMakePoint(*origin)
            old_opacity = pres.opacity()
            new_opacity = 1.0 if (opening and i not in self.hidden) else 0.0

            def apply(b=b, target=target, new_opacity=new_opacity):
                b.setPosition_(target)
                b.setOpacity_(new_opacity)
            no_anim(apply)
            begin = start + (i * 0.024 if opening else 0.0)     # staggered fan-out, left to right
            move = spring("position", NSValue.valueWithPoint_(old_pos),
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

    def pop(self):
        """A little bounce, so swapping the contents reads as a new set of buttons."""
        for b, _ in self.layers:
            a = CAKeyframeAnimation.animationWithKeyPath_("transform.scale")
            a.setValues_([1.0, 0.72, 1.06, 1.0])
            a.setDuration_(0.32)
            b.addAnimation_forKey_(a, "pop")

    def rotate(self, step):
        """Turn the ring one button: every button glides to its neighbour's slot.

        Each button starts from wherever its neighbour is *on screen right now*, so a new step
        taken while the previous one is still moving carries on smoothly instead of snapping back.
        """
        if not self.items:
            return False
        on_screen = [(b.presentationLayer() or b).position() for b, _ in self.layers]
        self.offset = (self.offset + step) % len(self.track())
        self.update()
        ease = CAMediaTimingFunction.functionWithName_("easeOut")
        for i, (b, _) in enumerate(self.layers):
            source = i + step
            entering = not 0 <= source < self.slots
            if entering:        # slides in from just past the end of the ring, fading up
                (x, y), (nx, ny) = self.pos[i], self.pos[i - step]
                start = NSMakePoint(x + (x - nx) * 0.6, y + (y - ny) * 0.6)
            else:
                start = on_screen[source]
            move = CABasicAnimation.animationWithKeyPath_("position")
            move.setFromValue_(NSValue.valueWithPoint_(start))
            move.setToValue_(NSValue.valueWithPoint_(NSMakePoint(*self.pos[i])))
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
        return True

    def move_to(self, slot_positions):
        """The island changed width: re-seat the slots (and the buttons, if they are out)."""
        self.pos = slot_positions
        if self.visible:
            for (b, _), point in zip(self.layers, slot_positions):
                b.setPosition_(point)       # implicit animation: they slide across

    # ---- making room for a drop-down ----

    def hide_under(self, rect, except_slot=None):
        """Tuck away the buttons a drop-down panel (x0, y0, x1, y1) would sit under."""
        x0, y0, x1, y1 = rect
        self.hidden = tuple(i for i, (x, y) in enumerate(self.pos)
                            if i != except_slot and x0 - RADIUS < x < x1 + RADIUS and y0 - RADIUS < y < y1 + RADIUS)
        for i in self.hidden:
            self.layers[i][0].setOpacity_(0)

    def unhide(self):
        for i in self.hidden:
            self.layers[i][0].setOpacity_(1 if self.visible else 0)
        self.hidden = ()
