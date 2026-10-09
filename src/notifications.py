"""Mirror macOS notification banners onto the island.

macOS gives an app no way to be told about other apps' notifications. What it does allow, once the
user has granted Accessibility access, is reading what is on screen; so the banners are read from
Notification Center's own windows. Nothing is read unless Mirror Notifications is switched on.
"""
import subprocess

import Quartz
from AppKit import NSRunningApplication

try:
    import ApplicationServices as AS
except ImportError:                 # the framework bindings are not installed
    AS = None

CENTER = "com.apple.notificationcenterui"
OWN_NAME = "Dynamic Island"
MAX_DEPTH = 6
STOCK_ACTIONS = {"Show Details", "Show", "Close", "Clear", "Clear All", "Show More", "Show Less"}    # every banner has these
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


def buttons(action_names):
    """The notification's own buttons ('Reply', 'Allow', ...) among a banner's accessibility actions."""
    names = []
    for action in action_names or []:
        text = str(action)
        if text.startswith("Name:"):
            name = text[5:].split("\n")[0].strip()
            if name and name not in STOCK_ACTIONS and name not in names:
                names.append(name)
    return names


def _frame(element):
    """(x, y, width, height) of an element on screen, measured from the top-left; None if it has none."""
    try:
        ok1, point = AS.AXValueGetValue(_attr(element, "AXPosition"), AS.kAXValueCGPointType, None)
        ok2, size = AS.AXValueGetValue(_attr(element, "AXSize"), AS.kAXValueCGSizeType, None)
    except Exception:
        return None
    return (point.x, point.y, size.width, size.height) if ok1 and ok2 else None


def _pictures(element, depth=0):
    """The image elements inside a banner (an attached photo, a sender's picture)."""
    found = []
    for child in _attr(element, "AXChildren") or []:
        if _attr(child, "AXRole") == "AXImage":
            found.append(child)
        elif depth < 3:
            found += _pictures(child, depth + 1)
    return found


def picture(notice):
    """A snapshot of the largest picture shown in the banner, as a CGImage; None if it has none, it is
    tiny, or macOS has not granted Screen Recording (the pixels can only be had from the screen)."""
    frames = [f for f in (_frame(e) for e in notice.get("pictures", [])) if f and f[2] >= 20 and f[3] >= 20]
    if not frames:
        return None
    x, y, w, h = max(frames, key=lambda f: f[2] * f[3])
    return Quartz.CGWindowListCreateImage(Quartz.CGRectMake(x, y, w, h), Quartz.kCGWindowListOptionOnScreenOnly,
                                          Quartz.kCGNullWindowID, Quartz.kCGWindowImageBestResolution)


def _collect(element, depth, found):
    if str(_attr(element, "AXSubrole") or "").startswith("AXNotificationCenter"):      # a banner or an alert
        texts = {}
        for child in _attr(element, "AXChildren") or []:
            if _attr(child, "AXRole") == "AXStaticText":
                texts[str(_attr(child, "AXIdentifier") or len(texts))] = str(_attr(child, "AXValue") or "")
        description = str(_attr(element, "AXDescription") or "")
        ident = str(_attr(element, "AXIdentifier") or description)
        error, actions = AS.AXUIElementCopyActionNames(element, None)
        found[ident] = dict(parse(description, texts), element=element, id=ident,
                            actions=buttons(actions if error == 0 else []), pictures=_pictures(element))
    elif depth < MAX_DEPTH:
        for child in _attr(element, "AXChildren") or []:
            _collect(child, depth + 1, found)


def banners():
    """The notifications on screen right now: {id: {'app', 'title', 'body', 'element'}}."""
    found = {}
    for app in NSRunningApplication.runningApplicationsWithBundleIdentifier_(CENTER):
        element = AS.AXUIElementCreateApplication(app.processIdentifier())
        AS.AXUIElementSetMessagingTimeout(element, 0.5)
        for window in _attr(element, "AXWindows") or []:
            _collect(window, 0, found)
    return found


def act(element, name):
    """Do to a banner what a click would: "AXPress" opens it, "Close" clears it. False once it has gone."""
    if AS is None or element is None:
        return False
    error, actions = AS.AXUIElementCopyActionNames(element, None)
    for action in actions or [] if error == 0 else []:
        if str(action) == name or str(action).startswith("Name:%s\n" % name):
            return AS.AXUIElementPerformAction(element, action) == 0
    return False


def open_notice(notice):
    """Open a notification as clicking its banner would; if the banner has gone, bring up its app."""
    if not act(notice.get("element"), "AXPress") and notice.get("app"):
        subprocess.Popen(["/usr/bin/open", "-a", notice["app"]], stderr=subprocess.DEVNULL)


def fresh(found, seen):
    """Which of `found` to announce, given the ids `seen` on the previous look (None: the first look)."""
    if seen is None:
        return []
    new = [v for k, v in found.items() if k not in seen and v["app"] != OWN_NAME]
    return new if len(new) <= BURST else []
