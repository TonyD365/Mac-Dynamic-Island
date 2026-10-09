"""Mirror macOS notification banners onto the island.

macOS gives an app no way to be told about other apps' notifications. What it does allow, once the
user has granted Accessibility access, is reading what is on screen; so the banners are read from
Notification Center's own windows. Nothing is read unless Mirror Notifications is switched on.
"""
from AppKit import NSRunningApplication

try:
    import ApplicationServices as AS
except ImportError:                 # the framework bindings are not installed
    AS = None

CENTER = "com.apple.notificationcenterui"
OWN_NAME = "Dynamic Island"
MAX_DEPTH = 6
BURST = 3           # more new ones than this at once is the Notification Center list being opened


def available():
    return AS is not None


def trusted(prompt=False):
    """Has the user granted Accessibility access? With prompt=True macOS offers to open the setting."""
    if AS is None:
        return False
    if prompt:
        return bool(AS.AXIsProcessTrustedWithOptions({AS.kAXTrustedCheckOptionPrompt: True}))
    return bool(AS.AXIsProcessTrusted())


def parse(description, texts):
    """{'app', 'title', 'body'} from a banner's description ('App, title, ...') and its labelled texts."""
    app = (description or "").split(",")[0].strip()
    title = texts.get("title") or app
    body = "  ·  ".join(t for t in (texts.get("subtitle"), texts.get("body")) if t)
    return {"app": app, "title": title, "body": body or ("" if title == app else app)}


def _attr(element, name):
    error, value = AS.AXUIElementCopyAttributeValue(element, name, None)
    return value if error == 0 else None


def _collect(element, depth, found):
    if str(_attr(element, "AXSubrole") or "").startswith("AXNotificationCenter"):      # a banner or an alert
        texts = {}
        for child in _attr(element, "AXChildren") or []:
            if _attr(child, "AXRole") == "AXStaticText":
                texts[str(_attr(child, "AXIdentifier") or len(texts))] = str(_attr(child, "AXValue") or "")
        description = str(_attr(element, "AXDescription") or "")
        found[str(_attr(element, "AXIdentifier") or description)] = parse(description, texts)
    elif depth < MAX_DEPTH:
        for child in _attr(element, "AXChildren") or []:
            _collect(child, depth + 1, found)


def banners():
    """The notifications on screen right now: {id: {'app', 'title', 'body'}}."""
    found = {}
    for app in NSRunningApplication.runningApplicationsWithBundleIdentifier_(CENTER):
        element = AS.AXUIElementCreateApplication(app.processIdentifier())
        AS.AXUIElementSetMessagingTimeout(element, 0.5)
        for window in _attr(element, "AXWindows") or []:
            _collect(window, 0, found)
    return found


def fresh(found, seen):
    """Which of `found` to announce, given the ids `seen` on the previous look (None: the first look)."""
    if seen is None:
        return []
    new = [v for k, v in found.items() if k not in seen and v["app"] != OWN_NAME]
    return new if len(new) <= BURST else []
