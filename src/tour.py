"""The guided tour: the island asks the user to try each thing, and moves on when they have.

Stops that need nothing done show a Next button instead. Skip is always there. The tour is
offered once, the first time the app runs, and again whenever it is asked for from Settings.
"""
from types import SimpleNamespace

from ui import GREEN, PINK, PURPLE

PAUSE_AFTER_DONE = 0.8      # let the user see what their action did before the next caption


def stop(title, subtitle, enter=None, done=None, next_button=False, ring=False, when=None, leave=None):
    """One stop of the tour.

    enter, leave -- called when the tour arrives at this stop and when it moves on
    done         -- returns True once the user has done what the caption asks; None if nothing is asked
    next_button  -- show Next (always on when nothing is asked; also on stops whose action is optional)
    ring         -- this stop needs the rings out; they are kept open
    when         -- returns False to leave this stop out
    """
    return SimpleNamespace(title=title, subtitle=subtitle, enter=enter, leave=leave, done=done,
                           next_button=next_button or done is None, ring=ring, when=when)


class Tour:
    def __init__(self, island):
        self.island = island
        self.active = False
        self.pending = False        # wanted, but waiting for the screen to be unlocked
        self.drawer = False         # hold the Shelf drawer open for the stops about it
        self.index = -1
        self.done_at = None         # when to move on, once the current stop's action is done
        # Things the user does that the island reports to the tour:
        self.turned = False         # scrolled a ring
        self.volume = False         # scrolled on the island
        self.shelf_before = 0       # files on the Shelf when the Shelf stop began
        self.added = False          # the user put a file on the Shelf during the tour

    def steps(self):
        """Captions must fit the island: about 24 characters for the title and 30 for the subtitle."""
        island = self.island
        shelf = lambda: len(island.settings["shelf"])
        return [
            stop("Welcome", "A quick tour of the island", enter=lambda: island.pulse(PINK)),
            stop("Point at the island", "Move the pointer onto it", done=lambda: island.on_island),
            stop("Click the island", "That opens the rings", done=lambda: island.menu_open),
            stop("Click a category", "Its buttons fan out further", ring=True, done=lambda: island.outer.visible),
            stop("Scroll over a ring", "That turns it", ring=True, enter=self.forget_turn, done=lambda: self.turned),
            stop("Click the gear", "Settings is the last button", ring=True, enter=self.back_to_categories,
                 done=lambda: island.menu_page == "settings"),
            stop("Settings work the same", "Groups open as outer rings", ring=True),
            stop("Drag a file onto me", "It moves to the Shelf  →", enter=self.open_drawer, leave=self.note_added,
                 done=lambda: shelf() > self.shelf_before, next_button=True),
            stop("Drag it out again", "Or click ↩ to put it back", done=lambda: shelf() <= self.shelf_before,
                 next_button=True, when=lambda: self.added),
            stop("Scroll on the island", "That changes the volume", enter=self.close_drawer,
                 done=lambda: self.volume, next_button=True),
            stop("That's the tour", "Replay: Settings › General", enter=lambda: island.pulse(PURPLE)),
        ]

    # ---- what the island shows ----

    def current(self):
        steps = self.steps()
        return steps[max(0, min(self.index, len(steps) - 1))]

    def text(self):
        step = self.current()
        return step.title, step.subtitle

    def shows_next(self):
        return self.active and self.done_at is None and self.current().next_button

    def next_label(self):
        return "Done" if self.index >= len(self.steps()) - 1 else "Next"

    def allows(self, item):
        """During the tour the rings are for looking at: categories open and the gear leads to
        Settings, but no button does its real job (nobody should lock the screen mid-tour)."""
        return item.children is not None or item.key == "settings"

    # ---- running it ----

    def start(self):
        """Begin the tour (or queue it, if the screen is locked)."""
        if self.island.locked or not self.island.screen_ok:
            self.pending = True
            return
        self.pending = False
        self.active = True
        self.index = -1
        self.done_at = None
        self.added = False
        self.advance()

    def stop(self):
        if not self.active:
            return
        self.active = False
        self.drawer = False
        self.done_at = None
        island = self.island
        if island.menu_open:
            island.close_menu()
        island.peek_until = 0.0
        island.refresh_tour_controls()

    def advance(self):
        """Go to the next stop that applies."""
        island = self.island
        steps = self.steps()
        if 0 <= self.index < len(steps) and steps[self.index].leave is not None:
            steps[self.index].leave()
        self.done_at = None
        while True:
            self.index += 1
            if self.index >= len(steps):
                self.stop()
                return
            step = steps[self.index]
            if step.when is None or step.when():
                break
        if not step.ring and island.menu_open:      # this stop starts with the rings folded
            island.close_menu()
        if step.enter is not None:
            step.enter()
        island.refresh_tour_controls()

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
        step = self.current()
        if step.ring:
            if not island.menu_open:                                # folded by a stray click: bring them back
                island.open_menu()
            island.menu_seen = now                                  # and don't let them fold by themselves
        if self.done_at is not None:
            if now >= self.done_at:
                self.advance()
        elif step.done is not None and step.done():
            self.done_at = now + PAUSE_AFTER_DONE
            island.pulse(GREEN)
            island.refresh_tour_controls()

    # ---- setting each stop up ----

    def forget_turn(self):
        self.turned = False

    def back_to_categories(self):
        island = self.island
        if island.menu_open and island.menu_page != "main":
            island.set_page("main")
        island.close_outer()

    def open_drawer(self):
        self.shelf_before = len(self.island.settings["shelf"])
        self.drawer = True

    def note_added(self):
        self.added = len(self.island.settings["shelf"]) > self.shelf_before

    def close_drawer(self):
        self.drawer = False
        self.volume = False
