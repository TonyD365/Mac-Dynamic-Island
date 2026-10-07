"""The guided tour: the island walks through what it can do, one short caption at a time.

Shown once, the first time the app runs, and again whenever it is asked for from Settings.
A click on the island ends it.
"""
from ui import BLUE, PINK, PURPLE

STEP_SECONDS = 3.6


class Tour:
    def __init__(self, island):
        self.island = island
        self.active = False
        self.pending = False        # wanted, but waiting for the screen to be unlocked
        self.drawer = False         # hold the Shelf drawer open for the step about it
        self.index = -1
        self.until = 0.0

    def steps(self):
        """(title, subtitle, what the island does) for each stop. Captions must fit the island:
        about 24 characters for the title and 30 for the subtitle."""
        island = self.island
        return [
            ("Welcome", "A quick tour  ·  click to skip", lambda: island.pulse(PINK)),
            ("Hover to open", "Clock, battery, now playing", None),
            ("Click for the rings", "Inner ring: categories", island.open_menu),
            ("Pick a category", "Its buttons fan out further", self.open_first_category),
            ("Scroll to turn a ring", "More buttons than fit at once", self.turn_rings),
            ("Settings comes last", "Make it yours from there", self.point_at_settings),
            ("Drop files on the island", "They wait on the Shelf  →", self.show_drawer),
            ("Scroll here for volume", "Drag the bar to seek", self.hide_drawer),
            ("That's the tour", "Replay: Settings › General", lambda: island.pulse(PURPLE)),
        ]

    # ---- running it ----

    def start(self):
        """Begin the tour (or queue it, if the screen is locked)."""
        if self.island.locked or not self.island.screen_ok:
            self.pending = True
            return
        self.pending = False
        self.active = True
        self.index = -1
        self.until = 0.0

    def stop(self):
        if not self.active:
            return
        self.active = False
        self.drawer = False
        island = self.island
        island.inner.hover = None
        if island.menu_open:
            island.close_menu()
        island.peek_until = 0.0

    def text(self):
        title, subtitle, _ = self.steps()[max(0, self.index)]
        return title, subtitle

    def tick(self, now):
        """Called on every tick of the island's main loop."""
        island = self.island
        if self.pending and not island.locked and island.screen_ok:
            self.start()
        if not self.active:
            return
        if island.locked:               # locked half-way through: put it away and offer it again later
            self.stop()
            self.pending = True
            return
        island.peek_until = max(island.peek_until, now + 0.5)       # stay open throughout
        island.menu_seen = now                                      # and keep the rings from folding
        if now < self.until:
            return
        steps = self.steps()
        self.index += 1
        if self.index >= len(steps):
            self.stop()
            return
        self.until = now + STEP_SECONDS
        action = steps[self.index][2]
        if action is not None:
            action()
        island.refresh(now)

    # ---- what the island does at each stop ----

    def open_first_category(self):
        island = self.island
        if not island.menu_open:
            island.open_menu()
        for slot, item in enumerate(island.inner.shown()):
            if item is not None and item.children:
                island.open_outer(item, island.inner.pos[slot])
                island.update_menu()
                return

    def turn_rings(self):
        island = self.island
        island.inner.rotate(1)
        if island.outer.visible:
            island.outer.rotate(1)
        island.pulse(BLUE)

    def point_at_settings(self):
        island = self.island
        island.close_outer()
        island.inner.set_items(island.inner_entries())       # back to where it started
        for slot, item in enumerate(island.inner.shown()):
            if item is not None and item.key == "settings":
                island.inner.hover = slot
        island.inner.update()

    def show_drawer(self):
        island = self.island
        island.inner.hover = None
        island.close_menu()
        self.drawer = True

    def hide_drawer(self):
        self.drawer = False
