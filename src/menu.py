"""What the rings contain: the action buttons, how they are grouped into categories, and the settings.

Inner ring, normally:      one button per category, then Settings.
Inner ring, in Settings:   Back, the settings groups, Quit.
Outer ring:                the buttons of whichever inner button is open.
"""
import copy
import uuid
from types import SimpleNamespace

import about
import autostart
import backgrounds
import custom_buttons
import monitors
import settings

# The built-in buttons and the category each one starts in.
DEFAULT_CATEGORIES = [
    {"name": "Time", "icon": "clock.fill", "items": ["focus", "timer", "stopwatch"]},
    {"name": "Media", "icon": "play.fill", "items": ["previous", "play", "next", "mute", "mic"]},
    {"name": "System", "icon": "switch.2", "items": ["dark", "awake", "lock", "sleep"]},
    {"name": "Tools", "icon": "wrench.and.screwdriver.fill", "items": ["screenshot", "color", "calculator"]},
    {"name": "Files", "icon": "folder.fill", "items": ["downloads", "desktop", "documents", "applications"]},
    {"name": "Apps", "icon": "square.grid.2x2.fill", "items": ["activity", "system_settings", "terminal"]},
    {"name": "My Buttons", "icon": "star.fill", "items": []},
]
CUSTOM_CATEGORY = "My Buttons"      # where newly made custom buttons appear
CATEGORY_ICONS = (
    ("clock.fill", "Clock"), ("timer", "Timer"), ("play.fill", "Play"), ("switch.2", "Switches"), ("wrench.and.screwdriver.fill", "Tools"),
    ("star.fill", "Star"), ("folder.fill", "Folder"), ("bolt.fill", "Bolt"), ("heart.fill", "Heart"),
    ("globe", "Globe"), ("music.note", "Music"), ("gamecontroller.fill", "Game"), ("book.fill", "Book"),
    ("briefcase.fill", "Work"), ("house.fill", "Home"), ("paintbrush.fill", "Design"),
    ("terminal.fill", "Terminal"), ("square.grid.2x2.fill", "Grid"),
)


def entry(key, symbol, label, status, action=None, on=None, safe=False, children=None, image=None):
    """One ring button. `children` (a list of entries) makes it open the outer ring instead of acting.
    `image` is the path of a picture to show in place of the symbol."""
    return SimpleNamespace(key=key, symbol=symbol, label=label, status=status, action=action, on=on,
                           safe=safe, children=children, image=image)


def custom_id(button):
    return "custom:" + button["id"]


def normalize(values):
    """Keep the saved categories consistent with the buttons that exist. Returns True if it changed anything."""
    before = copy.deepcopy((values["categories"], values["known_items"], values["custom_buttons"]))
    for button in values["custom_buttons"]:
        if not button.get("id"):
            button["id"] = uuid.uuid4().hex[:8]
    builtin = [item for category in DEFAULT_CATEGORIES for item in category["items"]]
    custom = [custom_id(b) for b in values["custom_buttons"]]
    valid = set(builtin) | set(custom)

    if not values["categories"] and not values["known_items"]:          # first run
        values["categories"] = copy.deepcopy(DEFAULT_CATEGORIES)

    seen = set()
    for category in values["categories"]:
        category.setdefault("name", "Untitled")
        category.setdefault("icon", "star.fill")
        kept = []
        for item in category.get("items", []):
            if item in valid and item not in seen:      # drop buttons that no longer exist, and repeats
                seen.add(item)
                kept.append(item)
        category["items"] = kept

    # Buttons that did not exist when the categories were last saved (a new custom button, or one
    # added by an update) go to their home category. Ones the user took out stay out.
    known = set(values["known_items"])
    home = {item: category["name"] for category in DEFAULT_CATEGORIES for item in category["items"]}
    for item in builtin + custom:
        if item in known or item in seen:
            continue
        wanted = home.get(item, CUSTOM_CATEGORY)
        target = next((c for c in values["categories"] if c["name"] == wanted), None)
        if target is None:
            icon = next((c["icon"] for c in DEFAULT_CATEGORIES if c["name"] == wanted), "star.fill")
            target = {"name": wanted, "icon": icon, "items": []}
            values["categories"].append(target)
        target["items"].append(item)
    values["known_items"] = sorted(valid)
    return before != (values["categories"], values["known_items"], values["custom_buttons"])


def unused(values):
    """Buttons that exist but are in no category."""
    placed = {item for category in values["categories"] for item in category["items"]}
    return [item for item in all_ids(values) if item not in placed]


def all_ids(values):
    return ([item for category in DEFAULT_CATEGORIES for item in category["items"]]
            + [custom_id(b) for b in values["custom_buttons"] if b.get("id")])


def list_image(values, item):
    """The image to show beside a button in the Categories window."""
    if item.startswith("custom:"):
        button = next((b for b in values["custom_buttons"] if custom_id(b) == item), None)
        if button is not None:
            return custom_buttons.button_image(button)
    from AppKit import NSImage
    return NSImage.imageWithSystemSymbolName_accessibilityDescription_(describe_id(values, item)[0], None)


def describe_id(values, item):
    """(symbol, label) for a button id, without needing a running island: for the editor window."""
    if item.startswith("custom:"):
        button = next((b for b in values["custom_buttons"] if custom_id(b) == item), None)
        return (button.get("icon", "star.fill"), button.get("name", "Custom")) if button else ("questionmark", item)
    return BUILTIN_LOOK.get(item, ("questionmark", item))


BUILTIN_LOOK = {
    "focus": ("timer", "Focus"),
    "timer": ("hourglass", "Timer"),
    "stopwatch": ("stopwatch.fill", "Stopwatch"),
    "previous": ("backward.fill", "Previous"),
    "play": ("playpause.fill", "Play / Pause"),
    "next": ("forward.fill", "Next"),
    "mute": ("speaker.slash.fill", "Mute"),
    "mic": ("mic.slash.fill", "Mute Microphone"),
    "dark": ("circle.lefthalf.filled", "Dark Mode"),
    "awake": ("cup.and.saucer.fill", "Keep Awake"),
    "lock": ("lock.fill", "Lock Screen"),
    "sleep": ("moon.zzz.fill", "Sleep Display"),
    "screenshot": ("camera.viewfinder", "Screenshot"),
    "color": ("eyedropper", "Color Picker"),
    "calculator": ("plus.forwardslash.minus", "Calculator"),
    "downloads": ("arrow.down.to.line", "Downloads"),
    "desktop": ("menubar.dock.rectangle", "Desktop"),
    "documents": ("doc.fill", "Documents"),
    "applications": ("square.grid.3x3.fill", "Applications"),
    "activity": ("gauge.medium", "Activity Monitor"),
    "system_settings": ("gearshape", "System Settings"),
    "terminal": ("terminal.fill", "Terminal"),
}


def actions(island):
    """Every action button that exists, by id."""
    S, A, raw = island.settings, island.actions, island.monitors

    def toggle_mute():
        raw.muted = not raw.muted          # shown at once; the next poll confirms it
        monitors.set_mute(raw.muted)

    def make(key, status, action, on=None, safe=False):
        symbol, label = BUILTIN_LOOK[key]
        return entry(key, symbol, label, status, action, on, safe)

    def playing():
        music = raw.music if S["music"] else None
        return bool(music and music.get("playing"))

    def now_title():
        music = raw.music if S["music"] else None
        return music["title"] if music else "Nothing is playing"

    found = {
        "focus": make("focus",
                      lambda: ("%s  ·  running" % (island.focus_mode or {}).get("name", "Focus")) if island.pomo_end
                      else "Choose a focus mode",
                      island.show_focus_dropdown, lambda: bool(island.pomo_end)),
        "timer": make("timer",
                      lambda: ("%s left  ·  %d running" % (island.countdown(island.timer_end), len(island.timers)))
                      if island.timer_end
                      else "Count down from a set time",
                      island.show_timer_dropdown, lambda: bool(island.timer_end), safe=True),
        "stopwatch": make("stopwatch",
                          lambda: ("%s  ·  click to stop" % island.elapsed(island.stopwatch_start))
                          if island.stopwatch_start else "Click to start",
                          island.toggle_stopwatch, lambda: bool(island.stopwatch_start), safe=True),
        "previous": make("previous", now_title, lambda: island.player("previous track"), safe=True),
        "play": make("play", now_title, lambda: island.player("playpause"), playing, safe=True),
        "next": make("next", now_title, lambda: island.player("next track"), safe=True),
        "mute": make("mute", lambda: "Muted" if raw.muted else "Sound on", toggle_mute,
                     lambda: bool(raw.muted), safe=True),
        "mic": make("mic", lambda: "Silenced for every app" if raw.mic_muted else "Microphone on",
                    island.toggle_mic, lambda: bool(raw.mic_muted), safe=True),
        "dark": make("dark", lambda: "On" if A.is_dark() else "Off", A.toggle_dark, A.is_dark),
        "awake": make("awake", lambda: "On" if A.is_awake() else "Off", A.toggle_awake, A.is_awake, safe=True),
        "lock": make("lock", lambda: "Lock this Mac now", island.lock_screen),
        "sleep": make("sleep", lambda: "Turn the screen off now", island.sleep_display, safe=True),
        "screenshot": make("screenshot", lambda: "Drag an area  ·  copied to clipboard", island.screenshot),
        "color": make("color", lambda: "Pick a colour  ·  copies its hex code", island.pick_color),
        "calculator": make("calculator", lambda: "Open Calculator", lambda: island.launch("Calculator")),
        "downloads": make("downloads", lambda: "Open the Downloads folder", lambda: island.open_folder("~/Downloads")),
        "desktop": make("desktop", lambda: "Open the Desktop folder", lambda: island.open_folder("~/Desktop")),
        "documents": make("documents", lambda: "Open the Documents folder", lambda: island.open_folder("~/Documents")),
        "applications": make("applications", lambda: "Open the Applications folder",
                             lambda: island.open_folder("/Applications")),
        "activity": make("activity", lambda: "See what is using the Mac", lambda: island.launch("Activity Monitor")),
        "system_settings": make("system_settings", lambda: "Open System Settings",
                                lambda: island.launch("System Settings")),
        "terminal": make("terminal", lambda: "Open Terminal", lambda: island.launch("Terminal")),
    }
    for button in S["custom_buttons"]:
        if button.get("id"):
            found[custom_id(button)] = entry(
                custom_id(button), button.get("icon", "star.fill"), button.get("name", "Custom"),
                lambda b=button: custom_buttons.describe(b), lambda b=button: island.run_custom(b),
                image=custom_buttons.picture_of(button))
    return found


def main_entries(island):
    """Inner ring: the categories that have something in them, then Settings."""
    available = actions(island)
    result = []
    for index, category in enumerate(island.settings["categories"]):
        children = [available[item] for item in category["items"] if item in available]
        if island.locked:               # on the lock screen only the harmless buttons remain
            children = [c for c in children if c.safe]
        if not children:
            continue
        result.append(entry("category:%d" % index, category.get("icon", "star.fill"), category.get("name", ""),
                            lambda n=len(children): "%d button%s" % (n, "" if n == 1 else "s"),
                            children=children, safe=True))
    if not island.locked:
        result.append(entry("settings", "gearshape.fill", "Settings", lambda: "Customize the island",
                            lambda: island.set_page("settings")))
    return result


def settings_entries(island):
    """Inner ring while in Settings: Back, the groups, Quit."""
    S = island.settings

    def toggle(symbol, label, key, note=""):
        def flip():
            S[key] = not S[key]
            settings.save(S)
        return entry("set:" + key, symbol, label, lambda: ("On" if S[key] else "Off") + note, flip, lambda: S[key])

    def cycle_background():
        S["background"] = backgrounds.next_choice(S)
        settings.save(S)
        island.apply_background()

    def cycle_dim():
        S["background_dim"] = backgrounds.next_dim(S["background_dim"])
        settings.save(S)
        island.apply_background()

    def group(key, symbol, label, children):
        return entry("group:" + key, symbol, label, lambda n=len(children): "%d settings" % n, children=children)

    return [
        entry("back", "chevron.left", "Back", lambda: "Return to the categories", lambda: island.set_page("main")),
        group("alerts", "bell.fill", "Alerts", [
            toggle("video.fill", "Camera & Mic Alerts", "privacy"),
            toggle("music.note", "Now Playing", "music"),
            toggle("bolt.fill", "Power Alerts", "power"),
            toggle("headphones", "Bluetooth Alerts", "bluetooth"),
            toggle("arrow.down.circle.fill", "Download Progress", "downloads"),
            toggle("exclamationmark.triangle.fill", "Storage & Heat Warnings", "health"),
            entry("set:mirror", "bell.badge.fill", "Mirror Notifications", island.mirror_status,
                  island.toggle_mirror, lambda: S["mirror"]),
            toggle("slider.horizontal.3", "Volume & Brightness Bar", "hud"),
            entry("set:replace_hud", "rectangle.slash", "Hide the System's Volume Panel", island.hud_keys_status,
                  island.toggle_hud_keys, lambda: S["replace_hud"]),
            toggle("hand.wave.fill", "Welcome Animation", "welcome"),
            entry("set:calendar", "calendar", "Calendar Events", island.calendar_status, island.toggle_calendar,
                  lambda: S["calendar"]),
        ]),
        group("general", "gearshape.2.fill", "General", [
            toggle("speaker.wave.2.fill", "Scroll to Change Volume", "scroll_volume"),
            toggle("cpu", "System Stats", "stats"),
            toggle("clock.fill", "24-Hour Clock", "clock24"),
            entry("set:login", "power", "Launch at Login", lambda: "On" if autostart.is_enabled() else "Off",
                  lambda: autostart.set_enabled(not autostart.is_enabled()), autostart.is_enabled),
            toggle("lock.display", "Show on Lock Screen", "lockscreen", "  ·  applies after restart"),
            toggle("arrow.down.app.fill", "Automatic Updates", "auto_update"),
            entry("set:check", "arrow.triangle.2.circlepath", "Check for Updates", island.update_status,
                  island.check_for_updates),
            entry("set:tour", "play.rectangle.fill", "Replay the Tour", lambda: "A short walk-through of the island",
                  island.replay_tour),
        ]),
        group("look", "paintbrush.fill", "Appearance", [
            toggle("sparkles", "Glow Effects", "glow"),
            entry("set:background", "photo.fill", "Background",
                  lambda: "%s  ·  click for next" % backgrounds.label(S), cycle_background,
                  lambda: bool(S["background"])),
            entry("set:image", "folder.fill", "Choose Image…", lambda: "Use your own picture", island.choose_image),
            entry("set:dim", "circle.righthalf.filled", "Dimming",
                  lambda: "%s  ·  click to change" % backgrounds.dim_label(S["background_dim"]), cycle_dim),
        ]),
        group("customize", "square.grid.2x2.fill", "Customize", [
            entry("set:categories", "rectangle.3.group.fill", "Categories",
                  lambda: "%d categories  ·  click to edit" % len(S["categories"]), island.edit_categories),
            entry("set:buttons", "plus", "Custom Buttons",
                  lambda: "%d added  ·  click to edit" % len(S["custom_buttons"]), island.edit_custom_buttons),
            entry("set:focus", "list.bullet", "Focus Modes",
                  lambda: "%d modes  ·  click to edit" % len(S["focus_modes"]), island.edit_focus_modes),
        ]),
        entry("about", "info", "About Dynamic Island", lambda: about.version_text() + "  ·  by " + about.AUTHOR,
              island.show_about),
        entry("quit", "xmark", "Quit Dynamic Island", lambda: "Close the island completely", island.request_quit),
    ]
