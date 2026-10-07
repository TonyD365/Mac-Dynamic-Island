"""Background pictures for the expanded island: macOS's own nature wallpapers, or any image file."""
import os

import Quartz
from Foundation import NSURL

# Thumbnails of the wallpapers that ship with macOS; looked up at run time, nothing is copied.
PRESET_DIR = "/System/Library/Desktop Pictures/.thumbnails"
PRESET_NAMES = (     # photographs only
    "Big Sur Mountains", "Big Sur Coastline", "Big Sur Horizon", "Big Sur Road", "Big Sur Waters Edge",
    "Big Sur Shore Rocks", "Big Sur Aerial", "Catalina Sunset", "Catalina Evening", "Catalina Clouds",
    "Catalina Coast", "Catalina Shoreline",
)
DIM_CHOICES = ((0.3, "Light"), (0.45, "Medium"), (0.62, "Strong"))


def presets():
    found = []
    for name in PRESET_NAMES:
        path = os.path.join(PRESET_DIR, name + ".heic")
        if os.path.exists(path):
            found.append((name, path))
    return found


def choices(settings):
    """All selectable values, in cycling order: off, each preset, then the user's own image if set."""
    values = [""] + [name for name, _ in presets()]
    if settings["background_custom"] and os.path.exists(settings["background_custom"]):
        values.append("custom")
    return values


def next_choice(settings):
    values = choices(settings)
    current = settings["background"]
    return values[(values.index(current) + 1) % len(values)] if current in values else ""


def label(settings):
    current = settings["background"]
    if current == "custom":
        return os.path.basename(settings["background_custom"])
    return current or "None"


def path_for(settings):
    current = settings["background"]
    if current == "custom":
        return settings["background_custom"]
    return dict(presets()).get(current)


def dim_label(value):
    return min(DIM_CHOICES, key=lambda c: abs(c[0] - value))[1]


def next_dim(value):
    levels = [c[0] for c in DIM_CHOICES]
    nearest = min(levels, key=lambda v: abs(v - value))
    return levels[(levels.index(nearest) + 1) % len(levels)]


def load(path, max_pixels=900):
    """Decode a down-scaled CGImage, or None if the file can't be read."""
    if not path or not os.path.exists(path):
        return None
    source = Quartz.CGImageSourceCreateWithURL(NSURL.fileURLWithPath_(path), None)
    if source is None:
        return None
    return Quartz.CGImageSourceCreateThumbnailAtIndex(source, 0, {
        Quartz.kCGImageSourceCreateThumbnailFromImageAlways: True,
        Quartz.kCGImageSourceCreateThumbnailWithTransform: True,
        Quartz.kCGImageSourceThumbnailMaxPixelSize: max_pixels,
    })
