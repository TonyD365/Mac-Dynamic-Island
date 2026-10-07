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
    "background": "",       # "", a preset name, or "custom"
    "background_custom": "",
    "background_dim": 0.45,
    "lockscreen": True,     # stay visible on the lock screen
    "welcome": True,        # greeting animation after logging in / unlocking
    "focus_modes": [],      # filled with focus.DEFAULT_MODES on first run; edited in the Focus Modes window
    "custom_buttons": [],   # [{"name", "icon", "kind", "target"}], edited in the Custom Buttons window
}
FOCUS_CHOICES = (15, 25, 45, 60)


def load():
    values = dict(DEFAULTS)
    values["custom_buttons"] = []     # never share the default list
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
