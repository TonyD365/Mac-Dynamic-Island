"""Take over the keyboard's volume and brightness keys, so that only the island shows the change.

macOS draws its own volume / brightness panel whenever it handles one of those keys, and offers no
switch for it. So the keys are caught before macOS sees them (which needs Accessibility access) and
the island changes the level itself. Changes made any other way still bring up the system's panel.
"""
import Quartz
from AppKit import NSEvent

import monitors

SYSTEM_DEFINED = 14                 # NSEventTypeSystemDefined: the keyboard's special keys
MEDIA_KEYS = 8                      # ... its subtype for volume, brightness and playback keys
SOUND_UP, SOUND_DOWN, BRIGHT_UP, BRIGHT_DOWN, MUTE = 0, 1, 2, 3, 7
STEP = 1 / 16.0                     # one press, as macOS does it
FINE = STEP / 4                     # with Shift-Option held
SHIFT, OPTION = 1 << 17, 1 << 19
_TAP_DISABLED = (0xFFFFFFFE, 0xFFFFFFFF)


def decode(data1):
    """(key, is_down) from a media-key event's data1."""
    return (data1 & 0xFFFF0000) >> 16, ((data1 & 0xFF00) >> 8) == 0xA


def stepped(level, direction, fine=False):
    """The level one press up or down from `level`, landing on the same marks macOS uses."""
    step = FINE if fine else STEP
    return max(0.0, min(1.0, round((level + direction * step) / step) * step))


class KeyTap:
    def __init__(self, display):
        self.display = display          # callable: the built-in display's id
        self.tap = None
        self.source = None

    def running(self):
        return self.tap is not None

    def start(self):
        """Begin catching the keys. False if macOS refuses (no Accessibility access yet)."""
        if self.tap is not None:
            return True
        self._callback = self.handle    # the tap does not keep its callback alive
        self.tap = Quartz.CGEventTapCreate(Quartz.kCGSessionEventTap, Quartz.kCGHeadInsertEventTap,
                                           Quartz.kCGEventTapOptionDefault, 1 << SYSTEM_DEFINED,
                                           self._callback, None)
        if self.tap is None:
            return False
        self.source = Quartz.CFMachPortCreateRunLoopSource(None, self.tap, 0)
        Quartz.CFRunLoopAddSource(Quartz.CFRunLoopGetMain(), self.source, Quartz.kCFRunLoopCommonModes)
        Quartz.CGEventTapEnable(self.tap, True)
        return True

    def stop(self):
        if self.tap is None:
            return
        Quartz.CGEventTapEnable(self.tap, False)
        Quartz.CFRunLoopRemoveSource(Quartz.CFRunLoopGetMain(), self.source, Quartz.kCFRunLoopCommonModes)
        Quartz.CFMachPortInvalidate(self.tap)
        self.tap = self.source = None

    def handle(self, proxy, kind, event, refcon):
        """Called by macOS for each special-key event. Returning None swallows it."""
        try:
            if kind in _TAP_DISABLED:               # macOS switched the tap off (it was slow, or the user typed
                Quartz.CGEventTapEnable(self.tap, True)     # a password); switch it back on
                return event
            if kind != SYSTEM_DEFINED:
                return event
            ns = NSEvent.eventWithCGEvent_(event)
            if ns is None or ns.subtype() != MEDIA_KEYS:
                return event
            key, down = decode(ns.data1())
            if key not in (SOUND_UP, SOUND_DOWN, BRIGHT_UP, BRIGHT_DOWN, MUTE):
                return event                        # play / pause and the rest are left to macOS
            if down and not self.act(key, ns.modifierFlags()):
                return event                        # could not do it ourselves: let macOS
            return None
        except Exception:
            return event                            # never leave the keys dead

    def act(self, key, flags):
        fine = bool(flags & SHIFT) and bool(flags & OPTION)
        if key == MUTE:
            muted = monitors.muted()
            if muted is None:
                return False
            monitors.set_mute(not muted)
            return True
        if key in (SOUND_UP, SOUND_DOWN):
            level = monitors.volume()
            if level is None:
                return False                        # an output with no volume of its own (HDMI, some DACs)
            monitors.set_volume(stepped(level, 1 if key == SOUND_UP else -1, fine))
            if key == SOUND_UP and monitors.muted():
                monitors.set_mute(False)
            return True
        level = monitors.brightness(self.display())
        if level is None:
            return False
        return monitors.set_brightness(self.display(), stepped(level, 1 if key == BRIGHT_UP else -1, fine))
