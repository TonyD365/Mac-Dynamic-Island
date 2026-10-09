"""User settings, persisted as JSON in ~/Library/Application Support/DynamicIsland."""
import copy
import json
import os

import focus

PATH = os.path.expanduser("~/Library/Application Support/DynamicIsland/settings.json")
DEFAULTS = {
    "privacy": True,        # camera / microphone dots and alerts
    "music": True,          # now-playing info and controls
    "power": True,          # charger plug / unplug alerts
    "glow": True,           # coloured glow pulses
    "clock24": True,        # 24-hour clock
    "focus_minutes": 25,
    "bluetooth": True,      # device connected / disconnected alerts
    "hud": True,            # volume and brightness bar
    "scroll_volume": True,  # scroll on the island to change the volume
    "stats": True,          # CPU / memory line when nothing else is going on
    "downloads": True,      # progress of browser downloads (reads the Downloads folder)
    "health": True,         # warnings when the disk is nearly full or the Mac is overheating
    "replace_hud": False,   # catch the volume / brightness keys so macOS's own panel stays away (same access)
    "mirror_hide": False,   # clear macOS's own banner once the island has shown the notification
    "mirror": False,        # show other apps' notifications (needs Accessibility access)
    "background": "",       # "", a preset name, or "custom"
    "background_custom": "",
    "background_dim": 0.45,
    "lockscreen": True,     # stay visible on the lock screen
    "welcome": True,        # greeting animation after logging in / unlocking
    "toured": False,        # the guided tour has been shown once
    "auto_update": True,    # download and open new releases without being asked
    "focus_modes": [],      # filled with focus.DEFAULT_MODES on first run; edited in the Focus Modes window
    "calendar": False,      # show the next calendar event (asks for calendar access when switched on)
    "shelf": [],            # files on the Shelf: their paths inside the Shelf folder
    "shelf_origins": {},    # for each of those, the folder it was moved from
    "categories": [],       # [{"name", "icon", "items": [button ids]}]; filled in by menu.normalize
    "known_items": [],      # button ids that existed when the categories were last saved
    "custom_buttons": [],   # [{"name", "icon", "kind", "target"}], edited in the Custom Buttons window
}
FOCUS_CHOICES = (15, 25, 45, 60)


def load():
    values = dict(DEFAULTS)
    values["custom_buttons"] = []     # never share the default list
    values["categories"] = []
    values["shelf"] = []
    values["shelf_origins"] = {}
    values["known_items"] = []
    values["focus_modes"] = copy.deepcopy(focus.DEFAULT_MODES)
    try:
        with open(PATH, encoding="utf-8") as f:
            saved = json.load(f)
        values.update({k: v for k, v in saved.items() if k in DEFAULTS and type(v) is type(DEFAULTS[k])})
    except (OSError, ValueError):
        pass
    if not values["focus_modes"]:
        values["focus_modes"] = copy.deepcopy(focus.DEFAULT_MODES)
    return values


def save(values):
    try:
        os.makedirs(os.path.dirname(PATH), exist_ok=True)
        with open(PATH, "w", encoding="utf-8") as f:
            json.dump(values, f, indent=2)
    except OSError:
        pass
